"""Register this deployed project as one complete, editable ZimaOS application."""

import fcntl
import json
import os
from pathlib import Path
import subprocess

from vpn import ROOT, atomic_write, remove_stopped_vpn, setting, value

APPS = Path("/var/lib/casaos/apps")


def register():
    apps = APPS
    if not apps.is_dir():
        raise SystemExit("ZimaOS app directory is unavailable.")
    env = ROOT / ".env"
    original = env.read_text()
    if value(original, "ZIMAOS_SOURCE_COMPOSE_FILE"):
        raise SystemExit("This project is already registered with ZimaOS.")
    config = json.loads(
        subprocess.check_output(
            ["docker", "compose", "config", "--format", "json"], text=True
        )
    )
    app = apps / config["name"]
    if app.exists():
        raise SystemExit("The app directory already exists; refusing to overwrite it.")
    config["x-casaos"] = {
        "main": "portal",
        "port_map": "8088",
        "scheme": "http",
        "index": "/",
        "is_uncontrolled": False,
        "store_app_id": config["name"],
        "title": {"custom": "Media Stack", "en_US": "Media Stack"},
    }
    app.mkdir(mode=0o700)
    compose = app / "docker-compose.yml"
    try:
        atomic_write(compose, json.dumps(config, indent=2) + "\n")
        subprocess.run(
            ["docker", "compose", "-f", str(compose), "config", "--quiet"], check=True
        )
        atomic_write(ROOT / "config/pre-zimaos.env", original)
        changed = setting(
            original,
            "ZIMAOS_SOURCE_COMPOSE_FILE",
            value(original, "COMPOSE_FILE", "compose.yaml"),
        )
        atomic_write(env, setting(changed, "COMPOSE_FILE", str(compose)))
        atomic_write(
            app / ".env",
            "# Service settings are resolved in docker-compose.yml.\n"
            "# Project recovery and routing settings remain in the checkout's .env.\n",
        )
        # ZimaOS discovers the app definition from each container's Compose labels.
        subprocess.run(
            [
                "docker",
                "compose",
                "up",
                "-d",
                "--no-deps",
                "--force-recreate",
                "--no-build",
                "--pull",
                "never",
                "--wait",
                "--wait-timeout",
                "180",
                "portal",
            ],
            check=True,
        )
        if "gluetun" not in config["services"]:
            remove_stopped_vpn(config["name"])
    except Exception:
        atomic_write(env, original)
        (app / ".env").unlink(missing_ok=True)
        compose.unlink(missing_ok=True)
        app.rmdir()
        subprocess.run(
            ["docker", "compose", "up", "-d", "--no-build", "--pull", "never"],
            check=False,
        )
        raise
    print("Registered Media Stack in ZimaOS with its complete Compose configuration.")


if __name__ == "__main__":
    os.chdir(ROOT)
    with (ROOT / "config/.compose.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        register()
