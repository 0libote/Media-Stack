"""Narrow upstream API clients. Credentials stay on the server."""

from concurrent.futures import ThreadPoolExecutor
import copy
import http.cookiejar
import ipaddress
import json
import os
from pathlib import Path
import socket
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from .state import SERVICES


class ServiceError(Exception):
    pass


def validate_url(value):
    if (
        not isinstance(value, str)
        or len(value) > 500
        or not value.isascii()
        or any(ord(c) < 33 for c in value)
    ):
        raise ValueError("Enter an HTTP or HTTPS service address without spaces.")
    try:
        url = urllib.parse.urlsplit(value)
        if (
            url.scheme not in ("http", "https")
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError()
        port = url.port
        if port is not None and not 1 <= port <= 65535:
            raise ValueError()
        try:
            address = ipaddress.ip_address(url.hostname)
        except ValueError:
            address = None
        if address and (
            address.is_link_local or address.is_multicast or address.is_unspecified
        ):
            raise ValueError()
    except ValueError:
        raise ValueError(
            "Use a full HTTP or HTTPS address, with no credentials, query, or fragment."
        ) from None
    return value.rstrip("/")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self, service, config, timeout=4):
        self.service = service
        self.config = config
        self.url = config["url"].rstrip("/")
        self.timeout = timeout
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            NoRedirect(),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
        )
        self.prefix = "/api/v1" if service == "prowlarr" else "/api/v3"

    def request(
        self, path, method="GET", payload=None, form=None, raw=False, with_status=False
    ):
        headers = {"Accept": "application/json", "User-Agent": "Media-Stack/1"}
        key = self.config.get("api_key", "")
        if key:
            if self.service == "jellyfin":
                headers["Authorization"] = "MediaBrowser Token=" + json.dumps(key)
            else:
                headers["X-Api-Key"] = key
        body = None
        if payload is not None:
            body = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        if form is not None:
            body = urllib.parse.urlencode(form).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            headers["Referer"] = self.url + "/"
            headers["Origin"] = urllib.parse.urlunsplit(
                (*urllib.parse.urlsplit(self.url)[:2], "", "", "")
            )
        req = urllib.request.Request(
            self.url + path, data=body, headers=headers, method=method
        )
        try:
            with self.opener.open(req, timeout=self.timeout) as response:
                data = response.read(8 * 1024 * 1024 + 1)
            if len(data) > 8 * 1024 * 1024:
                raise ServiceError(
                    "The app returned too much data. Open the app to inspect its library."
                )
            if raw:
                value = data.decode("utf-8")
                return (response.status, value) if with_status else value
            return json.loads(data) if data else None
        except urllib.error.HTTPError as error:
            error.close()
            if error.code in (401, 403):
                raise ServiceError(
                    "Access denied. Check the API key or login details."
                ) from None
            if error.code in (301, 302, 303, 307, 308):
                raise ServiceError(
                    "This address redirects. Use the app’s final address, including its base path."
                ) from None
            if error.code == 404:
                raise ServiceError(
                    "API endpoint not found. Check the address, base path, and supported app version."
                ) from None
            raise ServiceError(
                f"The app rejected the request (HTTP {error.code}). Check its settings and logs."
            ) from None
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError):
            raise ServiceError(
                "Cannot reach the app. Check its address, container, and network."
            ) from None
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ServiceError(
                "The address did not return an API response. Check the app address and base path."
            ) from None

    def api(self, path, **kwargs):
        return self.request(self.prefix + path, **kwargs)

    def login(self):
        if self.service == "qbittorrent":
            status, result = self.request(
                "/api/v2/auth/login",
                method="POST",
                form={
                    "username": self.config.get("username", ""),
                    "password": self.config.get("password", ""),
                },
                raw=True,
                with_status=True,
            )
            if status != 204 and result.strip() != "Ok.":
                raise ServiceError(
                    "qBittorrent rejected the login. Check the username and password."
                )

    def test(self):
        self.login()
        if self.service == "gluetun":
            self.request("/", raw=True)
            return "VPN healthy"
        if self.service == "dispatcharr":
            info = self.request("/api/core/version/")
            if not isinstance(info, dict) or not info.get("version"):
                raise ServiceError(
                    "Dispatcharr did not return a valid version response."
                )
            return str(info["version"])
        if self.service == "qbittorrent":
            return self.request("/api/v2/app/version", raw=True).strip()
        if self.service == "jellyfin":
            info = self.request("/System/Info")
        elif self.service == "seerr":
            self.request("/api/v1/settings/main")
            info = self.request("/api/v1/status")
        else:
            info = self.api("/system/status")
        if not isinstance(info, dict):
            raise ServiceError(
                "The app returned an unsupported status response. Check its API address and version."
            )
        return str(
            info.get("Version" if self.service == "jellyfin" else "version", "Unknown")
        )

    def snapshot(self):
        result = {
            "id": self.service,
            "status": "online",
            "message": "Connected",
            "metrics": {},
            "health": [],
        }
        try:
            result["version"] = self.test()
        except ServiceError as error:
            result.update(status="unavailable", message=str(error))
            return result
        # A failed secondary endpoint must not turn missing metrics into zeros.
        try:
            if self.service == "jellyfin":
                counts = self.request("/Items/Counts")
                sessions = self.request("/Sessions")
                result["metrics"] = {
                    "movies": counts.get("MovieCount"),
                    "series": counts.get("SeriesCount"),
                    "episodes": counts.get("EpisodeCount"),
                    "streams": sum(bool(s.get("NowPlayingItem")) for s in sessions),
                }
            elif self.service in ("radarr", "sonarr"):
                result["roots"] = [
                    {
                        "path": item["path"],
                        "accessible": item.get("accessible"),
                        "free": item.get("freeSpace"),
                    }
                    for item in self.api("/rootfolder")
                ]
                result["metrics"]["queue"] = self.api("/queue?page=1&pageSize=1").get(
                    "totalRecords"
                )
                result["health"] = [
                    {
                        "type": item.get("type", "warning"),
                        "message": item.get("message", "Check app health"),
                    }
                    for item in self.api("/health")
                ]
            elif self.service == "prowlarr":
                result["metrics"]["indexers"] = len(self.api("/indexer"))
                result["metrics"]["applications"] = len(self.api("/applications"))
                result["health"] = [
                    {
                        "type": item.get("type", "warning"),
                        "message": item.get("message", "Check app health"),
                    }
                    for item in self.api("/health")
                ]
            elif self.service == "seerr":
                info = self.request("/api/v1/request/count")
                result["metrics"] = {
                    "requests": info.get("total"),
                    "pending": info.get("pending"),
                }
            elif self.service == "qbittorrent":
                info = self.request("/api/v2/transfer/info")
                result["metrics"] = {
                    "download_speed": info.get("dl_info_speed"),
                    "upload_speed": info.get("up_info_speed"),
                    "connection": info.get("connection_status"),
                }
                torrents = self.request(
                    "/api/v2/torrents/info?filter=downloading&limit=8&sort=added_on&reverse=true"
                )
                result["downloads"] = [
                    {
                        "name": t.get("name", "Unnamed transfer"),
                        "progress": t.get("progress", 0),
                        "speed": t.get("dlspeed", 0),
                        "eta": t.get("eta"),
                        "state": t.get("state", "unknown"),
                    }
                    for t in torrents
                ]
        except (ServiceError, KeyError, TypeError, AttributeError) as error:
            result["metrics_error"] = (
                str(error)
                if isinstance(error, ServiceError)
                else "The app returned an unsupported response."
            )
        return result


