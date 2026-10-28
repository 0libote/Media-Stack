# Media Stack

A control panel for your own Jellyfin and ARR stack. Connect the apps, choose where files belong, and see what’s running from one place.

Media Stack runs on a Linux server or NAS with Docker Compose. It includes Jellyfin, Seerr, Radarr, Sonarr, Prowlarr, and Dispatcharr for live TV. Optional qBittorrent downloads can use your normal connection or Gluetun.

## What the panel does

- **Overview:** live service status, Jellyfin movie/show/episode counts, active streams, download speeds and progress, free storage, and app health warnings.
- **Connections:** verify and save app credentials. Connect the installed ARR apps and Seerr using local API keys without copying them through the browser.
- **Storage:** browse the shared data folder, choose movie/TV locations, and check write access and hardlinks.
- **Setup:** review and apply folder creation, Jellyfin libraries, ARR root folders, qBittorrent categories and download clients, Prowlarr sync, and Seerr connections with explicit quality profiles.

Existing connections and libraries are preserved. Setup adds missing settings, tests new app connections before saving, and reports partial failures. Retrying detects settings that already exist. It does not move media, change disk ownership, or rewrite existing app integrations.

![Storage management in Media Stack](docs/images/storage.png)

_Storage screen from an isolated test install._

## Install

You need Linux, Python 3.9+ for the setup script, Git, and [Docker Engine with Compose v2.24.4+](https://docs.docker.com/engine/install/). The control panel’s Python runtime is included in its container. Run setup as the normal user who will own the media files, with permission to use Docker.

```bash
git clone https://github.com/0libote/Media-Stack.git
cd Media-Stack
python3 setup.py
docker compose config --quiet
docker compose up -d --build
```

Setup asks for a storage folder, your server’s LAN IPv4 address, timezone, and an optional provider WireGuard file. Use a dedicated storage folder that your user can write to. The default address, `127.0.0.1`, allows access from the server itself; enter its LAN address to use other devices at home.

Open **http://YOUR-SERVER-IP:8088** and choose your administrator username and password on the first-start screen. This account controls the panel; the other apps keep their own accounts.

For a server using a separate disk:

```bash
python3 setup.py --data-dir /srv/media-stack --bind-address 192.168.1.50 --timezone Europe/London
```

For local defaults without prompts, use `python3 setup.py --non-interactive`. Setup preserves an existing `.env`; edit that file directly to change an installed stack.

## First time through

1. Open Jellyfin and Seerr from the panel. Complete their own account setup and sign Seerr into Jellyfin using `http://jellyfin:8096` as the internal address. Create a Movies library at `/data/media/movies` and a Shows library at `/data/media/tv` in Jellyfin. In Seerr, sync and enable at least one of those libraries to finish its wizard. You can leave its ARR connections for the panel.
2. In **Connections**, choose **Connect local apps**. Add a Jellyfin API key from Dashboard → API Keys. If downloads are enabled, add qBittorrent’s permanent Web UI login. Use the default internal service addresses for this Compose stack.
3. In **Storage**, check the movie and TV locations. Saving preferences does not move files or change the apps; the next step applies the new locations.
4. In **Setup**, choose the tasks, review each change, then apply. Select your Radarr and Sonarr quality profiles if connecting Seerr.
5. Add your own indexers in Prowlarr. Try one request for media you’re allowed to download and check it reaches Jellyfin. Existing media can be watched without enabling downloads.

The [manual setup guide](portal/guide.html), also linked in the panel, walks through the individual apps. [Panel behavior and supported APIs](docs/control-panel.md) explains the managed settings and remaining manual steps.

## Shared storage

Every app sees your dedicated data folder at `/data`. Jellyfin’s mount is read-only. Consistent paths prevent the common “download finished but import failed” problem and allow hardlinks on a compatible filesystem.

```text
Your data folder/
├── media/
│   ├── movies/          ← Radarr and Jellyfin
│   └── tv/              ← Sonarr and Jellyfin
└── torrents/
    ├── movies/          ← qBittorrent movie category
    ├── tv/              ← qBittorrent TV category
    └── incomplete/
```

You can choose other library subfolders inside `/data` in the panel. Changing a library location adds a new root/library entry where possible; it does not relocate existing files or change the paths of movies and series already managed by the apps. Jellyfin name conflicts and download category conflicts are shown for review in the native app.

Keep this data folder dedicated to media and downloads. The library tools and panel can access everything under it. To use a different host disk, change `DATA_DIR` in `.env` and recreate the containers; the panel cannot mount host disks.

## Optional downloads

Enable normal downloads with `python3 setup.py --downloads`, or supply `--vpn-config /path/to/provider.conf` for VPN routing. Existing installs can switch with `python3 ops/vpn.py off` or `python3 ops/vpn.py on`. The selected mode persists; VPN-off downloads use the normal connection. See [downloads and VPN modes](docs/downloads.md).

With the recovery timer, set `VPN_STOP_ACTION=direct` to continue normal downloads automatically when you stop Gluetun. The default is to pause VPN downloads. The rest of the stack stays available in either case. Only qBittorrent uses the VPN; TV, search, requests and playback remain independent. A working download API does not establish which public route is in use.

## Live TV

Open Dispatcharr on port **9191**, add your channel source and XMLTV guide, and connect its M3U/guide outputs to Jellyfin. Manage channel order, guide matching and recordings in Dispatcharr. The panel provides its status and an app link. [Live TV setup](docs/live-tv.md) explains source requirements and storage. A full UK lineup requires working streams or a tuner; Dispatcharr does not include channels or repair aerial reception.

## Keep it running

Run commands from this repository so Compose loads `.env`.

For an existing host, see [adopting a stack and automatic recovery](docs/maintenance.md#adopt-an-existing-stack). The optional disk-checked recovery timer restores services after boot and repairs VPN network dependencies; pause it before maintenance.

On ZimaOS, [register the complete application](docs/maintenance.md#zimaos-dashboard-controls) to keep its dashboard tile, Compose/settings and container controls together.

```bash
docker compose ps
docker compose logs --tail=100 portal
docker compose stop
docker compose up -d
```

Before updating, [back up the settings and media](docs/maintenance.md). Upstream app images follow stable channels and can change between installs. The panel’s Python dependencies are pinned with hashes.

```bash
git pull
docker compose pull --ignore-buildable
docker compose up -d --build
```

Use a trusted home network and finish the apps’ account setup before sharing their addresses. For an HTTPS reverse proxy, see [maintenance](docs/maintenance.md). Windows/macOS Docker Desktop, automatic disk migration, and GPU setup are outside this install flow. Hardware acceleration depends on the host; follow [Jellyfin’s guide](https://jellyfin.org/docs/general/post-install/transcoding/hardware-acceleration/).

## Ports

| Service                   | Port |
| ------------------------- | ---- |
| Media Stack control panel | 8088 |
| Jellyfin                  | 8096 |
| Seerr                     | 5055 |
| Radarr                    | 7878 |
| Sonarr                    | 8989 |
| Prowlarr                  | 9696 |
| Dispatcharr               | 9191 |
| qBittorrent, when enabled | 8080 |

## Development

The backend is Python/Flask, served by Gunicorn. The interface uses HTML, CSS, and browser JavaScript with bundled fonts; there is no frontend build step. See [development and validation](docs/development.md).

Project files use the [MIT license](LICENSE). Upstream apps and the bundled IBM Plex fonts retain their own licenses. Contributions should keep the install understandable and preserve users’ existing settings and files.
