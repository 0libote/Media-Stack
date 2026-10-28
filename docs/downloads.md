# Downloads with or without a VPN

Downloads and VPN routing are separate choices. Jellyfin, Dispatcharr, Seerr and the ARR apps use their own network connections in either mode. Their startup does not depend on Gluetun.

## Normal internet connection

For a new install:

```bash
python3 setup.py --downloads
```

For an existing install, keep its settings and enable the direct downloads file in `.env`:

```dotenv
COMPOSE_FILE=compose.yaml:compose.downloads.direct.yaml
DOWNLOADS_ENABLED=true
VPN_ENABLED=false
```

Create `config/qbittorrent` as the media owner, then run `docker compose up -d`. Downloads use your normal public internet connection in this mode.

## Add VPN routing

Setup accepts a single-peer WireGuard configuration with an IPv4 endpoint:

```bash
python3 setup.py --vpn-config /path/to/provider.conf
```

This enables `compose.downloads.direct.yaml:compose.vpn.yaml`, saves a private copy in `secrets/wg0.conf`, and sets `VPN_ENABLED=true`. Existing `.env` files are preserved. To add a provider configuration later, create `secrets/` with mode `0700`, install `wg0.conf` with mode `0600`, and add `compose.vpn.yaml` after `compose.downloads.direct.yaml` in `COMPOSE_FILE`.

The host needs `/dev/net/tun` and `NET_ADMIN`. The starter uses Gluetun's [custom WireGuard provider](https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/custom.md). Other providers can use a private `compose.vpn.host.yaml`: override the provider/type explicitly, reference credentials under `secrets/`, and replace Gluetun's mounts when no WireGuard file is needed. Plain `env_file` values do not override the starter's explicit `VPN_TYPE` and `VPN_SERVICE_PROVIDER` values.

The legacy `compose.downloads.yaml` filename continues to mean **VPN-protected downloads**, so upgrading an older installation does not silently remove its VPN. New installations use the separate direct/VPN files. The mode command below also migrates that legacy filename when explicitly invoked.

## Switch an installed stack

From the project directory, run as the user with Docker/configuration access (use `sudo` on the adopted server):

```bash
python3 ops/vpn.py off  # Downloads use the normal internet connection.
python3 ops/vpn.py on   # Downloads wait for Gluetun and use its tunnel.
```

The command validates the selected configuration, stops qBittorrent cleanly, changes its network and interface binding, then starts it again. It keeps configuration, login credentials, categories, torrents and save paths. The selected mode is persisted in `.env`. Private host overrides are kept; `compose.vpn.host.yaml` is loaded only in VPN mode. A failed startup restores the previous mode. The mode command and recovery job share a lock, and the server's configured media-disk identity guard also applies to mode changes.

The internal qBittorrent address is **`http://qbittorrent:8080` in both modes**. Gluetun owns that DNS alias when routing through the VPN. Change older panel/ARR connections from `gluetun` to `qbittorrent` once when adopting the new layout. The browser address remains port 8080 on the server.

With the recovery timer installed, choose what stopping Gluetun means in `.env`:

```dotenv
VPN_STOP_ACTION=direct
```

`direct` continues downloads on the normal connection after the next recovery check (normally within about a minute). The job requires a Docker stop event for the exited container before changing routes; an unhealthy tunnel or an app crash does not silently remove VPN protection. The default `pause` keeps downloads paused instead. Playback, TV, requests and library management stay available in either case.

Automatic fallback persists direct mode in `.env`. Run `python3 ops/vpn.py on` to restore VPN routing. Starting Gluetun by itself does not reroute an already independent qBittorrent container. Without the recovery timer, use the explicit `on`/`off` commands.

When using the guarded recovery timer on a removable media disk, Gluetun can retain `restart: unless-stopped` because its state lives on the internal disk. Keep media-facing services on `on-failure` so the disk-checked job controls their boot startup. This also lets Docker distinguish a manually stopped Gluetun from one that should resume after reboot.

## Connect and verify

Read the temporary qBittorrent password privately from its logs and set a permanent password in its Web UI. Connect it in the panel, then review the download-client setup. Existing custom client settings are preserved.

Check the route after switching:

```bash
docker compose exec qbittorrent curl -fsS https://api.ipify.org
```

VPN mode should show the provider's exit IP and bind qBittorrent to `tun0`; direct mode clears that binding. Gluetun's firewall stays enabled. Test a controlled VPN interruption before relying on the setup. No provider port forwarding is configured by the starter.

To disable all downloads, stop qBittorrent (and Gluetun if enabled), remove their Compose files from `.env`, and set `DOWNLOADS_ENABLED=false`. Keep the configuration directories and secret files for later reuse.