def default_url(service):
    return os.environ.get(
        f"{service.upper()}_URL", f"http://{service}:{SERVICES[service]['port']}"
    )


def local_key(service, directory):
    try:
        if service in ("radarr", "sonarr", "prowlarr"):
            path = Path(directory) / service / "config.xml"
            if path.stat().st_size > 65536:
                raise ServiceError("Local configuration is too large to read safely.")
            key = ET.fromstring(path.read_text()).findtext("ApiKey")
        elif service == "seerr":
            path = Path(directory) / "seerr/settings.json"
            if path.stat().st_size > 1024 * 1024:
                raise ServiceError("Local configuration is too large to read safely.")
            key = json.loads(path.read_text()).get("main", {}).get("apiKey")
        else:
            key = None
    except (OSError, ValueError, ET.ParseError):
        raise ServiceError(
            "Local API key is not available yet. Finish the app’s first-time setup or enter its key manually."
        ) from None
    if (
        not isinstance(key, str)
        or not key
        or len(key) > 1024
        or any(not 33 <= ord(c) <= 126 for c in key)
    ):
        raise ServiceError(
            "No API key was found. Finish the app’s first-time setup first."
        )
    return key


def config_for(store, service, directory):
    with store.lock:
        config = copy.deepcopy(store.data["services"].get(service))
    if config and config.get("key_source") == "local":
        config["api_key"] = local_key(service, directory)
    return config


def snapshots(store, directory):
    def read(service):
        if service == "gluetun" and os.environ.get("VPN_ENABLED") == "false":
            return {
                "id": service,
                "status": "disabled",
                "message": "VPN switched off. Downloads use the normal connection when enabled.",
                "metrics": {},
            }
        try:
            config = config_for(store, service, directory)
            if not config:
                return {
                    "id": service,
                    "status": "unlinked",
                    "message": "Connect to see status and stats",
                    "metrics": {},
                }
            return Client(service, config).snapshot()
        except ServiceError as error:
            return {
                "id": service,
                "status": "unavailable",
                "message": str(error),
                "metrics": {},
            }

    with ThreadPoolExecutor(max_workers=len(SERVICES)) as pool:
        return list(pool.map(read, SERVICES))
