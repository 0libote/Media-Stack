from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from control.app import create_app
from control.__main__ import reset_admin
from control.integrations import Client, ServiceError, validate_url
from fake_services import FakeServices, KEY, PASSWORD


class PanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.upstream = FakeServices()

    @classmethod
    def tearDownClass(cls):
        cls.upstream.close()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.data = root / "data"
        self.data.mkdir()
        self.app = create_app(
            {
                "TESTING": True,
                "STATE_DIR": root / "state",
                "DATA_DIR": self.data,
                "KEY_DIR": root / "keys",
            }
        )
        self.client = self.app.test_client()
        self.store = self.app.extensions["store"]
        self.csrf = self.client.get("/api/session").json["csrf"]

    def post(self, path, data=None, client=None, csrf=None):
        return (client or self.client).post(
            path,
            json=data or {},
            headers={"X-CSRF-Token": self.csrf if csrf is None else csrf},
        )

    def sign_in(self):
        response = self.post(
            "/api/auth/setup", {"username": "owner", "password": "panel-test-password"}
        )
        self.assertEqual(response.status_code, 200, response.json)
        self.csrf = response.json["csrf"]

    def connect_all(self):
        with self.store.lock:
            self.store.data["services"] = {
                name: self.upstream.config(name)
                for name in (
                    "jellyfin",
                    "seerr",
                    "radarr",
                    "sonarr",
                    "prowlarr",
                    "qbittorrent",
                )
            }
            self.store.save()

    def test_private_state_and_first_time_account_setup(self):
        self.assertEqual(stat.S_IMODE(self.store.path.stat().st_mode), 0o600)
        self.assertFalse((self.store.directory / "setup-code").exists())
        bad = self.post(
            "/api/auth/setup", {"username": "", "password": "panel-test-password"}
        )
        self.assertEqual(bad.status_code, 400)
        self.sign_in()
        self.assertFalse((self.store.directory / "setup-code").exists())
        self.assertNotIn("claim_hash", self.store.data)
        self.assertEqual(self.store.data["username"], "owner")
        self.assertNotIn("panel-test-password", self.store.path.read_text())
        self.assertEqual(
            self.post(
                "/api/auth/setup",
                {"username": "replacement", "password": "another-test-password"},
            ).status_code,
            409,
        )

    def test_setup_rejects_invalid_usernames_and_empty_passwords(self):
        for data in (
            {"password": "panel-test-password"},
            {"username": "a" * 65, "password": "panel-test-password"},
            {"username": "bad\nname", "password": "panel-test-password"},
            {"username": "owner", "password": ""},
            {"username": "owner", "password": None},
            {"username": "owner", "password": "a" * 129},
        ):
            self.assertEqual(self.post("/api/auth/setup", data).status_code, 400)
        self.assertIsNone(self.store.data["password_hash"])

    def test_short_passwords_work_for_setup_login_and_password_changes(self):
        response = self.post("/api/auth/setup", {"username": "owner", "password": "x"})
        self.assertEqual(response.status_code, 200)
        self.csrf = response.json["csrf"]
        self.post("/api/auth/logout")
        self.csrf = self.client.get("/api/session").json["csrf"]
        response = self.post("/api/auth/login", {"username": "owner", "password": "x"})
        self.assertEqual(response.status_code, 200)
        self.csrf = response.json["csrf"]
        self.assertEqual(
            self.post(
                "/api/auth/password", {"current": "x", "password": ""}
            ).status_code,
            400,
        )
        response = self.post("/api/auth/password", {"current": "x", "password": "y"})
        self.assertEqual(response.status_code, 200)
        self.csrf = response.json["csrf"]
        self.post("/api/auth/logout")
        self.csrf = self.client.get("/api/session").json["csrf"]
        self.assertEqual(
            self.post(
                "/api/auth/login", {"username": "owner", "password": "y"}
            ).status_code,
            200,
        )

    def test_setup_still_requires_csrf_and_same_origin(self):
        data = {"username": "owner", "password": "panel-test-password"}
        self.assertEqual(
            self.client.post("/api/auth/setup", json=data).status_code, 403
        )
        response = self.client.post(
            "/api/auth/setup",
            json=data,
            headers={
                "X-CSRF-Token": self.csrf,
                "Origin": "https://attacker.invalid",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertIsNone(self.store.data["password_hash"])

    def test_login_checks_both_username_and_password(self):
        self.sign_in()
        self.post("/api/auth/logout")
        self.csrf = self.client.get("/api/session").json["csrf"]
        for name, password in (
            ("someone-else", "panel-test-password"),
            ("owner", "incorrect-password"),
        ):
            response = self.post(
                "/api/auth/login", {"username": name, "password": password}
            )
            self.assertEqual(response.status_code, 403)
            self.assertFalse(self.client.get("/api/session").json["authenticated"])
        response = self.post(
            "/api/auth/login", {"username": "owner", "password": "panel-test-password"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.client.get("/api/session").json["authenticated"])

    def test_legacy_account_keeps_password_and_connections_with_admin_username(self):
        self.sign_in()
        self.connect_all()
        legacy = dict(self.store.data)
        legacy.pop("username")
        legacy["claim_hash"] = None
        self.store.path.write_text(json.dumps(legacy))
        (self.store.directory / "setup-code").write_text("obsolete-code")
        restarted = create_app(
            {"TESTING": True, "STATE_DIR": self.store.directory, "DATA_DIR": self.data}
        )
        restored = restarted.extensions["store"]
        self.assertEqual(restored.data["username"], "admin")
        for key in ("password_hash", "secret", "auth_version", "services", "locations"):
            self.assertEqual(restored.data[key], legacy[key])
        self.assertNotIn("claim_hash", restored.data)
        self.assertFalse((self.store.directory / "setup-code").exists())
        client = restarted.test_client()
        token = client.get("/api/session").json["csrf"]
        response = self.post(
            "/api/auth/login",
            {"username": "admin", "password": "panel-test-password"},
            client=client,
            csrf=token,
        )
        self.assertEqual(response.status_code, 200)

    def test_authentication_required_for_all_management_endpoints(self):
        for path in (
            "/api/overview",
            "/api/connections",
            "/api/storage",
            "/api/storage/browse",
            "/api/setup/profiles",
        ):
            self.assertEqual(self.client.get(path).status_code, 401, path)
        for path in (
            "/api/connections/radarr",
            "/api/storage/locations",
            "/api/setup/preview",
            "/api/setup/apply",
        ):
            self.assertEqual(self.post(path).status_code, 401, path)
        self.assertEqual(self.client.get("/api/health").json, {"status": "ok"})

    def test_csrf_and_cross_origin_requests_rejected(self):
        self.sign_in()
        self.assertEqual(
            self.client.post("/api/connections/discover", json={}).status_code, 403
        )
        response = self.client.post(
            "/api/connections/discover",
            json={},
            headers={"X-CSRF-Token": self.csrf, "Origin": "https://attacker.invalid"},
        )
        self.assertEqual(response.status_code, 403)

    def test_password_change_revokes_other_sessions(self):
        self.sign_in()
        other = self.app.test_client()
        token = other.get("/api/session").json["csrf"]
        response = self.post(
            "/api/auth/login",
            {"username": "owner", "password": "panel-test-password"},
            client=other,
            csrf=token,
        )
        self.assertEqual(response.status_code, 200)
        response = self.post(
            "/api/auth/password",
            {"current": "panel-test-password", "password": "changed-test-password"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(other.get("/api/connections").status_code, 401)
        self.assertEqual(self.client.get("/api/connections").status_code, 200)

    def test_login_rate_limit_and_logout(self):
        self.sign_in()
        response = self.post("/api/auth/logout")
        self.assertEqual(response.status_code, 200)
        self.csrf = self.client.get("/api/session").json["csrf"]
        for _ in range(9):
            response = self.post(
                "/api/auth/login",
                {"username": "owner", "password": "wrong-test-password"},
            )
        self.assertEqual(response.status_code, 429)

    def test_test_connection_does_not_save_or_return_key(self):
        self.sign_in()
        response = self.post(
            "/api/connections/radarr/test", self.upstream.config("radarr")
        )
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(self.store.data["services"], {})
        self.assertNotIn(KEY, response.get_data(as_text=True))
        saved = self.post("/api/connections/radarr", self.upstream.config("radarr"))
        self.assertEqual(saved.status_code, 200)
        self.assertNotIn(
            KEY, self.client.get("/api/connections").get_data(as_text=True)
        )
        edited = dict(self.upstream.config("radarr"), api_key="")
        self.assertEqual(self.post("/api/connections/radarr", edited).status_code, 200)
        self.assertEqual(self.store.data["services"]["radarr"]["api_key"], KEY)

    def test_failed_save_preserves_previous_connection(self):
        self.sign_in()
        self.connect_all()
        previous = json.dumps(self.store.data["services"])
        response = self.post(
            "/api/connections/radarr",
            dict(self.upstream.config("radarr"), api_key="wrong-key"),
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(json.dumps(self.store.data["services"]), previous)
        self.assertNotIn(KEY, response.get_data(as_text=True))

    def test_disconnect_changes_only_panel(self):
        self.sign_in()
        self.connect_all()
        before = len(self.upstream.writes)
        response = self.client.delete(
            "/api/connections/radarr", headers={"X-CSRF-Token": self.csrf}
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("radarr", self.store.data["services"])
        self.assertEqual(len(self.upstream.writes), before)

    def test_snapshot_uses_real_metrics_and_redacts_secrets(self):
        self.sign_in()
        self.connect_all()
        response = self.client.get("/api/overview")
        self.assertEqual(response.status_code, 200, response.json)
        data = {item["id"]: item for item in response.json["services"]}
        self.assertEqual(data["jellyfin"]["metrics"]["movies"], 123)
        self.assertEqual(data["jellyfin"]["metrics"]["streams"], 1)
        self.assertEqual(data["qbittorrent"]["metrics"]["download_speed"], 4096)
        self.assertEqual(data["seerr"]["metrics"]["pending"], 2)
        for secret in (KEY, PASSWORD):
            self.assertNotIn(secret, response.get_data(as_text=True))

    def test_qbittorrent_no_content_login_keeps_authenticated_session(self):
        with patch.object(self.upstream, "qbit_login_status", 204):
            client = Client("qbittorrent", self.upstream.config("qbittorrent"))
            self.assertTrue(client.test())
            client.config["password"] = "wrong-password"
            with self.assertRaises(ServiceError):
                client.test()

    def test_optional_service_health_connections_need_no_credentials(self):
        self.sign_in()
        for service in ("gluetun", "dispatcharr"):
            result = self.post(
                "/api/connections/" + service,
                {
                    "url": self.upstream.base + "/" + service,
                },
            )
            self.assertEqual(result.status_code, 200, result.json)
            self.assertNotIn("api_key", self.store.data["services"][service])

    def test_invalid_dispatcharr_response_is_a_service_error(self):
        with patch.object(self.upstream, "invalid_metrics", True):
            with self.assertRaises(ServiceError):
                Client("dispatcharr", self.upstream.config("dispatcharr")).test()

    def test_unlinked_metrics_are_absent_instead_of_zero(self):
        self.sign_in()
        result = self.client.get("/api/overview").json
        self.assertTrue(
            all(
                item["status"] == "unlinked" and item["metrics"] == {}
                for item in result["services"]
            )
        )

    def test_storage_confinement_symlinks_and_overlapping_locations(self):
        self.sign_in()
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        (self.data / "escape").symlink_to(outside, target_is_directory=True)
        for value in (
            "/etc",
            "/data/../outside",
            "/data/escape",
            "/database",
            "/data/\u0000bad",
        ):
            response = self.post(
                "/api/storage/locations", {"movies": value, "tv": "/data/media/tv"}
            )
            self.assertEqual(response.status_code, 400, value)
        for movies, tv in (
            ("/data/media", "/data/media/tv"),
            ("/data/media", "/data/media"),
            ("/data/torrents/movies", "/data/media/tv"),
        ):
            self.assertEqual(
                self.post(
                    "/api/storage/locations", {"movies": movies, "tv": tv}
                ).status_code,
                400,
            )
        self.assertEqual(
            self.client.get("/api/storage/browse?path=/data/escape").status_code, 400
        )
        self.assertFalse(self.client.get("/api/storage/browse").json["folders"])

    def test_saving_locations_does_not_change_apps_or_files(self):
        self.sign_in()
        before = len(self.upstream.writes)
        result = self.post(
            "/api/storage/locations",
            {"movies": "/data/library/movies", "tv": "/data/library/tv"},
        )
        self.assertEqual(result.status_code, 200)
        self.assertFalse((self.data / "library").exists())
        self.assertEqual(len(self.upstream.writes), before)

    def test_hardlink_check_cleans_up_and_keeps_existing_files(self):
        self.sign_in()
        for directory in ("media/movies", "media/tv", "torrents/incomplete"):
            (self.data / directory).mkdir(parents=True)
        original = self.data / "media/movies/existing.txt"
        original.write_text("keep this")
        result = self.post("/api/storage/check").json
        self.assertTrue(all(item["hardlinks"] for item in result["results"]))
        self.assertFalse(list(self.data.rglob(".media-stack-check-*")))
        self.assertEqual(original.read_text(), "keep this")

    def test_missing_folders_check_is_actionable(self):
        self.sign_in()
        result = self.post("/api/storage/check").json
        self.assertTrue(
            all(
                not item["hardlinks"] and "Create" in item["message"]
                for item in result["results"]
            )
        )

    def test_security_headers_and_static_files(self):
        response = self.client.get("/")
        self.addCleanup(response.close)
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        for path in (
            "/app.js",
            "/format.mjs",
            "/style.css",
            "/guide.html",
            "/favicon.svg",
            "/fonts/plex-regular.woff2",
        ):
            with self.client.get(path) as asset:
                self.assertEqual(asset.status_code, 200, path)
        for path in (
            "/config/portal/settings.json",
            "/.env",
            "/control/app.py",
            "/../LICENSE",
        ):
            self.assertEqual(self.client.get(path).status_code, 404, path)

    def test_local_key_can_only_be_sent_to_default_installation_url(self):
        self.sign_in()
        result = self.post(
            "/api/connections/radarr",
            {"url": "https://example.invalid", "key_source": "local"},
        )
        self.assertEqual(result.status_code, 400)
        self.assertIn("default internal address", result.json["error"])

    def test_local_discovery_retains_existing_manual_connections(self):
        self.sign_in()
        self.connect_all()
        before = json.dumps(self.store.data["services"], sort_keys=True)
        result = self.post("/api/connections/discover")
        self.assertEqual(result.status_code, 200)
        self.assertTrue(all(item["ok"] for item in result.json["results"]))
        self.assertEqual(
            json.dumps(self.store.data["services"], sort_keys=True), before
        )

    def test_local_discovery_reads_keys_without_returning_or_storing_them(self):
        self.sign_in()
        keys = Path(self.app.config["KEY_DIR"])
        env = {}
        for name in ("radarr", "sonarr", "prowlarr", "seerr"):
            folder = keys / name
            folder.mkdir(parents=True)
            if name == "seerr":
                (folder / "settings.json").write_text(
                    json.dumps({"main": {"apiKey": KEY}})
                )
            else:
                (folder / "config.xml").write_text(
                    f"<Config><ApiKey>{KEY}</ApiKey></Config>"
                )
            env[name.upper() + "_URL"] = self.upstream.config(name)["url"]
        with patch.dict(os.environ, env):
            response = self.post("/api/connections/discover")
            self.assertTrue(
                all(item["ok"] for item in response.json["results"]), response.json
            )
            self.assertNotIn(KEY, response.get_data(as_text=True))
            for item in self.store.data["services"].values():
                self.assertEqual(item["key_source"], "local")
                self.assertNotIn("api_key", item)
            response = self.client.get("/api/overview")
            self.assertEqual(response.status_code, 200)
            self.assertNotIn(KEY, response.get_data(as_text=True))

    def test_invalid_key_characters_are_rejected_without_echoing_them(self):
        self.sign_in()
        for key in ("private-\n-key", "private-💿-key"):
            response = self.post(
                "/api/connections/radarr",
                dict(self.upstream.config("radarr"), api_key=key),
            )
            self.assertEqual(response.status_code, 400)
            self.assertNotIn("private-", response.get_data(as_text=True))

    def test_operator_recovery_keeps_connections_and_revokes_sessions(self):
        self.sign_in()
        self.connect_all()
        previous = json.dumps(self.store.data["services"], sort_keys=True)
        with redirect_stdout(io.StringIO()):
            reset_admin(self.store.directory)
        restarted = create_app(
            {"TESTING": True, "STATE_DIR": self.store.directory, "DATA_DIR": self.data}
        )
        restored = restarted.extensions["store"]
        self.assertEqual(
            json.dumps(restored.data["services"], sort_keys=True), previous
        )
        self.assertIsNone(restored.data["password_hash"])
        self.assertNotEqual(restored.data["secret"], self.store.data["secret"])
        self.assertIsNone(restored.data["username"])
        self.assertFalse((restored.directory / "setup-code").exists())
        client = restarted.test_client()
        token = client.get("/api/session").json["csrf"]
        response = self.post(
            "/api/auth/setup",
            {"username": "new-owner", "password": "replacement-password"},
            client=client,
            csrf=token,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(restored.data["username"], "new-owner")

    def test_trusted_proxy_supports_https_origin_and_secure_cookies(self):
        with patch.dict(os.environ, {"PANEL_TRUST_PROXY": "1"}):
            proxy_app = create_app(
                {
                    "TESTING": True,
                    "STATE_DIR": self.store.directory,
                    "DATA_DIR": self.data,
                    "SESSION_COOKIE_SECURE": True,
                }
            )
        client = proxy_app.test_client()
        response = client.get("/api/session", headers={"X-Forwarded-Proto": "https"})
        self.assertIn("Secure", response.headers["Set-Cookie"])
        self.assertIn("HttpOnly", response.headers["Set-Cookie"])
        token = response.json["csrf"]
        response = client.post(
            "/api/auth/setup",
            json={"username": "owner", "password": "panel-test-password"},
            headers={
                "X-CSRF-Token": token,
                "Origin": "https://localhost",
                "X-Forwarded-Proto": "https",
            },
        )
        self.assertEqual(response.status_code, 200, response.json)


class ClientTests(unittest.TestCase):
    def test_url_validation(self):
        for value in (
            "file:///etc/passwd",
            "http://user:password@localhost",
            "http://169.254.169.254",
            "http://host/?key=value",
            "http://host/#hash",
            "http://host:99999",
            "http://0.0.0.0",
            "http://host/with space",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_url(value)
        self.assertEqual(
            validate_url("https://server.local:7878/radarr/"),
            "https://server.local:7878/radarr",
        )

    def test_upstream_error_body_is_never_exposed(self):
        upstream = FakeServices()
        self.addCleanup(upstream.close)
        upstream.failures[("radarr", "/api/v3/system/status")] = 401
        with self.assertRaises(ServiceError) as caught:
            Client("radarr", upstream.config("radarr")).test()
        self.assertNotIn(KEY, str(caught.exception))
        self.assertIn("Access denied", str(caught.exception))

    def test_failed_secondary_metrics_do_not_mark_app_offline(self):
        upstream = FakeServices()
        self.addCleanup(upstream.close)
        upstream.failures[("jellyfin", "/Items/Counts")] = 503
        data = Client("jellyfin", upstream.config("jellyfin")).snapshot()
        self.assertEqual(data["status"], "online")
        self.assertEqual(data["metrics"], {})
        self.assertIn("metrics_error", data)

    def test_unknown_metrics_are_not_coerced_to_zero(self):
        upstream = FakeServices()
        self.addCleanup(upstream.close)
        upstream.invalid_metrics = True
        data = Client("jellyfin", upstream.config("jellyfin")).snapshot()
        self.assertIsNone(data["metrics"]["movies"])
        self.assertIsNone(data["metrics"]["series"])


if __name__ == "__main__":
    unittest.main()
