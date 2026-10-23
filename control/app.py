"""Authenticated Media Stack API and frontend."""

from datetime import timedelta
import hashlib
import hmac
import os
from pathlib import Path
import secrets
import threading
import time

from flask import Flask, jsonify, request, send_from_directory, session
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix

from .integrations import (
    Client,
    ServiceError,
    default_url,
    local_key,
    snapshots,
    validate_url,
)
from .operations import Operations
from .state import SERVICES, Store, now
from .storage import Storage

ROOT = Path(__file__).resolve().parents[1]


def create_app(settings=None):
    app = Flask(__name__, static_folder=None)
    app.config.update(
        STATE_DIR=os.environ.get("PANEL_STATE_DIR", str(ROOT / "config/portal")),
        DATA_DIR=os.environ.get("PANEL_DATA_DIR", "/data"),
        KEY_DIR=os.environ.get("PANEL_KEY_DIR", "/connections"),
        DATA_HOST_PATH=os.environ.get("DATA_HOST_PATH", ""),
        MAX_CONTENT_LENGTH=32768,
        SESSION_COOKIE_NAME="media_stack_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_SECURE=os.environ.get("PANEL_COOKIE_SECURE") == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
    )
    if settings:
        app.config.update(settings)
    if os.environ.get("PANEL_TRUST_PROXY") == "1":
        app.wsgi_app = ProxyFix(
            app.wsgi_app, x_for=0, x_proto=1, x_host=0, x_port=0, x_prefix=0
        )
    store = Store(app.config["STATE_DIR"])
    app.secret_key = store.data["secret"]
    storage = Storage(app.config["DATA_DIR"], app.config["DATA_HOST_PATH"])
    operations = Operations(store, storage, app.config["KEY_DIR"])
    app.extensions.update(store=store, storage=storage, operations=operations)
    cache = {"time": 0, "data": None}
    cache_lock = threading.Lock()
    attempts = {}
    attempts_lock = threading.Lock()

    def authenticated():
        return (
            bool(store.data["password_hash"])
            and session.get("auth_version") == store.data["auth_version"]
        )

    def body():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValueError("Send a JSON object with this request.")
        return data

    def invalidate():
        cache["time"] = 0

    def rate_limit():
        with attempts_lock:
            current = time.monotonic()
            address = request.remote_addr or "local"
            attempts[address] = [
                stamp for stamp in attempts.get(address, []) if current - stamp < 300
            ]
            if len(attempts[address]) >= 8:
                return jsonify(
                    error="Too many sign-in attempts. Wait five minutes and try again."
                ), 429
            if len(attempts) > 1024:
                for key in list(attempts):
                    if not attempts[key] or current - attempts[key][-1] >= 300:
                        del attempts[key]
                if len(attempts) > 1024:
                    return jsonify(error="Sign-in is busy. Try again shortly."), 429
            attempts[address].append(current)
        return None

    @app.before_request
    def protect_api():
        if not request.path.startswith("/api/"):
            return None
        public = {"/api/health", "/api/session", "/api/auth/setup", "/api/auth/login"}
        if request.path not in public and not authenticated():
            return jsonify(error="Sign in to manage this stack."), 401
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            if request.headers.get("Origin") not in (
                None,
                request.host_url.rstrip("/"),
            ):
                return jsonify(
                    error="This request came from another site. Reload the panel and try again."
                ), 403
            expected = session.get("csrf", "")
            if not expected or not hmac.compare_digest(
                request.headers.get("X-CSRF-Token", "").encode(), expected.encode()
            ):
                return jsonify(
                    error="Your session changed. Reload the panel and try again."
                ), 403

    @app.after_request
    def security_headers(response):
        response.headers.update(
            {
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Referrer-Policy": "no-referrer",
                "Cache-Control": "no-store",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            }
        )
        return response

    @app.errorhandler(ValueError)
    def invalid_input(error):
        return jsonify(error=str(error)), 400

    @app.errorhandler(ServiceError)
    def service_error(error):
        return jsonify(error=str(error)), 422

    @app.errorhandler(Exception)
    def unexpected(error):
        if isinstance(error, HTTPException):
            return jsonify(error=error.description), error.code
        # Do not log upstream bodies, keys, credentials, or request payloads.
        app.logger.error("Panel request failed: %s", type(error).__name__)
        return jsonify(
            error="The request could not finish. Check the panel logs and try again."
        ), 500

    @app.get("/api/health")
    def health():
        return jsonify(status="ok")

    @app.get("/api/session")
    def get_session():
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
        return jsonify(
            authenticated=authenticated(),
            needs_setup=not bool(store.data["password_hash"]),
            csrf=session["csrf"],
        )

    @app.post("/api/auth/setup")
    def claim():
        limited = rate_limit()
        if limited:
            return limited
        data = body()
        password, code = data.get("password"), data.get("code", "")
        if not isinstance(password, str) or not 12 <= len(password) <= 128:
            raise ValueError(
                "Choose an administrator password between 12 and 128 characters."
            )
        if not isinstance(code, str):
            raise ValueError(
                "Enter the setup code from config/portal/setup-code on your server."
            )
        with store.lock:
            if store.data["password_hash"]:
                return jsonify(
                    error="This panel has already been set up. Sign in instead."
                ), 409
            if not hmac.compare_digest(
                hashlib.sha256(code.strip().encode()).hexdigest(),
                store.data["claim_hash"],
            ):
                return jsonify(
                    error="The setup code does not match. Read config/portal/setup-code on your server."
                ), 403
            store.data.update(
                password_hash=generate_password_hash(password), claim_hash=None
            )
            store.save()
            (store.directory / "setup-code").unlink(missing_ok=True)
        session.clear()
        session.update(
            auth_version=store.data["auth_version"], csrf=secrets.token_urlsafe(32)
        )
        session.permanent = True
        store.event("Administrator account created", "success")
        return jsonify(csrf=session["csrf"])

    @app.post("/api/auth/login")
    def login():
        limited = rate_limit()
        if limited:
            return limited
        password = body().get("password")
        if not isinstance(password, str) or len(password) > 128:
            raise ValueError("Enter your administrator password.")
        if not store.data["password_hash"] or not check_password_hash(
            store.data["password_hash"], password
        ):
            return jsonify(error="The password does not match."), 403
        session.clear()
        session.update(
            auth_version=store.data["auth_version"], csrf=secrets.token_urlsafe(32)
        )
        session.permanent = True
        with attempts_lock:
            attempts.pop(request.remote_addr or "local", None)
        return jsonify(csrf=session["csrf"])

    @app.post("/api/auth/logout")
    def logout():
        session.clear()
        return jsonify(ok=True)

    @app.post("/api/auth/password")
    def password():
        data = body()
        current, new = data.get("current"), data.get("password")
        if (
            not isinstance(current, str)
            or not isinstance(new, str)
            or not 12 <= len(new) <= 128
            or len(current) > 128
        ):
            raise ValueError(
                "Enter your current password and a new password of 12–128 characters."
            )
        with store.lock:
            if not check_password_hash(store.data["password_hash"], current):
                return jsonify(error="The current password does not match."), 403
            store.data["password_hash"] = generate_password_hash(new)
            store.data["auth_version"] += 1
            store.save()
            session["auth_version"] = store.data["auth_version"]
            session["csrf"] = secrets.token_urlsafe(32)
        store.event("Administrator password changed")
        return jsonify(csrf=session["csrf"])

    def public_connections():
        values = []
        for service, metadata in SERVICES.items():
            saved = store.data["services"].get(service, {})
            available = (
                service in ("radarr", "sonarr", "prowlarr", "seerr")
                and (
                    Path(app.config["KEY_DIR"])
                    / service
                    / ("settings.json" if service == "seerr" else "config.xml")
                ).is_file()
            )
            values.append(
                {
                    "id": service,
                    **metadata,
                    "url": saved.get("url", default_url(service)),
                    "public_url": saved.get("public_url", ""),
                    "configured": bool(saved),
                    "key_source": saved.get("key_source", "manual"),
                    "local_available": bool(available),
                    "has_key": bool(saved.get("api_key"))
                    or saved.get("key_source") == "local",
                    "username": saved.get("username", ""),
                    "has_password": bool(saved.get("password")),
                }
            )
        return values

    @app.get("/api/connections")
    def connections():
        return jsonify(services=public_connections())

    def connection_data(service, data):
        if service not in SERVICES:
            raise ValueError("Unknown service.")
        previous = store.data["services"].get(service, {})
        value = {"url": validate_url(data.get("url", default_url(service)))}
        public = data.get("public_url", "")
        value["public_url"] = validate_url(public) if public else ""
        if service == "qbittorrent":
            for name in ("username", "password"):
                candidate = data.get(name) or previous.get(name, "")
                if (
                    not isinstance(candidate, str)
                    or not candidate
                    or len(candidate) > 1024
                    or any(ord(c) < 32 for c in candidate)
                ):
                    raise ValueError("Enter a qBittorrent username and password.")
                value[name] = candidate
        else:
            source = data.get("key_source", "manual")
            if source not in ("manual", "local"):
                raise ValueError(
                    "Choose a manual API key or the local installation key."
                )
            value["key_source"] = source
            if source == "local":
                if value["url"] != default_url(service):
                    raise ValueError(
                        "Local keys can only be used with the installed app’s default internal address."
                    )
                value["api_key"] = local_key(service, app.config["KEY_DIR"])
            else:
                key = data.get("api_key") or previous.get("api_key", "")
                if (
                    not isinstance(key, str)
                    or not key
                    or len(key) > 1024
                    or any(not 33 <= ord(c) <= 126 for c in key)
                ):
                    raise ValueError("Enter the API key from the app’s settings.")
                value["api_key"] = key
        return value

    @app.post("/api/connections/<service>/test")
    def test_connection(service):
        config = connection_data(service, body())
        version = Client(service, config).test()
        return jsonify(
            ok=True,
            version=version,
            message="Connection verified. Save to use it in the panel.",
        )

    @app.post("/api/connections/<service>")
    def save_connection(service):
        with store.lock:
            config = connection_data(service, body())
            version = Client(service, config).test()
            if config.get("key_source") == "local":
                config.pop("api_key", None)
            store.data["services"][service] = config
            store.event(SERVICES[service]["name"] + " connected", "success")
            invalidate()
        return jsonify(ok=True, version=version)

    @app.delete("/api/connections/<service>")
    def disconnect(service):
        if service not in SERVICES:
            raise ValueError("Unknown service.")
        with store.lock:
            store.data["services"].pop(service, None)
            store.event(SERVICES[service]["name"] + " disconnected from the panel")
            invalidate()
        return jsonify(ok=True)

    @app.post("/api/connections/discover")
    def discover():
        results = []
        for service in ("radarr", "sonarr", "prowlarr", "seerr"):
            if service in store.data["services"]:
                results.append(
                    {"id": service, "ok": True, "message": "Existing connection kept"}
                )
                continue
            try:
                config = connection_data(service, {"key_source": "local"})
                Client(service, config).test()
                config.pop("api_key", None)
                with store.lock:
                    store.data["services"][service] = config
                    store.event(
                        SERVICES[service]["name"] + " connected using its local key",
                        "success",
                    )
                results.append(
                    {
                        "id": service,
                        "ok": True,
                        "message": "Connected using the local API key",
                    }
                )
            except (ServiceError, ValueError) as error:
                results.append({"id": service, "ok": False, "message": str(error)})
        invalidate()
        return jsonify(results=results)

    @app.get("/api/overview")
    def overview():
        with cache_lock:
            if cache["data"] is None or time.monotonic() - cache["time"] > 15:
                cache["data"] = {
                    "services": snapshots(store, app.config["KEY_DIR"]),
                    "checked_at": now(),
                }
                cache["time"] = time.monotonic()
            result = dict(cache["data"])
        result.update(
            connections=public_connections(),
            storage=storage.summary(dict(store.data["locations"])),
            events=store.data["events"],
            downloads_enabled=os.environ.get("DOWNLOADS_ENABLED") == "true",
        )
        return jsonify(result)

    @app.get("/api/storage")
    def get_storage():
        return jsonify(storage.summary(dict(store.data["locations"])))

    @app.get("/api/storage/browse")
    def browse():
        return jsonify(storage.browse(request.args.get("path", "/data")))

    @app.post("/api/storage/locations")
    def locations():
        data = body()
        values = {key: data.get(key) for key in ("movies", "tv")}
        for value in values.values():
            path = storage.path(value)
            if path == storage.root:
                raise ValueError(
                    "Choose a subfolder, rather than the whole data mount."
                )
        paths = [storage.path(value) for value in values.values()]
        if paths[0].is_relative_to(paths[1]) or paths[1].is_relative_to(paths[0]):
            raise ValueError(
                "Movies and TV need separate folders that do not contain each other."
            )
        for path in paths:
            torrents = storage.path("/data/torrents")
            if path.is_relative_to(torrents) or torrents.is_relative_to(path):
                raise ValueError(
                    "Keep library folders separate from download folders under /data/torrents."
                )
        with store.lock:
            store.data["locations"] = {
                key: "/data/" + str(storage.path(value).relative_to(storage.root))
                for key, value in values.items()
            }
            store.event(
                "Library location preferences saved; review setup to apply them"
            )
        return jsonify(
            ok=True,
            message="Locations saved in the panel. Review setup changes to add them in the apps.",
        )

    @app.post("/api/storage/check")
    def check_storage():
        return jsonify(results=storage.check_import(dict(store.data["locations"])))

    @app.get("/api/setup/profiles")
    def profiles():
        return jsonify(operations.profiles())

    @app.post("/api/setup/preview")
    def preview():
        data = body()
        options = {}
        for key in ("folders", "libraries", "downloads", "indexers", "requests"):
            if not isinstance(data.get(key, False), bool):
                raise ValueError("Setup choices must be true or false.")
            options[key] = data.get(key, False)
        for key in ("radarr_profile", "sonarr_profile"):
            value = data.get(key)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("Choose a valid quality profile.")
            options[key] = value
        return jsonify(operations.preview(options))

    @app.post("/api/setup/apply")
    def apply():
        token = body().get("token")
        if not isinstance(token, str) or len(token) > 100:
            raise ValueError("Review the changes before applying them.")
        try:
            return jsonify(operations.apply(token))
        finally:
            invalidate()

    @app.get("/")
    @app.get("/index.html")
    def index():
        return send_from_directory(ROOT / "portal", "index.html")

    @app.get("/guide.html")
    def old_guide():
        return send_from_directory(ROOT / "portal", "guide.html")

    @app.get("/<path:name>")
    def assets(name):
        allowed = {
            "app.js",
            "format.mjs",
            "links.js",
            "style.css",
            "guide.css",
            "favicon.svg",
            "fonts/plex-regular.woff2",
            "fonts/plex-medium.woff2",
            "fonts/LICENSE.txt",
        }
        if name not in allowed:
            return jsonify(error="Page not found."), 404
        return send_from_directory(ROOT / "portal", name)

    return app
