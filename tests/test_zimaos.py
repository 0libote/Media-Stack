"""ZimaOS requires regular deployment files, including its optional environment."""

import importlib.util
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

OPS = Path(__file__).resolve().parents[1] / "ops"
spec = importlib.util.spec_from_file_location("zima_vpn", OPS / "vpn.py")
vpn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vpn)
spec = importlib.util.spec_from_file_location("zimaos", OPS / "zimaos.py")
zimaos = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {"vpn": vpn}):
    spec.loader.exec_module(zimaos)


class ZimaOSTests(unittest.TestCase):
    def test_registration_uses_a_private_regular_environment_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            apps = root / "apps"
            apps.mkdir()
            (root / "config").mkdir()
            env = root / ".env"
            original = "COMPOSE_FILE=compose.yaml\nVPN_STOP_ACTION=direct\n"
            env.write_text(original)
            config = {"name": "media-stack", "services": {"portal": {}}}
            with (
                patch.object(zimaos, "ROOT", root),
                patch.object(zimaos, "APPS", apps),
                patch.object(
                    zimaos.subprocess,
                    "check_output",
                    side_effect=[json.dumps(config), ""],
                ),
                patch.object(zimaos.subprocess, "run"),
            ):
                zimaos.register()
            app_env = apps / "media-stack/.env"
            self.assertTrue(stat.S_ISREG(app_env.lstat().st_mode))
            self.assertEqual(app_env.stat().st_mode & 0o777, 0o600)
            self.assertIn("ZIMAOS_SOURCE_COMPOSE_FILE=compose.yaml", env.read_text())
            self.assertIn("VPN_STOP_ACTION=direct", env.read_text())
            self.assertEqual((root / "config/pre-zimaos.env").read_text(), original)

    def test_repairing_a_symlink_preserves_the_project_environment(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            env = root / "project.env"
            env.write_text("VPN_STOP_ACTION=direct\nVPN_ENABLED=false\n")
            app_env = root / ".env"
            app_env.symlink_to(env)
            vpn.atomic_write(app_env, "# Resolved Compose deployment.\n")
            self.assertTrue(stat.S_ISREG(app_env.lstat().st_mode))
            self.assertEqual(
                env.read_text(), "VPN_STOP_ACTION=direct\nVPN_ENABLED=false\n"
            )
