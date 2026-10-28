import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "configure_jellyfin_guide",
    Path(__file__).resolve().parents[1] / "ops/configure_jellyfin_guide.py",
)
guide = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guide)


class GuideConfigurationTests(unittest.TestCase):
    def configure(self, live, repeat=1):
        plugin_path = "/Plugins/" + guide.INJECTOR_ID + "/Configuration"
        state = {
            plugin_path: {"CustomJavaScripts": [{"Name": "Keep me"}], "Other": True},
            "/Branding/Configuration": {"CustomCss": "body { color: red; }"},
            "/System/Configuration/livetv": copy.deepcopy(live),
        }
        writes = []

        def request(req, **kwargs):
            path = req.full_url.removeprefix("http://jellyfin")
            if req.data is not None:
                payload = json.loads(req.data)
                writes.append((path, payload))
                if path == "/System/Configuration/Branding":
                    state["/Branding/Configuration"] = payload
                elif path == "/LiveTv/ListingProviders":
                    state["/System/Configuration/livetv"]["ListingProviders"] = [payload]
                else:
                    state[path] = payload
                return io.BytesIO(b"")
            return io.BytesIO(json.dumps(state[path]).encode())

        with tempfile.TemporaryDirectory() as folder:
            settings = Path(folder) / "settings.json"
            settings.write_text(json.dumps({"jellyfin": {"apiKey": "test-key"}}))
            with (
                patch("sys.argv", ["guide", "--url", "http://jellyfin", "--seerr-settings", str(settings)]),
                patch.object(guide.urllib.request, "urlopen", side_effect=request),
            ):
                for _ in range(repeat):
                    try:
                        guide.main()
                    except SystemExit as error:
                        self.assertEqual(error.code, 2)
                        return writes, state
        return writes, state

    def test_missing_provider_or_tuner_fails_before_any_writes(self):
        provider = {"Type": "xmltv", "Path": "http://dispatcharr/epg"}
        tuner = {"Url": "http://dispatcharr/m3u/UK", "Id": "keep-id"}
        for live in (
            {},
            {"ListingProviders": [], "TunerHosts": [tuner]},
            {"ListingProviders": [provider], "TunerHosts": []},
        ):
            with self.subTest(live=live):
                writes, _ = self.configure(live)
                self.assertEqual(writes, [])

    def test_repeated_configuration_keeps_other_scripts_css_and_tuner_id(self):
        live = {
            "ListingProviders": [{"Type": "xmltv", "Path": "http://dispatcharr/epg", "Id": "provider-id"}],
            "TunerHosts": [{"Url": "http://dispatcharr/m3u/UK", "Id": "keep-id"}],
        }
        writes, state = self.configure(live, repeat=2)
        self.assertEqual(len(writes), 6)
        config = state["/Plugins/" + guide.INJECTOR_ID + "/Configuration"]
        self.assertTrue(config["Other"])
        self.assertEqual([s["Name"] for s in config["CustomJavaScripts"]], ["Keep me", "Media Stack TV Guide"])
        css = state["/Branding/Configuration"]["CustomCss"]
        self.assertIn("body { color: red; }", css)
        self.assertEqual(css.count("/* media-stack-tv:start */"), 1)
        provider = writes[-1][1]
        self.assertEqual(provider["Id"], "provider-id")
        self.assertEqual(provider["EnabledTuners"], ["keep-id"])
        self.assertEqual(state["/System/Configuration/livetv"]["TunerHosts"], live["TunerHosts"])
