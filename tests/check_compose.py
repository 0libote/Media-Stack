"""Check rendered Compose configuration with a real Compose binary."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
command = (
    [os.environ["COMPOSE_BINARY"]]
    if "COMPOSE_BINARY" in os.environ
    else ["docker", "compose"]
)
base = command + [
    "--env-file",
    str(ROOT / ".env.example"),
    "-f",
    str(ROOT / "compose.yaml"),
]


def render(extra=()):
    return json.loads(
        subprocess.check_output(
            base + list(extra) + ["config", "--format", "json"], text=True
        )
    )


core = render()
with patch.dict(os.environ, {"JELLYFIN_RENDER_GID": "109"}):
    gpu = render(["-f", str(ROOT / "compose.gpu.yaml")])
assert gpu["services"]["jellyfin"]["devices"][0]["target"] == "/dev/dri/renderD128"
assert gpu["services"]["jellyfin"]["group_add"] == ["109"]
assert not core["services"]["jellyfin"].get("devices")
assert set(core["services"]) == {
    "portal",
    "jellyfin",
    "seerr",
    "radarr",
    "sonarr",
    "prowlarr",
    "dispatcharr",
}
direct = render(["-f", str(ROOT / "compose.downloads.direct.yaml")])
assert set(direct["services"]) == set(core["services"]) | {"qbittorrent"}
assert "network_mode" not in direct["services"]["qbittorrent"]
assert not direct["services"]["qbittorrent"].get("depends_on")
assert direct["services"]["qbittorrent"]["ports"][0]["published"] == "8080"
full = render(
    [
        "-f",
        str(ROOT / "compose.downloads.direct.yaml"),
        "-f",
        str(ROOT / "compose.vpn.yaml"),
    ]
)
legacy = render(["-f", str(ROOT / "compose.downloads.yaml")])
assert legacy["services"]["qbittorrent"]["network_mode"] == "service:gluetun"
services = full["services"]
assert set(services) == set(core["services"]) | {"gluetun", "qbittorrent"}
assert services["qbittorrent"]["network_mode"] == "service:gluetun"
assert "ports" not in services["qbittorrent"]
assert (
    services["qbittorrent"]["depends_on"]["gluetun"]["condition"] == "service_healthy"
)
assert services["gluetun"]["environment"]["FIREWALL_INPUT_PORTS"] == "8080"
assert "qbittorrent" in services["gluetun"]["networks"]["default"]["aliases"]
for name in core["services"]:
    assert not services[name].get("depends_on"), name
assert "network_mode" not in services["dispatcharr"]
assert services["seerr"]["init"]
for name in ("radarr", "sonarr", "prowlarr", "seerr", "qbittorrent", "dispatcharr"):
    assert services[name]["healthcheck"]["test"], name
for name in ("radarr", "sonarr", "prowlarr"):
    assert services[name]["environment"]["HEALTH_PORT"].isdigit(), name
for name, service in services.items():
    assert service["restart"] == "unless-stopped", name
    assert service["stop_grace_period"] == "1m0s", name
    for port in service.get("ports", []):
        assert port["host_ip"] == "127.0.0.1", (name, port)
shared = []
for name in ("portal", "jellyfin", "radarr", "sonarr", "qbittorrent"):
    shared.append(
        next(v["source"] for v in services[name]["volumes"] if v["target"] == "/data")
    )
assert len(set(shared)) == 1, shared
media = next(v for v in services["jellyfin"]["volumes"] if v["target"] == "/data")
assert media["read_only"]
panel = services["portal"]
assert panel["read_only"]
assert panel["cap_drop"] == ["ALL"]
assert all("docker.sock" not in str(volume) for volume in panel["volumes"])
assert all(
    volume.get("read_only")
    for volume in panel["volumes"]
    if volume["target"].startswith("/connections/")
)

# Exercise the generated dotenv file, not just the hand-written reference.
spec = importlib.util.spec_from_file_location("media_setup", ROOT / "setup.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)
with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    with patch.object(setup.os, "getuid", return_value=1000):
        setup.prepare(root, str(root / "media #1"), "192.0.2.10", "Etc/UTC")
    generated = json.loads(
        subprocess.check_output(
            command
            + [
                "--env-file",
                str(root / ".env"),
                "-f",
                str(ROOT / "compose.yaml"),
                "config",
                "--format",
                "json",
            ],
            text=True,
        )
    )
    volume = next(
        v for v in generated["services"]["radarr"]["volumes"] if v["target"] == "/data"
    )
    assert volume["source"] == str(root / "media #1"), volume
    assert generated["services"]["portal"]["ports"][0]["host_ip"] == "192.0.2.10"
print(
    "Compose checks passed: core, VPN namespace, shared paths, private bindings, generated dotenv."
)
