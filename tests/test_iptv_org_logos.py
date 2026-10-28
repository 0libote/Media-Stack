import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "iptv_org_logos", Path(__file__).resolve().parents[1] / "ops/iptv_org_logos.py"
)
logos = importlib.util.module_from_spec(spec)
spec.loader.exec_module(logos)


class LogoTests(unittest.TestCase):
    def test_matching_ignores_stream_quality_but_keeps_timeshifts_distinct(self):
        self.assertEqual(logos.normalise("BBC One (1080p) [Geo-blocked]"), logos.normalise("bbc-one"))
        self.assertEqual(logos.normalise("Channel 4 HD"), logos.normalise("4"))
        self.assertEqual(logos.normalise("ITV2 +1"), logos.normalise("itv2-plus-1"))
        self.assertNotEqual(logos.normalise("ITV2"), logos.normalise("ITV2 +1"))

    def test_imgur_and_non_http_sources_are_never_downloaded(self):
        for url in ["https://i.imgur.com/logo.png", "https://imgur.com/logo", "file:///etc/passwd", ""]:
            self.assertFalse(logos.allowed_logo(url))
        self.assertTrue(logos.allowed_logo("https://raw.githubusercontent.com/tv-logo/logo.png"))
