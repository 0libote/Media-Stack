"""Publish an atomic local XMLTV file for Jellyfin, without dummy programmes."""

import argparse
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", default="media-stack-dispatcharr-1")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = subprocess.run(
        ["docker", "exec", "-i", args.container, "python", "-"],
        input=Path(__file__).with_name("export_uk_guide.py").read_bytes(),
        stdout=subprocess.PIPE, check=True,
    )
    root = ET.fromstring(result.stdout)
    if not root.findall("channel") or not root.findall("programme"):
        raise SystemExit("The UK guide is empty; retaining the previous file.")
    temporary = args.output.with_suffix(".tmp")
    temporary.write_bytes(result.stdout)
    temporary.chmod(0o644)
    temporary.replace(args.output)
    print("Published UK guide:", len(root.findall("channel")), "channels;", len(root.findall("programme")), "real listings")


if __name__ == "__main__":
    main()
