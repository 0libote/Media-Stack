# Media Stack

Your own movie and TV library, with a simple home page to bring it together.

Media Stack packages Jellyfin and the ARR apps into a Docker Compose project you can run on a Linux server or NAS. Start with media you already own. Add requests, library management, and VPN-protected downloads when you’re ready.

| App | What it does | Port |
| --- | --- | --- |
| Media Stack | Home page and first-time setup guide | 8088 |
| Jellyfin | Watch your movies and TV | 8096 |
| Seerr | Discover and request media | 5055 |
| Radarr | Organize movies | 7878 |
| Sonarr | Organize TV shows | 8989 |
| Prowlarr | Manage search indexers | 9696 |
| qBittorrent + Gluetun | Optional downloads through a VPN | 8080 |

## Get started

You need a Linux machine, Python 3.9+, Git, and [Docker Engine with Compose v2.20+](https://docs.docker.com/engine/install/). Run setup as your normal user, with permission to run Docker. Docker Desktop on Windows/macOS is outside this starter’s supported scope.

```bash
git clone https://github.com/0libote/Media-Stack.git
cd Media-Stack
python3 setup.py
docker compose config --quiet
docker compose up -d
```

Setup asks for a storage folder, your server’s LAN IPv4 address, timezone, and an optional WireGuard file. It creates folders and a local `.env`, and leaves existing settings alone. The default address, `127.0.0.1`, allows access from the server itself. Enter the server’s LAN address to use it from your TV, phone, or another computer. Do the account setup before giving others access.

Open **http://YOUR-SERVER-IP:8088** and follow **First-time setup**. Each app needs its own initial configuration; setup does not silently create accounts or copy API keys. The guide walks through the connections and paths.

For a local install with default settings:

```bash
python3 setup.py --non-interactive
```

For a server with a separate storage disk:

```bash
python3 setup.py --data-dir /srv/media-stack --bind-address 192.168.1.50 --timezone Europe/London
```

Your user must be able to write to the chosen folder. Setup never changes ownership of an existing library. UID/GID are taken from the user running setup.

## How files move

All library tools and the optional download client mount one shared data directory at `/data`. This keeps paths consistent and permits hardlinks when the storage filesystem supports them. Jellyfin gets read-only access to `media/`.

```text
Your data folder/
├── media/
│   ├── movies/
│   └── tv/
└── torrents/
    ├── movies/
    ├── tv/
    └── incomplete/
```

Put your existing files in the appropriate media folders, or use a dedicated existing data folder with this layout. Don’t point setup at an entire disk that also contains unrelated private files: Radarr, Sonarr, and qBittorrent can access everything under the data folder.

## Optional downloads

Provide a WireGuard configuration from your VPN provider during setup, or follow [the downloads guide](docs/downloads.md) to add it later. qBittorrent shares Gluetun’s network and waits for its VPN health check. There is no direct-network download mode in this starter.

Only qBittorrent uses the VPN. Indexer searches, requests, and playback use the host’s normal connection. Use services and media you have permission to access.

## Day-to-day use

Run commands from this repository so Compose loads your `.env`.

```bash
docker compose ps                 # See containers
docker compose logs --tail=100    # Diagnose problems; logs may contain private data
docker compose stop              # Stop without removing containers
docker compose up -d             # Start again
```

Before updating, [back up your configuration](docs/maintenance.md). Images follow their upstream stable channels, so pulls can include major changes; this is a starter, not a frozen release bundle.

```bash
docker compose pull
docker compose up -d
```

See [maintenance and troubleshooting](docs/maintenance.md) for backups, ports, permissions, VPN problems, and moving an install. Intel/AMD/NVIDIA acceleration is hardware-specific and deliberately left to [Jellyfin’s hardware guide](https://jellyfin.org/docs/general/post-install/transcoding/hardware-acceleration/).

## Project files

- `compose.yaml`: the home page, Jellyfin, Seerr, and ARR apps.
- `compose.downloads.yaml`: optional Gluetun and qBittorrent.
- `setup.py`: creates your local settings and folders without starting containers.
- `portal/`: static home page and guided app configuration. No build step or external assets.
- `.env.example`: reference settings. `.env`, app configuration, media, and VPN files are excluded from Git.

This repo contains deployment configuration and an original portal, not copies of the upstream applications. Project files use the [MIT license](LICENSE); each application retains its own license. Contributions should keep the default install easy to understand. Run `python3 -m unittest discover -s tests` and validate both Compose configurations before sending a change.

## Upstream documentation

[Jellyfin containers](https://jellyfin.org/docs/general/installation/container/) · [Seerr Docker setup](https://docs.seerr.dev/getting-started/docker/) · [LinuxServer images](https://docs.linuxserver.io/images/) · [Gluetun custom WireGuard](https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/custom.md)
