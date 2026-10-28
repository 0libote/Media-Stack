import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "dispatcharr_playback", Path(__file__).resolve().parents[1] / "ops/dispatcharr_playback.py"
)
playback = importlib.util.module_from_spec(spec)
spec.loader.exec_module(playback)


class PlaybackTests(unittest.TestCase):
    def test_compatibility_is_limited_to_amagi_hls(self):
        self.assertTrue(playback.amagi_hls("https://station.amagi.tv/live/playlist.m3u8?session=1"))
        for url in [
            "https://amagi.tv.example.com/live.m3u8", "https://other.example/live.m3u8",
            "file:///data/live.m3u8", "https://station.amagi.tv/live.mpd",
        ]:
            self.assertFalse(playback.amagi_hls(url))

    def test_extensionless_segments_keep_local_file_protocol_disabled(self):
        import shlex
        args = shlex.split(playback.PARAMETERS)
        self.assertEqual(args[args.index("-allowed_segment_extensions") + 1], "ALL")
        self.assertNotIn("file", args[args.index("-protocol_whitelist") + 1].split(","))
