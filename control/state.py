"""Private local settings; writes are atomic and never include media files."""

import hashlib
import json
import os
from pathlib import Path
import secrets
import tempfile
import threading
from datetime import datetime, timezone

SERVICES = {
    "jellyfin": {"name": "Jellyfin", "role": "Watch your library", "port": 8096},
    "seerr": {"name": "Seerr", "role": "Discover and request", "port": 5055},
    "radarr": {"name": "Radarr", "role": "Movie management", "port": 7878},
    "sonarr": {"name": "Sonarr", "role": "TV management", "port": 8989},
    "prowlarr": {"name": "Prowlarr", "role": "Indexer management", "port": 9696},
    "qbittorrent": {"name": "qBittorrent", "role": "Download client", "port": 8080},
    "gluetun": {
        "name": "Gluetun",
        "role": "Optional download VPN",
        "port": 9999,
        "auth": "none",
        "browser": False,
    },
    "dispatcharr": {
        "name": "Dispatcharr",
        "role": "Live TV, channels, guide and recordings",
        "port": 9191,
        "auth": "none",
    },
}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = self.directory / "settings.json"
        self.lock = threading.RLock()
        if self.path.exists():
            self.data = json.loads(self.path.read_text())
        else:
            self.data = {
                "secret": secrets.token_hex(32),
                "username": None,
                "password_hash": None,
                "auth_version": 1,
                "services": {},
                "locations": {"movies": "/data/media/movies", "tv": "/data/media/tv"},
                "events": [],
            }
            self.save()
        if "username" not in self.data or "claim_hash" in self.data:
            self.data.setdefault(
                "username", "admin" if self.data["password_hash"] else None
            )
            self.data.pop("claim_hash", None)
            self.save()
        (self.directory / "setup-code").unlink(missing_ok=True)

    def save(self):
        with self.lock:
            descriptor, temporary = tempfile.mkstemp(
                dir=self.directory, prefix=".settings-"
            )
            try:
                with os.fdopen(descriptor, "w") as handle:
                    json.dump(self.data, handle, indent=2)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)

    def event(self, message, kind="info"):
        with self.lock:
            self.data["events"] = [
                {"time": now(), "message": message, "kind": kind}
            ] + self.data["events"][:49]
            self.save()

    def fingerprint(self):
        with self.lock:
            return hashlib.sha256(
                json.dumps(
                    {key: self.data[key] for key in ("services", "locations")},
                    sort_keys=True,
                ).encode()
            ).hexdigest()
