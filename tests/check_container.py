"""Smoke-test the built panel with empty mounts and no external network."""

import argparse
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile

SMOKE = r"""
import http.cookiejar
import json
from pathlib import Path
import os
import time
import urllib.request

assert os.getuid() != 0
opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
)
base = "http://127.0.0.1:8088"
def call(path, body=None, csrf=""):
    req = urllib.request.Request(base + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", "X-CSRF-Token": csrf})
    with opener.open(req, timeout=10) as response:
        return json.load(response)
for attempt in range(40):
    try:
        assert call("/api/health")["status"] == "ok"
        break
    except OSError:
        time.sleep(.25)
else:
    raise SystemExit("The panel did not start within ten seconds")
session = call("/api/session")
assert session["needs_setup"] and not session["authenticated"]
code_file = Path("/state/setup-code")
assert code_file.stat().st_mode & 0o777 == 0o600
result = call("/api/auth/setup", {"code": code_file.read_text().strip(),
    "password": "isolated-container-test-password"}, session["csrf"])
csrf = result["csrf"]
assert not code_file.exists()
assert Path("/state/settings.json").stat().st_mode & 0o777 == 0o600
overview = call("/api/overview")
assert len(overview["services"]) == 6
assert all(item["status"] == "unlinked" for item in overview["services"])
assert overview["storage"]["disk"]["total"] > 0
plan = call("/api/setup/preview", {"folders": True}, csrf)
assert plan["can_apply"] and plan["steps"][0]["status"] == "create"
result = call("/api/setup/apply", {"token": plan["token"]}, csrf)
assert result["steps"][0]["status"] == "done"
assert all(step["status"] == "blocked" for step in result["steps"][1:])
assert not result["complete"]
checks = call("/api/storage/check", {}, csrf)
assert all(item["hardlinks"] for item in checks["results"])
assert not list(Path("/data").rglob(".media-stack-check-*"))
for path in ("/app.js", "/format.mjs", "/style.css", "/fonts/plex-regular.woff2"):
    with opener.open(base + path, timeout=5) as response:
        assert response.status == 200
        assert response.headers["X-Content-Type-Options"] == "nosniff"
print("Container smoke checks passed: non-root read-only runtime, claim/login, private state, disk stats, reviewed folder creation, hardlinks, and bundled assets.")
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="media-stack-panel:test")
    args = parser.parse_args()
    if not shutil.which("docker"):
        parser.exit(
            1, "Docker CLI and a running daemon are required for the container check.\n"
        )
    name = "media-stack-check-" + secrets.token_hex(6)
    uid, gid = (os.getuid(), os.getgid()) if os.getuid() else (1000, 1000)
    with tempfile.TemporaryDirectory(prefix="media-stack-container-") as directory:
        root = Path(directory)
        for part in ("state", "data"):
            (root / part).mkdir(mode=0o700)
            if os.getuid() == 0:
                os.chown(root / part, uid, gid)
        try:
            subprocess.run(
                [
                    "docker",
                    "run",
                    "--detach",
                    "--rm",
                    "--name",
                    name,
                    "--network",
                    "none",
                    "--user",
                    f"{uid}:{gid}",
                    "--read-only",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges",
                    "--memory",
                    "256m",
                    "--cpus",
                    "1",
                    "--tmpfs",
                    "/tmp:rw,noexec,nosuid,size=16m",
                    "--mount",
                    f"type=bind,src={root / 'state'},dst=/state",
                    "--mount",
                    f"type=bind,src={root / 'data'},dst=/data",
                    args.image,
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                timeout=30,
            )
            subprocess.run(
                ["docker", "exec", name, "python", "-c", SMOKE], check=True, timeout=45
            )
        finally:
            subprocess.run(
                ["docker", "rm", "--force", name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=15,
            )


if __name__ == "__main__":
    main()
