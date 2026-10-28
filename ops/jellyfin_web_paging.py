"""Work around unbounded channel browsing in the installed Jellyfin 12 web build.

Only known bundles are changed. Original files are saved; newer builds are left
alone for review. Recovery reapplies this after a container replacement.
"""

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

PATCHES = [
    (
        "10398.ea89da93f96b286dd4f0.chunk.js",
        "c2b724f828cbc4aef4befc4710dd59591f8180f37d84615cb1cf6fa45807d518",
        "getLiveTvChannels({userId:f.Id,fields:[o.z.PrimaryImageAspectRatio],startIndex:u.StartIndex,isFavorite:h,",
        "getLiveTvChannels({userId:f.Id,fields:[o.z.PrimaryImageAspectRatio],startIndex:u.StartIndex,limit:(0,I.cm)().limit,isFavorite:h,",
    ),
    (
        "14553.6ddb0da23f2698557d33.chunk.js",
        "a613661f2a2bd541c694184c769ab168d7678ee677efcdae5e0eabf8d3acfe0d",
        "var h=500;H=h,O(),v.StartIndex=E,v.Limit=h,",
        "var h=100;H=h,O(),v.StartIndex=E,v.Limit=h,",
    ),
]


def patch_text(body, old, new):
    if new in body and old not in body:
        return body
    if body.count(old) != 1:
        raise ValueError("Expected exactly one pagination expression")
    return body.replace(old, new, 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", default="jellyfin")
    args = parser.parse_args()
    container = subprocess.check_output(
        ["docker", "inspect", "--format", "{{.Id}}", args.container], text=True
    ).strip()
    config = Path(__file__).resolve().parents[1] / "config"
    stamp = config / "jellyfin-web-paging.json"
    if stamp.exists() and json.loads(stamp.read_text()).get("container") == container:
        return
    backups = config / "jellyfin-web-originals"
    backups.mkdir(parents=True, exist_ok=True)
    applied = []
    with tempfile.TemporaryDirectory(prefix="jellyfin-web-paging-") as folder:
        for filename, digest, old, new in PATCHES:
            destination = "/jellyfin/jellyfin-web/" + filename
            local = Path(folder) / filename
            result = subprocess.run(
                ["docker", "cp", container + ":" + destination, str(local)],
                capture_output=True, text=True,
            )
            if result.returncode:
                print("Jellyfin web pagination: different build; review needed for", filename)
                continue
            body = local.read_text()
            if new in body and old not in body:
                applied.append(filename)
                continue
            if hashlib.sha256(local.read_bytes()).hexdigest() != digest:
                print("Jellyfin web pagination: unknown bundle; leaving unchanged:", filename)
                continue
            (backups / filename).write_bytes(local.read_bytes())
            local.write_text(patch_text(body, old, new))
            local.chmod(0o644)
            subprocess.run(["docker", "cp", str(local), container + ":" + destination], check=True)
            applied.append(filename)
            print("Jellyfin web pagination repaired:", filename)
    temporary = stamp.with_suffix(".tmp")
    temporary.write_text(json.dumps({"container": container, "applied": applied}) + "\n")
    temporary.replace(stamp)


if __name__ == "__main__":
    main()
