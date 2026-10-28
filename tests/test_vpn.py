"""VPN switches keep custom deployment files, settings, and rollback state."""

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "vpn", Path(__file__).resolve().parents[1] / "ops/vpn.py"
)
vpn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vpn)


class VPNTests(unittest.TestCase):
    def test_vpn_cleanup_targets_only_exited_containers_in_this_project(self):
        for output in ("", "stopped-vpn\n"):
            with (
                self.subTest(output=output),
                patch.object(
                    vpn.subprocess, "check_output", return_value=output
                ) as inspect,
                patch.object(vpn.subprocess, "run") as run,
            ):
                vpn.remove_stopped_vpn("test-stack")
                args = inspect.call_args.args[0]
                for selector in (
                    "label=com.docker.compose.project=test-stack",
                    "label=com.docker.compose.service=gluetun",
                    "status=exited",
                ):
                    self.assertIn(selector, args)
                if output:
                    run.assert_called_once_with(
                        ["docker", "rm", "stopped-vpn"], check=True
                    )
                else:
                    run.assert_not_called()

    def test_zimaos_modes_keep_the_dashboard_as_the_active_compose_file(self):
        original = "COMPOSE_FILE=/apps/media-stack/docker-compose.yml\nZIMAOS_SOURCE_COMPOSE_FILE=compose.yaml:compose.downloads.direct.yaml:compose.host.yaml\n"
        enabled = vpn.mode_settings(original, True, True)
        self.assertIn("COMPOSE_FILE=/apps/media-stack/docker-compose.yml\n", enabled)
        self.assertIn(
            "ZIMAOS_SOURCE_COMPOSE_FILE=compose.yaml:compose.downloads.direct.yaml:compose.vpn.yaml:compose.host.yaml:compose.vpn.host.yaml\n",
            enabled,
        )
        self.assertIn(
            "COMPOSE_FILE=/apps/media-stack/docker-compose.yml\n",
            vpn.mode_settings(enabled, False),
        )

    def test_routing_changes_preserve_dashboard_settings_and_saved_vpn(self):
        current = {
            "services": {
                "qbittorrent": {
                    "image": "custom:version",
                    "volumes": ["keep"],
                    "ports": [8080],
                    "networks": {"default": {}},
                },
                "portal": {"environment": {"VPN_ENABLED": "false", "OTHER": "keep"}},
                "jellyfin": {"environment": {"TZ": "Europe/London"}},
            },
            "x-casaos": {"main": "portal"},
        }
        target = {
            "services": {
                "qbittorrent": {
                    "network_mode": "service:gluetun",
                    "depends_on": {"gluetun": {"condition": "service_healthy"}},
                },
                "gluetun": {"image": "default"},
                "portal": {"environment": {"VPN_ENABLED": "true"}},
            }
        }
        enabled = vpn.routed_config(
            current, target, {"image": "saved:vpn", "environment": {"CUSTOM": "keep"}}
        )
        q = enabled["services"]["qbittorrent"]
        self.assertEqual(q["network_mode"], "service:gluetun")
        self.assertNotIn("ports", q)
        self.assertNotIn("networks", q)
        self.assertEqual(q["image"], "custom:version")
        self.assertEqual(q["volumes"], ["keep"])
        self.assertEqual(enabled["services"]["gluetun"]["image"], "saved:vpn")
        self.assertEqual(enabled["services"]["portal"]["environment"]["OTHER"], "keep")
        self.assertEqual(
            enabled["services"]["jellyfin"], current["services"]["jellyfin"]
        )
        self.assertEqual(enabled["x-casaos"], current["x-casaos"])
        disabled = vpn.routed_config(enabled, current)
        self.assertNotIn("gluetun", disabled["services"])
        self.assertNotIn("network_mode", disabled["services"]["qbittorrent"])
        self.assertEqual(disabled["services"]["qbittorrent"]["ports"], [8080])
        self.assertNotIn("gluetun", current["services"])

    def test_modes_keep_private_host_settings_and_remove_only_vpn_files(self):
        original = "COMPOSE_FILE=compose.yaml:compose.downloads.direct.yaml:compose.host.yaml\nTZ=Europe/London\n"
        enabled = vpn.mode_settings(original, True, True)
        self.assertIn(
            "compose.downloads.direct.yaml:compose.vpn.yaml:compose.host.yaml:compose.vpn.host.yaml",
            enabled,
        )
        self.assertIn("VPN_ENABLED=true", enabled)
        disabled = vpn.mode_settings(enabled, False)
        self.assertIn(
            "COMPOSE_FILE=compose.yaml:compose.downloads.direct.yaml:compose.host.yaml\n",
            disabled,
        )
        self.assertIn("VPN_ENABLED=false", disabled)
        self.assertIn("TZ=Europe/London", disabled)

    def test_downloads_must_be_enabled_explicitly(self):
        with self.assertRaises(ValueError):
            vpn.mode_settings("COMPOSE_FILE=compose.yaml\n", False)

    def test_legacy_file_changes_only_during_an_explicit_mode_switch(self):
        original = "COMPOSE_FILE=compose.yaml:compose.downloads.yaml\n"
        enabled = vpn.mode_settings(original, True)
        self.assertIn("compose.downloads.direct.yaml:compose.vpn.yaml", enabled)
        disabled = vpn.mode_settings(original, False)
        self.assertIn(
            "COMPOSE_FILE=compose.yaml:compose.downloads.direct.yaml\n", disabled
        )
        self.assertNotIn("compose.vpn.yaml", disabled)

    def test_missing_media_disk_refuses_mode_change(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "media-stack.conf"
            config.write_text(
                "MEDIA_STACK_MOUNT=/media/Media\nMEDIA_STACK_UUID=expected\n"
            )
            with patch.object(vpn.os.path, "ismount", return_value=False):
                with self.assertRaisesRegex(ValueError, "unavailable"):
                    vpn.check_media_disk(config)

    def test_interface_binding_changes_without_replacing_other_preferences(self):
        original = "[BitTorrent]\nSession\\Interface=tun0\nSession\\InterfaceName=tun0\nSession\\DefaultSavePath=/media/Downloads\n[WebUI]\nPassword_PBKDF2=keep-this\n"
        direct = vpn.interface_settings(original, False)
        self.assertIn("Session\\Interface=\n", direct)
        self.assertNotIn("tun0", direct)
        restored = vpn.interface_settings(direct, True)
        self.assertIn("Session\\Interface=tun0\n", restored)
        for content in (direct, restored):
            self.assertIn("Session\\DefaultSavePath=/media/Downloads", content)
            self.assertIn("Password_PBKDF2=keep-this", content)

    def test_preferences_read_failure_restarts_the_original_stack(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            env = root / ".env"
            original = "COMPOSE_FILE=compose.yaml:compose.downloads.direct.yaml:compose.vpn.yaml\nVPN_ENABLED=true\n"
            env.write_text(original)
            preferences = root / "qBittorrent/qBittorrent.conf"
            preferences.parent.mkdir()
            preferences.write_text("unchanged preferences")
            config = {"services": {"gluetun": {}, "qbittorrent": {
                "volumes": [{"source": str(root), "target": "/config"}],
            }}}
            read_text = Path.read_text
            calls = []

            def read(path, *args, **kwargs):
                if path == preferences:
                    self.assertEqual(calls[-1][2], "stop")
                    raise PermissionError("preferences unreadable")
                return read_text(path, *args, **kwargs)

            with (
                patch.object(vpn, "ROOT", root),
                patch.object(vpn, "check_media_disk"),
                patch.object(vpn.subprocess, "check_output", return_value=json.dumps(config)),
                patch.object(vpn.subprocess, "run", side_effect=lambda args, **kw: calls.append(args)),
                patch.object(Path, "read_text", read),
            ):
                with self.assertRaisesRegex(PermissionError, "preferences unreadable"):
                    vpn.switch(False)
            self.assertEqual(calls[-1][2:4], ["up", "-d"])
            self.assertEqual(calls[-1][-2:], ["qbittorrent", "portal"])
            self.assertEqual(env.read_text(), original)
            self.assertEqual(preferences.read_text(), "unchanged preferences")
            self.assertFalse(list(root.glob(".vpn-*")))

    def test_failed_start_restores_original_mode_and_preferences(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            env = root / ".env"
            env.write_text(
                "COMPOSE_FILE=compose.yaml:compose.downloads.direct.yaml:compose.vpn.yaml\nVPN_ENABLED=true\n"
            )
            env.chmod(0o600)
            config_dir = root / "config/qbittorrent/qBittorrent"
            config_dir.mkdir(parents=True)
            preferences = config_dir / "qBittorrent.conf"
            preferences.write_text("[BitTorrent]\nSession\\Interface=tun0\n")
            original_env, original_preferences = (
                env.read_text(),
                preferences.read_text(),
            )
            config = {
                "services": {
                    "gluetun": {},
                    "qbittorrent": {
                        "volumes": [
                            {"source": str(config_dir.parent), "target": "/config"}
                        ]
                    },
                }
            }

            def run(args, **kwargs):
                if "up" in args and kwargs.get("check"):
                    raise subprocess.CalledProcessError(1, ["docker", "compose", "up"])

            with (
                patch.object(vpn, "ROOT", root),
                patch.object(
                    vpn.subprocess, "check_output", return_value=json.dumps(config)
                ),
                patch.object(vpn.subprocess, "run", side_effect=run),
            ):
                with self.assertRaises(subprocess.CalledProcessError):
                    vpn.switch(False)
            self.assertEqual(env.read_text(), original_env)
            self.assertEqual(preferences.read_text(), original_preferences)
            self.assertEqual(env.stat().st_mode & 0o777, 0o600)
            self.assertFalse(list(root.glob(".vpn-*")))

    def test_dashboard_config_is_also_restored_after_a_failed_start(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config_dir = root / "config/qbittorrent/qBittorrent"
            config_dir.mkdir(parents=True)
            preferences = config_dir / "qBittorrent.conf"
            preferences.write_text("[BitTorrent]\nSession\\Interface=tun0\n")
            dashboard = root / "dashboard.yml"
            dashboard.write_text("original dashboard content\n")
            env = root / ".env"
            env.write_text(
                "COMPOSE_FILE="
                + str(dashboard)
                + "\nZIMAOS_SOURCE_COMPOSE_FILE=compose.yaml:compose.downloads.direct.yaml:compose.vpn.yaml\nVPN_ENABLED=true\n"
            )
            original_env = env.read_text()
            current = {
                "services": {
                    "qbittorrent": {
                        "network_mode": "service:gluetun",
                        "volumes": [
                            {"source": str(config_dir.parent), "target": "/config"}
                        ],
                    },
                    "portal": {"environment": {"VPN_ENABLED": "true"}},
                    "gluetun": {"image": "saved"},
                }
            }
            target = {
                "services": {
                    "qbittorrent": {"ports": [8080]},
                    "portal": {"environment": {"VPN_ENABLED": "false"}},
                }
            }

            def run(args, **kwargs):
                if "up" in args and kwargs.get("check"):
                    raise subprocess.CalledProcessError(1, args)

            with (
                patch.object(vpn, "ROOT", root),
                patch.object(
                    vpn.subprocess,
                    "check_output",
                    side_effect=[json.dumps(target), json.dumps(current)],
                ),
                patch.object(vpn.subprocess, "run", side_effect=run),
            ):
                with self.assertRaises(subprocess.CalledProcessError):
                    vpn.switch(False)
            self.assertEqual(env.read_text(), original_env)
            self.assertEqual(dashboard.read_text(), "original dashboard content\n")
            self.assertIn("Session\\Interface=tun0", preferences.read_text())
            self.assertFalse(list(root.glob(".vpn-*")))
