#!/usr/bin/env python3
"""Prepare a Media Stack install without starting or changing containers."""

import argparse
import base64
import binascii
import configparser
import ipaddress
import os
from pathlib import Path
import shutil
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parent


def wireguard_config(path):
    text = path.read_text()
    config = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        config.read_string(text)
    except configparser.Error as error:
        raise ValueError(
            "WireGuard file must contain one [Interface] and one [Peer] section."
        ) from error
    if set(config.sections()) != {"Interface", "Peer"}:
        raise ValueError(
            "WireGuard file must contain one [Interface] and one [Peer] section."
        )
    for section, key in (
        ("Interface", "PrivateKey"),
        ("Interface", "Address"),
        ("Peer", "PublicKey"),
        ("Peer", "Endpoint"),
        ("Peer", "AllowedIPs"),
    ):
        if not config.get(section, key, fallback="").strip():
            raise ValueError(f"WireGuard file is missing [{section}] {key}.")
    for section, key in (
        ("Interface", "PrivateKey"),
        ("Peer", "PublicKey"),
        ("Peer", "PresharedKey"),
    ):
        value = config.get(section, key, fallback="").strip()
        if key == "PresharedKey" and not value:
            continue
        try:
            valid = len(base64.b64decode(value, validate=True)) == 32
        except (binascii.Error, ValueError):
            valid = False
        if not valid:
            raise ValueError(
                f"WireGuard [{section}] {key} must be a base64-encoded 32-byte key."
            )
    endpoint = config["Peer"]["Endpoint"].rsplit(":", 1)
    if len(endpoint) != 2:
        raise ValueError("WireGuard Endpoint must be an IPv4 address and port.")
    ipaddress.IPv4Address(endpoint[0])
    if not 1 <= int(endpoint[1]) <= 65535:
        raise ValueError("WireGuard endpoint port must be between 1 and 65535.")
    # Gluetun custom WireGuard endpoints currently require an IP, not a hostname.
    return text


def prepare(root, data_dir, bind_address, timezone, vpn_config=None, downloads=False):
    if (root / ".env").exists():
        raise ValueError(
            ".env already exists; edit it directly. Existing settings were kept."
        )
    if os.getuid() == 0:
        raise ValueError(
            "Run setup as the user who will own the media files, without sudo."
        )
    ipaddress.IPv4Address(bind_address)
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ValueError(
            "Use an IANA timezone such as Etc/UTC or Europe/London."
        ) from error
    data = Path(data_dir).expanduser()
    data = (root / data).resolve() if not data.is_absolute() else data.resolve()
    if any(char in str(data) for char in "\n\r'\\$"):
        raise ValueError(
            "The data path cannot contain newlines, quotes, backslashes, or dollar signs."
        )
    reserved = (
        "config",
        "secrets",
        "portal",
        "control",
        "ops",
        "docs",
        "tests",
        ".git",
        ".github",
        "backups",
        ".venv",
    )
    if (
        data == root
        or data in root.parents
        or any(data.is_relative_to(root / path) for path in reserved)
    ):
        raise ValueError(
            "Choose a dedicated data directory outside the repo's application and source folders."
        )
    vpn_text = wireguard_config(Path(vpn_config).expanduser()) if vpn_config else None
    secret = root / "secrets" / "wg0.conf"
    if vpn_text and secret.exists():
        raise ValueError(
            "secrets/wg0.conf already exists; existing VPN settings were kept."
        )
    directories = [
        root / "config" / app
        for app in (
            "portal",
            "jellyfin",
            "jellyfin-cache",
            "radarr",
            "sonarr",
            "prowlarr",
        )
    ]
    directories += [
        data / path
        for path in (
            "media/movies",
            "media/tv",
            "torrents/movies",
            "torrents/tv",
            "torrents/incomplete",
            "recordings",
        )
    ]
    if downloads or vpn_text:
        directories += [root / "config/qbittorrent"]
    if vpn_text:
        directories += [root / "config/gluetun"]
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
        if not os.access(directory, os.W_OK | os.X_OK):
            raise ValueError(f"Your user needs write access to {directory}.")
    if vpn_text:
        secret.parent.mkdir(mode=0o700, exist_ok=True)
        with open(
            secret, "x", opener=lambda path, flags: os.open(path, flags, 0o600)
        ) as handle:
            handle.write(vpn_text)
    compose = "compose.yaml"
    if downloads or vpn_text:
        compose += ":compose.downloads.direct.yaml"
    if vpn_text:
        compose += ":compose.vpn.yaml"
    settings = (
        f"COMPOSE_FILE={compose}\nPUID={os.getuid()}\nPGID={os.getgid()}\n"
        f"TZ={timezone}\nDATA_DIR='{data}'\nBIND_ADDRESS={bind_address}\n"
        f"DOWNLOADS_ENABLED={'true' if downloads or vpn_text else 'false'}\n"
        f"VPN_ENABLED={'true' if vpn_text else 'false'}\n"
        "VPN_STOP_ACTION=pause\n"
    )
    with open(
        root / ".env", "x", opener=lambda path, flags: os.open(path, flags, 0o600)
    ) as handle:
        handle.write(settings)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir", help="Dedicated media/download folder (default: ./data)"
    )
    parser.add_argument(
        "--bind-address", help="Server LAN IPv4 address (default: 127.0.0.1)"
    )
    parser.add_argument("--timezone", help="IANA timezone (default: Etc/UTC)")
    parser.add_argument(
        "--vpn-config", help="Provider WireGuard file; enables VPN downloads"
    )
    parser.add_argument(
        "--downloads", action="store_true", help="Enable downloads without a VPN"
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Use defaults for unanswered settings",
    )
    args = parser.parse_args()
    interactive = sys.stdin.isatty() and not args.non_interactive

    def answer(value, prompt, default):
        return (
            value
            if value is not None
            else (
                (input(f"{prompt} [{default}]: ").strip() or default)
                if interactive
                else default
            )
        )

    try:
        data_dir = answer(args.data_dir, "Media and downloads folder", "./data")
        bind = answer(
            args.bind_address,
            "Server LAN IPv4 address (127.0.0.1 for this machine only)",
            "127.0.0.1",
        )
        timezone = answer(args.timezone, "Timezone", "Etc/UTC")
        vpn = answer(args.vpn_config, "WireGuard file (leave empty for no VPN)", "")
        downloads = args.downloads or bool(vpn)
        if interactive and not downloads:
            downloads = (
                answer(None, "Enable downloads without a VPN? y/n", "n").lower() == "y"
            )
        prepare(ROOT, data_dir, bind, timezone, vpn or None, downloads=downloads)
    except (ValueError, OSError, configparser.Error) as error:
        parser.exit(1, f"Setup stopped: {error}\n")
    if not shutil.which("docker"):
        print(
            "Settings saved. Install Docker Engine and Compose before starting the stack."
        )
    host = "localhost" if bind in ("127.0.0.1", "0.0.0.0") else bind
    print(
        f"\nReady. Run from {ROOT}:\n  docker compose config --quiet\n  docker compose up -d\n\nOpen http://{host}:8088 and follow First-time setup."
    )
    print(
        "On first use, choose your administrator username and password in the browser."
    )
    if bind == "0.0.0.0":
        print(
            "Listening on all host interfaces; use your server's LAN address from another device."
        )


if __name__ == "__main__":
    main()
