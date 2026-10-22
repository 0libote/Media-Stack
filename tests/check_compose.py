"""Check rendered Compose configuration with a real Compose binary."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
command = [os.environ["COMPOSE_BINARY"]] if "COMPOSE_BINARY" in os.environ else ["docker", "compose"]
base = command + ["--env-file", str(ROOT / ".env.example"), "-f", str(ROOT / "compose.yaml")]


def render(extra=()):
    return json.loads(subprocess.check_output(base + list(extra) + ["config", "--format", "json"], text=True))


core = render()
assert set(core["services"]) == {"portal", "jellyfin", "seerr", "radarr", "sonarr", "prowlarr"}
full = render(["-f", str(ROOT / "compose.downloads.yaml")])
services = full["services"]
assert set(services) == set(core["services"]) | {"gluetun", "qbittorrent"}
assert services["qbittorrent"]["network_mode"] == "service:gluetun"
assert "ports" not in services["qbittorrent"]
assert services["qbittorrent"]["depends_on"]["gluetun"]["condition"] == "service_healthy"
assert services["gluetun"]["environment"]["FIREWALL_INPUT_PORTS"] == "8080"
assert services["seerr"]["init"]
for name, service in services.items():
    for port in service.get("ports", []):
        assert port["host_ip"] == "127.0.0.1", (name, port)
shared = []
for name in ("radarr", "sonarr", "qbittorrent"):
    shared.append(next(v["source"] for v in services[name]["volumes"] if v["target"] == "/data"))
assert len(set(shared)) == 1, shared
media = next(v for v in services["jellyfin"]["volumes"] if v["target"] == "/data/media")
assert media["read_only"]

# Exercise the generated dotenv file, not just the hand-written reference.
import importlib.util
spec = importlib.util.spec_from_file_location("media_setup", ROOT / "setup.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)
from unittest.mock import patch
with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    with patch.object(setup.os, "getuid", return_value=1000):
        setup.prepare(root, str(root / "media #1"), "192.0.2.10", "Etc/UTC")
    generated = json.loads(subprocess.check_output(command + ["--env-file", str(root / ".env"),
        "-f", str(ROOT / "compose.yaml"), "config", "--format", "json"], text=True))
    volume = next(v for v in generated["services"]["radarr"]["volumes"] if v["target"] == "/data")
    assert volume["source"] == str(root / "media #1"), volume
    assert generated["services"]["portal"]["ports"][0]["host_ip"] == "192.0.2.10"
print("Compose checks passed: core, VPN namespace, shared paths, private bindings, generated dotenv.")
