"""Switch qBittorrent between VPN and normal networking without changing app data."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def value(text, key, default=""):
    match = re.search(r"^" + re.escape(key) + r"=(.*)$", text, re.MULTILINE)
    return match.group(1).strip().strip("\"'") if match else default


def setting(text, key, content):
    line = key + "=" + content
    if re.search(r"^" + re.escape(key) + "=", text, re.MULTILINE):
        return re.sub(
            r"^" + re.escape(key) + r"=.*$", lambda _: line, text, flags=re.MULTILINE
        )
    return text.rstrip() + "\n" + line + "\n"


def mode_settings(text, enabled, host_vpn=False):
    key = (
        "ZIMAOS_SOURCE_COMPOSE_FILE"
        if value(text, "ZIMAOS_SOURCE_COMPOSE_FILE")
        else "COMPOSE_FILE"
    )
    files = value(text, key, "compose.yaml").split(os.pathsep)
    files = [
        "compose.downloads.direct.yaml" if f == "compose.downloads.yaml" else f
        for f in files
    ]
    files = [
        f
        for f in files
        if Path(f).name not in ("compose.vpn.yaml", "compose.vpn.host.yaml")
    ]
    if "compose.downloads.direct.yaml" not in files:
        raise ValueError("Enable downloads first; see docs/downloads.md.")
    if enabled:
        files.insert(
            files.index("compose.downloads.direct.yaml") + 1, "compose.vpn.yaml"
        )
        if host_vpn:
            files.append("compose.vpn.host.yaml")
    text = setting(text, key, os.pathsep.join(files))
    return setting(text, "VPN_ENABLED", "true" if enabled else "false")


def routed_config(current, target, saved_vpn=None):
    """Keep dashboard edits while replacing only the selected network routing."""
    result = json.loads(json.dumps(current))
    torrent = result["services"]["qbittorrent"]
    for key in ("network_mode", "networks", "ports", "depends_on"):
        torrent.pop(key, None)
        if key in target["services"]["qbittorrent"]:
            torrent[key] = target["services"]["qbittorrent"][key]
    if "gluetun" in target["services"]:
        result["services"]["gluetun"] = (
            current["services"].get("gluetun")
            or saved_vpn
            or target["services"]["gluetun"]
        )
    else:
        result["services"].pop("gluetun", None)
    result["services"]["portal"].setdefault("environment", {})["VPN_ENABLED"] = target[
        "services"
    ]["portal"]["environment"]["VPN_ENABLED"]
    return result


def interface_settings(text, enabled):
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line == "[BitTorrent]"), None)
    if start is None:
        lines += ["", "[BitTorrent]"]
        start = len(lines) - 1
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("[")),
        len(lines),
    )
    keys = {
        "Session\\Interface": "tun0" if enabled else "",
        "Session\\InterfaceName": "tun0" if enabled else "",
        "Session\\InterfaceAddress": "",
    }
    section = [
        line for line in lines[start + 1 : end] if line.split("=", 1)[0] not in keys
    ]
    lines[start + 1 : end] = section + [key + "=" + val for key, val in keys.items()]
    return "\n".join(lines) + "\n"


def atomic_write(path, text):
    previous = path.stat() if path.exists() else None
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".vpn-")
    try:
        with os.fdopen(descriptor, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(temporary, previous.st_mode & 0o777 if previous else 0o600)
        if previous and os.geteuid() == 0:
            os.chown(temporary, previous.st_uid, previous.st_gid)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def remove_stopped_vpn(project):
    # ZimaOS Start also starts orphan containers, conflicting with direct downloads.
    ids = subprocess.check_output(
        [
            "docker",
            "ps",
            "-aq",
            "--filter",
            "label=com.docker.compose.project=" + project,
            "--filter",
            "label=com.docker.compose.service=gluetun",
            "--filter",
            "status=exited",
        ],
        text=True,
    ).split()
    if ids:
        subprocess.run(["docker", "rm", *ids], check=True)


def check_media_disk(guard=Path("/etc/media-stack.conf")):
    if not guard.exists():
        return
    text = guard.read_text()
    mount = value(text, "MEDIA_STACK_MOUNT")
    if mount:
        if not os.path.ismount(mount):
            raise ValueError("Media disk is unavailable; routing was not changed.")
        actual = subprocess.check_output(
            ["findmnt", "-n", "-o", "UUID", "--target", mount], text=True
        ).strip()
        if (
            not actual
            or actual.casefold() != value(text, "MEDIA_STACK_UUID").casefold()
        ):
            raise ValueError("Media disk UUID changed; routing was not changed.")


def switch(enabled):
    check_media_disk()
    env = ROOT / ".env"
    original = env.read_text()
    changed = mode_settings(
        original, enabled, (ROOT / "compose.vpn.host.yaml").exists()
    )
    dashboard = (
        Path(value(original, "COMPOSE_FILE"))
        if value(original, "ZIMAOS_SOURCE_COMPOSE_FILE")
        else None
    )
    source_env = (
        setting(changed, "COMPOSE_FILE", value(changed, "ZIMAOS_SOURCE_COMPOSE_FILE"))
        if dashboard
        else changed
    )
    # Validate the selected configuration before stopping a working download client.
    descriptor, candidate = tempfile.mkstemp(dir=ROOT, prefix=".vpn-env-")
    try:
        with os.fdopen(descriptor, "w") as f:
            f.write(source_env)
        config = json.loads(
            subprocess.check_output(
                [
                    "docker",
                    "compose",
                    "--env-file",
                    candidate,
                    "config",
                    "--format",
                    "json",
                ],
                text=True,
            )
        )
    finally:
        Path(candidate).unlink(missing_ok=True)
    old_config = json.loads(
        subprocess.check_output(
            ["docker", "compose", "config", "--format", "json"], text=True
        )
    )
    old_dashboard = dashboard.read_text() if dashboard else None
    if dashboard:
        saved_path = ROOT / "config/zima-gluetun.json"
        saved = json.loads(saved_path.read_text()) if saved_path.exists() else None
        if "gluetun" in old_config["services"]:
            atomic_write(
                saved_path,
                json.dumps(old_config["services"]["gluetun"], indent=2) + "\n",
            )
        config = routed_config(old_config, config, saved)
        descriptor, candidate = tempfile.mkstemp(dir=ROOT, prefix=".vpn-compose-")
        try:
            with os.fdopen(descriptor, "w") as f:
                json.dump(config, f)
            subprocess.run(
                ["docker", "compose", "-f", candidate, "config", "--quiet"], check=True
            )
        finally:
            Path(candidate).unlink(missing_ok=True)
    mount = next(
        v["source"]
        for v in config["services"]["qbittorrent"]["volumes"]
        if v["target"] == "/config"
    )
    path = Path(mount) / "qBittorrent/qBittorrent.conf"
    stop = ["qbittorrent"] + (
        ["gluetun"] if "gluetun" in old_config["services"] else []
    )
    subprocess.run(["docker", "compose", "stop", *stop], check=True)
    # Read after shutdown so qBittorrent's final settings flush is preserved.
    old_preferences = path.read_text() if path.exists() else None
    try:
        if old_preferences is not None:
            atomic_write(path, interface_settings(old_preferences, enabled))
        if dashboard:
            atomic_write(dashboard, json.dumps(config, indent=2) + "\n")
        atomic_write(env, changed)
        subprocess.run(
            [
                "docker",
                "compose",
                "up",
                "-d",
                "--no-build",
                "--pull",
                "never",
                "--wait",
                "--wait-timeout",
                "180",
                "qbittorrent",
                "portal",
            ],
            check=True,
        )
        if dashboard and not enabled:
            remove_stopped_vpn(config["name"])
    except Exception:
        subprocess.run(
            [
                "docker",
                "compose",
                "stop",
                "qbittorrent",
                *(["gluetun"] if enabled else []),
            ],
            check=False,
        )
        atomic_write(env, original)
        if dashboard:
            atomic_write(dashboard, old_dashboard)
        if old_preferences is not None:
            atomic_write(path, old_preferences)
        subprocess.run(
            [
                "docker",
                "compose",
                "up",
                "-d",
                "--no-build",
                "--pull",
                "never",
                "qbittorrent",
                "portal",
            ],
            check=False,
        )
        raise
    print(
        "VPN routing enabled."
        if enabled
        else "VPN off: downloads use your normal internet connection."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["on", "off"])
    args = parser.parse_args()
    os.chdir(ROOT)
    with (ROOT / "config/.compose.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        switch(args.mode == "on")


if __name__ == "__main__":
    main()
