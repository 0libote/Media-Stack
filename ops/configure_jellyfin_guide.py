"""Configure the guide-first web extension and the curated local XMLTV source."""

import argparse
import json
import os
import re
import urllib.request
from pathlib import Path

INJECTOR_ID = "f5a34f7b-2e8a-4e6a-a722-3a216a81b374"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--seerr-settings", type=Path, required=True)
    parser.add_argument("--guide-path", default="/config/config/media-stack-uk-guide.xml")
    args = parser.parse_args()
    key = json.loads(args.seerr_settings.read_text())["jellyfin"]["apiKey"]
    root = Path(__file__).resolve().parents[1]

    def api(path, payload=None):
        request = urllib.request.Request(
            args.url.rstrip("/") + path,
            headers={"Authorization": "MediaBrowser Token=" + json.dumps(key), "Content-Type": "application/json"},
            data=json.dumps(payload).encode() if payload is not None else None,
        )
        with urllib.request.urlopen(request, timeout=90) as response:
            body = response.read()
            return json.loads(body) if body else None

    config = api("/Plugins/" + INJECTOR_ID + "/Configuration")
    entries = [s for s in config.get("CustomJavaScripts", []) if s.get("Name") != "Media Stack TV Guide"]
    entries.append({"Name": "Media Stack TV Guide", "Script": (root / "integrations/jellyfin/guide.js").read_text(),
                    "Enabled": True, "RequiresAuthentication": True, "Module": False, "Src": ""})
    config["CustomJavaScripts"] = entries
    api("/Plugins/" + INJECTOR_ID + "/Configuration", config)

    branding = api("/Branding/Configuration")
    css = branding.get("CustomCss") or ""
    css = re.sub(r"/\* media-stack-tv:start \*/.*?/\* media-stack-tv:end \*/", "", css, flags=re.S).rstrip()
    branding["CustomCss"] = css + "\n/* media-stack-tv:start */\n" + (root / "integrations/jellyfin/guide.css").read_text() + "\n/* media-stack-tv:end */\n"
    api("/System/Configuration/Branding", branding)

    live = api("/System/Configuration/livetv")
    provider = next(p for p in live["ListingProviders"] if p.get("Type") == "xmltv" and ("dispatcharr" in p.get("Path", "") or p.get("Path") == args.guide_path))
    uk = next(t for t in live["TunerHosts"] if t.get("Url", "").endswith("/m3u/UK"))
    provider.update(Path=args.guide_path, EnableAllTuners=False, EnabledTuners=[uk["Id"]])
    api("/LiveTv/ListingProviders", provider)
    print("Configured guide-first web navigation, compact styling and real UK listings; existing tuner IDs retained.")


if __name__ == "__main__":
    os.umask(0o077)
    main()
