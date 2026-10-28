"""Restore this Compose project after boot, disk delays, or VPN namespace changes."""

import json
import fcntl
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

DISK_RECOVERY = Path(__file__).resolve().parents[1] / "config/.disk-unavailable"


def compose(*args, capture=False):
    return (
        subprocess.check_output(["docker", "compose", *args], text=True)
        if capture
        else subprocess.run(["docker", "compose", *args], check=True)
    )


def disk_ready(path, expected_uuid):
    if not os.path.ismount(path):
        return False
    actual = subprocess.check_output(
        ["findmnt", "-n", "-o", "UUID", "--target", path], text=True
    ).strip()
    return bool(expected_uuid) and actual.casefold() == expected_uuid.casefold()


def inspect_services():
    ids = compose("ps", "-aq", capture=True).split()
    if not ids:
        return {}
    containers = json.loads(
        subprocess.check_output(["docker", "inspect", *ids], text=True)
    )
    return {c["Config"]["Labels"]["com.docker.compose.service"]: c for c in containers}


def namespace(container):
    return subprocess.check_output(
        ["docker", "exec", container["Id"], "readlink", "/proc/1/ns/net"], text=True
    ).strip()


def configured_services():
    return set(compose("config", "--services", capture=True).split())


def stop_action():
    from vpn import ROOT, value

    env = ROOT / ".env"
    return (
        value(env.read_text(), "VPN_STOP_ACTION", "pause") if env.exists() else "pause"
    )


def was_manually_stopped(container):
    state = container["State"]
    if state.get("Status") != "exited":
        return False
    # A successful app exit alone is insufficient evidence to remove VPN routing.
    try:
        stamp = re.sub(r"(\.\d{6})\d+", r"\1", state["FinishedAt"])
        finished = datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except (KeyError, ValueError):
        return False
    events = subprocess.check_output(
        [
            "docker",
            "events",
            "--since",
            str(int(finished)),
            "--until",
            str(int(time.time()) + 1),
            "--filter",
            "container=" + container["Id"],
            "--filter",
            "event=stop",
            "--format",
            "{{json .}}",
        ],
        text=True,
        timeout=10,
    )
    return any(
        json.loads(line).get("timeNano", 0) / 1e9 >= finished - 0.001
        for line in events.splitlines()
        if line.strip()
    )


def switch_to_direct():
    from vpn import switch

    # The recovery entrypoint already holds the same lock as the mode command.
    switch(False)


def main():
    os.chdir(Path(__file__).resolve().parents[1])
    mount = os.environ.get("MEDIA_STACK_MOUNT")
    if mount and not disk_ready(mount, os.environ.get("MEDIA_STACK_UUID", "")):
        # Never let library scans or downloads use an empty host mountpoint.
        DISK_RECOVERY.touch()
        compose("stop", "-t", "60")
        raise SystemExit(
            "Media disk unavailable or UUID changed; stack stopped. Will retry."
        )

    active = configured_services()
    before = {
        name: container
        for name, container in inspect_services().items()
        if name in active
    }
    # A dashboard Stop must stay stopped; boot recovery has no retained stop event.
    if (
        active
        and not DISK_RECOVERY.exists()
        and active <= before.keys()
        and all(c["State"].get("Status") == "exited" for c in before.values())
        and "portal" in before
        and was_manually_stopped(before["portal"])
    ):
        print("The complete stack was deliberately stopped; leaving it stopped.")
        return
    vpn = before.get("gluetun")
    if vpn and vpn["State"].get("Status") == "exited":
        if stop_action() == "direct" and was_manually_stopped(vpn):
            print("Gluetun was stopped. Switching downloads to the normal connection.")
            switch_to_direct()
            active = configured_services()
            before = {
                name: c for name, c in inspect_services().items() if name in active
            }
        elif vpn["State"].get("ExitCode") == 0:
            print(
                "Gluetun is stopped. VPN downloads stay paused; other apps remain available."
            )
            active -= {"gluetun", "qbittorrent"}
    unhealthy = {
        name
        for name, container in before.items()
        if name in active
        and container["State"].get("Health", {}).get("Status") == "unhealthy"
    }
    if "gluetun" in unhealthy:
        compose("stop", "qbittorrent")
        compose("restart", "--no-deps", "gluetun")
        unhealthy.discard("gluetun")
        unhealthy.discard("qbittorrent")
    if unhealthy:
        compose("restart", "--no-deps", *sorted(unhealthy))

    # Compose re-evaluates dependency order; Docker restart policies alone do not.
    if not active:
        return
    compose("up", "-d", "--no-build", "--pull", "never", *sorted(active))
    current = inspect_services()
    vpn, torrent = current.get("gluetun"), current.get("qbittorrent")
    if (
        "gluetun" in active
        and vpn
        and torrent
        and vpn["State"]["Running"]
        and torrent["State"]["Running"]
    ):
        if namespace(vpn) != namespace(torrent):
            compose(
                "up",
                "-d",
                "--no-deps",
                "--force-recreate",
                "--no-build",
                "--pull",
                "never",
                "qbittorrent",
            )
    compose(
        "up",
        "-d",
        "--no-build",
        "--pull",
        "never",
        "--wait",
        "--wait-timeout",
        "180",
        *sorted(active),
    )
    if "jellyfin" in active and current.get("jellyfin", {}).get("State", {}).get("Running"):
        subprocess.run(
            [sys.executable, str(Path(__file__).with_name("jellyfin_web_paging.py")),
             "--container", current["jellyfin"]["Id"]],
            check=False,
            timeout=60,
        )
    DISK_RECOVERY.unlink(missing_ok=True)


if __name__ == "__main__":
    with (Path(__file__).resolve().parents[1] / "config/.compose.lock").open(
        "a"
    ) as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        main()
