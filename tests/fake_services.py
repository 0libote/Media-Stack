"""Small local HTTP fixtures for integration tests; no real services or credentials."""

import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from urllib.parse import parse_qs, urlsplit

KEY = "synthetic-test-api-key"
PASSWORD = "synthetic-qbit-password"


class FakeServices:
    def __init__(self):
        self.roots = {"radarr": [], "sonarr": []}
        self.clients = {"radarr": [], "sonarr": []}
        self.applications = []
        self.libraries = []
        self.categories = {}
        self.requests = {"radarr": [], "sonarr": []}
        self.writes = []
        self.failures = {}
        self.delay = 0
        self.invalid_metrics = False
        fixtures = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.handle_request()

            def do_POST(self):
                self.handle_request()

            def handle_request(self):
                parsed = urlsplit(self.path)
                parts = parsed.path.strip("/").split("/", 1)
                if len(parts) != 2:
                    self.send_response(404)
                    self.end_headers()
                    return
                service, path = parts
                path = "/" + path
                length = int(self.headers.get("Content-Length", 0))
                data = self.rfile.read(length)
                if "application/json" in self.headers.get("Content-Type", ""):
                    payload = json.loads(data) if data else None
                else:
                    payload = {
                        key: values[0]
                        for key, values in parse_qs(data.decode()).items()
                    }
                is_login = path == "/api/v2/auth/login"
                if self.command == "POST" and not is_login:
                    fixtures.writes.append((service, path, payload))
                failure = fixtures.failures.get((service, path))
                if failure:
                    self.send_response(failure)
                    self.end_headers()
                    self.wfile.write(
                        ("upstream body with " + KEY + " and " + PASSWORD).encode()
                    )
                    return
                if is_login:
                    valid = (
                        payload.get("username") == "admin"
                        and payload.get("password") == PASSWORD
                    )
                    self.send_response(200)
                    if valid:
                        self.send_header("Set-Cookie", "SID=test-session; Path=/")
                    self.end_headers()
                    self.wfile.write(b"Ok." if valid else b"Fails.")
                    return
                if service == "qbittorrent":
                    if "SID=test-session" not in self.headers.get("Cookie", ""):
                        self.send_response(403)
                        self.end_headers()
                        return
                elif (
                    self.headers.get(
                        "X-Emby-Token" if service == "jellyfin" else "X-Api-Key"
                    )
                    != KEY
                ):
                    self.send_response(401)
                    self.end_headers()
                    return
                result, raw = fixtures.response(
                    service, path, self.command, payload, parse_qs(parsed.query)
                )
                if result is NotImplemented:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header(
                    "Content-Type", "text/plain" if raw else "application/json"
                )
                self.end_headers()
                self.wfile.write(
                    str(result).encode() if raw else json.dumps(result).encode()
                )

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def config(self, service):
        return (
            {
                "url": self.base + "/" + service,
                "public_url": "",
                "key_source": "manual",
                "api_key": KEY,
            }
            if service != "qbittorrent"
            else {
                "url": self.base + "/qbittorrent",
                "public_url": "",
                "username": "admin",
                "password": PASSWORD,
            }
        )

    def response(self, service, path, method, payload, query):
        if service in ("radarr", "sonarr", "prowlarr"):
            prefix = "/api/v1" if service == "prowlarr" else "/api/v3"
            if not path.startswith(prefix):
                return NotImplemented, False
            route = path[len(prefix) :]
            if route == "/system/status":
                return {"version": "4.0.0-test"}, False
            if route == "/health":
                return [], False
            if route == "/queue":
                return {"totalRecords": 2}, False
            if route == "/qualityprofile":
                return [{"id": 1, "name": "HD-1080p"}, {"id": 2, "name": "Any"}], False
            if route == "/rootfolder":
                if method == "POST":
                    self.roots[service].append(
                        {"id": len(self.roots[service]) + 1, **payload}
                    )
                return copy.deepcopy(self.roots[service]), False
            if route == "/downloadclient/schema":
                category = "movieCategory" if service == "radarr" else "tvCategory"
                return [
                    {
                        "implementation": "QBittorrent",
                        "configContract": "QBittorrentSettings",
                        "fields": [
                            {"name": name, "value": value}
                            for name, value in {
                                "host": "localhost",
                                "port": 8080,
                                "useSsl": False,
                                "urlBase": "",
                                "username": "",
                                "password": "",
                                category: "",
                                "priority": 0,
                            }.items()
                        ],
                    }
                ], False
            if route == "/downloadclient/test" or route == "/applications/test":
                return [], False
            if route == "/downloadclient":
                if method == "POST":
                    self.clients[service].append(copy.deepcopy(payload))
                return copy.deepcopy(self.clients[service]), False
            if route == "/applications/schema":
                return [
                    {
                        "implementation": name,
                        "configContract": name + "Settings",
                        "fields": [
                            {"name": key, "value": value}
                            for key, value in {
                                "prowlarrUrl": "",
                                "baseUrl": "",
                                "apiKey": "",
                                "syncCategories": [2000 if name == "Radarr" else 5000],
                            }.items()
                        ],
                    }
                    for name in ("Radarr", "Sonarr")
                ], False
            if route == "/applications":
                if method == "POST":
                    self.applications.append(copy.deepcopy(payload))
                return copy.deepcopy(self.applications), False
            if route == "/indexer":
                return [{"id": 1}, {"id": 2}], False
        elif service == "jellyfin":
            if path == "/System/Info":
                return {"Version": "10.11-test", "ServerName": "Test Jellyfin"}, False
            if path == "/Items/Counts":
                if self.invalid_metrics:
                    return {"MovieCount": None}, False
                return {
                    "MovieCount": 123,
                    "SeriesCount": 21,
                    "EpisodeCount": 456,
                }, False
            if path == "/Sessions":
                return [
                    {"NowPlayingItem": {"Name": "Synthetic movie"}},
                    {"Id": "inactive"},
                ], False
            if path == "/Library/VirtualFolders":
                if method == "POST":
                    self.libraries.append(
                        {
                            "Name": query["name"][0],
                            "Locations": [
                                item["Path"]
                                for item in payload["LibraryOptions"]["PathInfos"]
                            ],
                        }
                    )
                return copy.deepcopy(self.libraries), False
        elif service == "seerr":
            if path == "/api/v1/settings/main":
                return {"apiKey": KEY, "applicationTitle": "Seerr"}, False
            if path == "/api/v1/status":
                return {"version": "3.0-test"}, False
            if path == "/api/v1/request/count":
                return {"total": 7, "pending": 2}, False
            for target in ("radarr", "sonarr"):
                if path == f"/api/v1/settings/{target}":
                    if method == "POST":
                        self.requests[target].append(copy.deepcopy(payload))
                    return copy.deepcopy(self.requests[target]), False
                if path == f"/api/v1/settings/{target}/test":
                    return {"profiles": []}, False
        elif service == "qbittorrent":
            if path == "/api/v2/app/version":
                return "v5.0-test", True
            if path == "/api/v2/transfer/info":
                return {
                    "dl_info_speed": 4096,
                    "up_info_speed": 2048,
                    "connection_status": "connected",
                }, False
            if path == "/api/v2/torrents/info":
                return [
                    {
                        "name": "Synthetic transfer <script>alert(1)</script>",
                        "progress": 0.42,
                        "dlspeed": 4096,
                        "eta": 3600,
                        "state": "downloading",
                    }
                ], False
            if path == "/api/v2/torrents/categories":
                return copy.deepcopy(self.categories), False
            if path == "/api/v2/torrents/createCategory":
                self.categories[payload["category"]] = {
                    "name": payload["category"],
                    "savePath": payload["savePath"],
                }
                return "", True
        return NotImplemented, False
