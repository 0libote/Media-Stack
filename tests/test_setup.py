import importlib.util
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "media_setup", Path(__file__).resolve().parents[1] / "setup.py"
)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)

# Synthetic fixture, never a real provider credential.
WIREGUARD = """[Interface]
PrivateKey = AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE=
Address = 10.2.0.2/32
[Peer]
PublicKey = AgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgI=
AllowedIPs = 0.0.0.0/0
Endpoint = 203.0.113.1:51820
"""


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "repo"
        self.root.mkdir()
        # CI may run as root; test the intended unprivileged user explicitly.
        self.uid = patch.object(setup.os, "getuid", return_value=1000)
        self.gid = patch.object(setup.os, "getgid", return_value=1000)
        self.uid.start()
        self.gid.start()
        self.addCleanup(self.uid.stop)
        self.addCleanup(self.gid.stop)

    def prepare(self, **kwargs):
        settings = dict(data_dir="data", bind_address="127.0.0.1", timezone="Etc/UTC")
        settings.update(kwargs)
        setup.prepare(self.root, **settings)

    def test_default_install_creates_shared_paths_and_private_env(self):
        self.prepare()
        env = (self.root / ".env").read_text()
        self.assertIn("COMPOSE_FILE=compose.yaml\n", env)
        self.assertIn("PUID=1000\nPGID=1000\n", env)
        self.assertEqual(stat.S_IMODE((self.root / ".env").stat().st_mode), 0o600)
        for path in (
            "config/jellyfin",
            "config/jellyfin-cache",
            "config/prowlarr",
            "data/media/movies",
            "data/media/tv",
            "data/torrents/incomplete",
        ):
            self.assertTrue((self.root / path).is_dir(), path)
        self.assertFalse((self.root / "secrets").exists())

    def test_existing_env_and_library_are_preserved(self):
        self.prepare()
        media = self.root / "data/media/movies/example.txt"
        media.write_text("keep me")
        previous = (self.root / ".env").read_bytes()
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.prepare(bind_address="192.0.2.1")
        self.assertEqual((self.root / ".env").read_bytes(), previous)
        self.assertEqual(media.read_text(), "keep me")

    def test_vpn_config_is_private_and_not_written_into_env(self):
        source = Path(self.temp.name) / "provider.conf"
        source.write_text(WIREGUARD)
        self.prepare(vpn_config=source)
        secret = self.root / "secrets/wg0.conf"
        self.assertEqual(secret.read_text(), WIREGUARD)
        self.assertEqual(stat.S_IMODE(secret.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(secret.parent.stat().st_mode), 0o700)
        env = (self.root / ".env").read_text()
        self.assertIn(
            "COMPOSE_FILE=compose.yaml:compose.downloads.direct.yaml:compose.vpn.yaml\n",
            env,
        )
        self.assertIn("VPN_ENABLED=true\n", env)
        self.assertNotIn("AQEBAQEBAQE", env)
        self.assertTrue(source.exists())

    def test_direct_downloads_do_not_require_vpn_secrets(self):
        self.prepare(downloads=True)
        env = (self.root / ".env").read_text()
        self.assertIn("COMPOSE_FILE=compose.yaml:compose.downloads.direct.yaml\n", env)
        self.assertIn("DOWNLOADS_ENABLED=true\nVPN_ENABLED=false\n", env)
        self.assertTrue((self.root / "config/qbittorrent").is_dir())
        self.assertTrue((self.root / "data/recordings").is_dir())
        self.assertFalse((self.root / "secrets").exists())

    def test_invalid_input_fails_before_writing_settings(self):
        for settings in (
            {"bind_address": "server.local"},
            {"timezone": "Etc/UTC\nEVIL=1"},
            {"data_dir": "bad\npath"},
            {"data_dir": "$HOME/data"},
            {"data_dir": "."},
            {"data_dir": "config/media"},
            {"data_dir": "secrets/media"},
            {"data_dir": "portal/media"},
        ):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                self.prepare(**settings)
            self.assertFalse((self.root / ".env").exists())

    def test_malformed_or_unsupported_vpn_fails_without_files(self):
        source = Path(self.temp.name) / "bad.conf"
        for content in (
            "[Interface]\nAddress = 10.0.0.1/32\n",
            WIREGUARD.replace("203.0.113.1:51820", "vpn.example:51820"),
            WIREGUARD.replace(":51820", ":70000"),
        ):
            source.write_text(content)
            with self.subTest(content=content), self.assertRaises(ValueError):
                self.prepare(vpn_config=source)
            self.assertFalse((self.root / ".env").exists())
            self.assertFalse((self.root / "secrets").exists())

    def test_external_path_with_spaces_is_supported(self):
        data = Path(self.temp.name) / "my media #1"
        self.prepare(data_dir=str(data))
        self.assertTrue((data / "media/movies").is_dir())
        self.assertIn(f"DATA_DIR='{data}'", (self.root / ".env").read_text())

    def test_invalid_vpn_errors_do_not_echo_secret_text(self):
        source = Path(self.temp.name) / "invalid.conf"
        for text in (
            "[Interface]\nsecret-value-without-equals\n",
            WIREGUARD.replace(
                "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE=", "secret-value"
            ),
        ):
            source.write_text(text)
            with self.assertRaises(ValueError) as caught:
                setup.wireguard_config(source)
            self.assertNotIn("secret-value", str(caught.exception))

    def test_existing_vpn_secret_is_not_overwritten(self):
        secret = self.root / "secrets/wg0.conf"
        secret.parent.mkdir()
        secret.write_text("existing secret")
        source = Path(self.temp.name) / "provider.conf"
        source.write_text(WIREGUARD)
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.prepare(vpn_config=source)
        self.assertEqual(secret.read_text(), "existing secret")
        self.assertFalse((self.root / ".env").exists())

    def test_root_setup_is_rejected(self):
        with (
            patch.object(setup.os, "getuid", return_value=0),
            self.assertRaisesRegex(ValueError, "without sudo"),
        ):
            self.prepare()


if __name__ == "__main__":
    unittest.main()
