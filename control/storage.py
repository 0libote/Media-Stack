"""Only operate inside the data mount. Never move or delete a user's media."""

import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile


class Storage:
    def __init__(self, directory, host_path=""):
        self.root = Path(directory).resolve()
        self.host_path = host_path

    def path(self, value):
        if (
            not isinstance(value, str)
            or len(value) > 500
            or any(ord(c) < 32 for c in value)
        ):
            raise ValueError("Choose a folder inside /data.")
        virtual = PurePosixPath(value)
        if (
            not virtual.is_absolute()
            or virtual.parts[:2] != ("/", "data")
            or ".." in virtual.parts
            or "\\" in value
        ):
            raise ValueError(
                "Choose a folder inside /data; parent traversal is not allowed."
            )
        path = self.root.joinpath(*virtual.parts[2:]).resolve()
        if path != self.root and not path.is_relative_to(self.root):
            raise ValueError("That folder resolves outside the data mount.")
        return path

    def inspect(self, value):
        path = self.path(value)
        parent = path
        while not parent.exists() and parent != self.root:
            parent = parent.parent
        return {
            "path": value,
            "exists": path.is_dir(),
            "writable": parent.is_dir() and os.access(parent, os.W_OK | os.X_OK),
        }

    def summary(self, locations):
        result = {
            "mount": "/data",
            "host_path": self.host_path,
            "locations": {key: self.inspect(value) for key, value in locations.items()},
        }
        try:
            usage = shutil.disk_usage(self.root)
            result["disk"] = {
                "total": usage.total,
                "used": usage.used,
                "free": usage.free,
            }
        except OSError:
            result["error"] = (
                "The data mount is not available. Check DATA_DIR and the Compose volume."
            )
        return result

    def browse(self, value):
        path = self.path(value)
        if not path.is_dir():
            raise ValueError(
                "This folder does not exist yet. Enter the path to create it when applying locations."
            )
        children = []
        with os.scandir(path) as entries:
            for item in entries:
                if not item.name.startswith(".") and item.is_dir(follow_symlinks=False):
                    children.append(item.name)
                if len(children) > 200:
                    break
        return {
            "path": value,
            "folders": sorted(children[:200], key=str.casefold),
            "truncated": len(children) > 200,
        }

    def mkdir(self, value):
        path = self.path(value)
        path.mkdir(parents=True, exist_ok=True)
        return self.inspect(value)

    def check_import(self, locations):
        source = self.path("/data/torrents/incomplete")
        results = []
        for kind, value in locations.items():
            target = self.path(value)
            result = {"kind": kind, "path": value, "hardlinks": False}
            if not source.is_dir() or not target.is_dir():
                result["message"] = "Create the download and library folders first."
            else:
                temporary = destination = None
                try:
                    with tempfile.NamedTemporaryFile(
                        prefix=".media-stack-check-", dir=source, delete=False
                    ) as handle:
                        temporary = Path(handle.name)
                    destination = target / temporary.name
                    os.link(temporary, destination)
                    result.update(
                        hardlinks=True,
                        message="Write access and hardlinks work between these folders.",
                    )
                except OSError:
                    result["message"] = (
                        "Hardlink check failed. Check write access and whether the folders share a filesystem."
                    )
                finally:
                    if (
                        destination is not None
                        and destination.exists()
                        and temporary is not None
                        and os.path.samestat(destination.stat(), temporary.stat())
                    ):
                        destination.unlink()
                    if temporary is not None:
                        temporary.unlink(missing_ok=True)
            results.append(result)
        return results
