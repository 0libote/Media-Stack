# Maintenance and troubleshooting

## Administrator access

The panel has one administrator account. Its hashed password, saved app credentials, preferred locations, and recent events live in `config/portal/settings.json`. The file is private to the owning user (`0600`). Manual API keys and qBittorrent credentials must be readable by the backend, so they are stored in plaintext on disk; keep the host and backups private.

On first startup, open the panel and choose an administrator username and password. Other apps retain their own accounts and permissions. Upgrading an existing password-only panel keeps its password and assigns the username `admin`.

To recover access, stop the panel, reset its administrator login, and restart it:

```bash
docker compose stop portal
docker compose run --rm --no-deps portal python -m control reset-admin
docker compose up -d portal
```

The reset keeps saved connections and locations, invalidates old panel sessions, and returns the panel to its first-start username/password screen. Do not run it against a live panel process; that process holds its settings in memory.

## Network access and HTTPS

Keep the stack on a trusted home network. Finish the apps’ account setup before sharing their addresses. The panel login protects its own control functions; it does not add authentication in front of the other apps.

Set `BIND_ADDRESS` to the server’s LAN IPv4 address to use other home devices. `127.0.0.1` is local access only; `0.0.0.0` listens on all IPv4 interfaces. Do not forward these ports on your router. Docker’s published ports need firewall rules that account for Docker networking.

For a trusted HTTPS reverse proxy that preserves `Host` and sets `X-Forwarded-Proto`, put these in `.env`:

```dotenv
PANEL_COOKIE_SECURE=1
PANEL_TRUST_PROXY=1
```

Then recreate the panel. Trust-proxy mode accepts one proxy’s forwarded protocol, not its host or client IP. Keep the backend reachable only through that trusted proxy. With secure cookies enabled, direct plain-HTTP sign-in will not work. Use each app’s **Browser address** override in Connections for its own HTTPS URL; proxying the panel alone does not proxy the rest of the stack.

CSRF protection, SameSite/HttpOnly cookies, login attempt limits, and response security headers are enabled. They do not encrypt plain HTTP traffic; use a trusted LAN or HTTPS for credentials.

## Change ports and disk mounts

To change an app’s host port, edit its Compose mapping and set its browser-address override in the panel. Internal container addresses can stay the same. A qBittorrent Web UI port change also needs matching `WEBUI_PORT`, Gluetun’s `FIREWALL_INPUT_PORTS`, and both sides of its published mapping. Test and save the changed internal address before linking new clients.

To use another data disk, stop the stack, update `DATA_DIR` in `.env`, prepare the expected folders and ownership on that disk, and recreate the containers. Move/copy your media separately if needed. The panel only manages paths within its current `/data` mount and never performs disk migration.

Changing preferred locations adds new root/library entries where possible. Existing movies/series keep their current paths, and existing integrations keep their custom settings. See [panel behavior](control-panel.md) before changing an established library.

## Update

```bash
git pull
docker compose pull --ignore-buildable
docker compose up -d --build
```

The panel is built locally, so rebuild it after code or dependency changes. Other app images follow upstream stable channels. Take a backup before an upgrade that could migrate application databases.

If you installed the original static-portal starter, keep `.env` and your current app configurations, create `config/portal` as your normal user, then rebuild the portal:

```bash
mkdir -p config/portal
docker compose up -d --build portal
```

The control panel starts unlinked; connect the apps to grant it access. This repository does not import an unrelated existing Docker project or change its mounts automatically.

## Adopt an existing stack

Before replacing containers, stop the media apps and archive their complete configuration folders, Compose definitions, container inspection output, and any named or anonymous configuration/cache volumes. Verify the archives and keep a second copy on another machine. Record library paths, torrent resume files, database counts, image IDs, ownership, ports, and integration addresses. Keep media files in place.

Use a private, Git-ignored `compose.host.yaml` to override the project for an existing host. Set `COMPOSE_FILE=compose.yaml:compose.host.yaml` in `.env`. This file can pin the installed images and mount existing AppData folders instead of creating empty configurations. Compose 2.24.4+ supports `volumes: !override [...]` to replace inherited mounts, including Seerr's named volume. Mount the existing media disk at `/data` and also at its original container path, such as `/media`, when saved library/download paths use that path. Audit uses of any previous `/data` mount before replacing it. Do not change media ownership or relocate files as part of adopting the containers.

Keep provider credentials in a private file under `secrets/`, referenced with `env_file`. The optional VPN file is a WireGuard example; an existing OpenVPN provider needs its own Gluetun override. In VPN mode, keep qBittorrent on `network_mode: service:gluetun` with a healthy dependency and `restart: true`. Never copy a resolved Docker container ID into the Compose source. Bind qBittorrent to the VPN interface in its own Advanced settings as well.

Stop and disable the old deployment before starting the new project on its ports. Preserve the stopped originals with `restart=no` and retire their old manager definitions outside its watched app folder. Never run both sets against the same databases. On the project's shared network, use service names for internal integrations (`jellyfin`, `seerr`, `radarr`, `sonarr`, `prowlarr`, and `qbittorrent:8080`); keep browser addresses on the server's LAN address.

After adoption, verify app authentication, database integrity and counts, torrent count/paths, library availability, a real media stream, cold startup, and VPN recovery. Configure panel connections while its process is stopped if importing settings directly. Leave a new panel's administrator claim for its owner; other apps keep their existing accounts.

## ZimaOS dashboard controls

After deploying this project on ZimaOS, run `sudo python3 ops/zimaos.py` from the checkout. This registers one **Media Stack** application, opening the panel on port 8088 and exposing the complete active stack in ZimaOS's Compose/settings and container controls. It adopts the existing Compose project rather than launching another copy. Registration validates the configuration and preserves the original `.env` in private `config/pre-zimaos.env`.

The active Compose file then lives at `/var/lib/casaos/apps/media-stack/docker-compose.yml`; `.env` points `COMPOSE_FILE` there. ZimaOS edits and command-line recovery use that same file. Keep it private and include the app directory in backups. `ZIMAOS_SOURCE_COMPOSE_FILE` retains the repository's original file chain as the routing template. The VPN mode command changes the torrent network settings and panel VPN status while retaining other dashboard edits; the saved Gluetun service is retained privately in `config/zima-gluetun.json` while disabled. Gluetun appears in the active app's service list when VPN mode is enabled.

The ZimaOS app directory requires a regular `.env` file; symlinks are rejected by its installed-app API. This file contains comments because the app's service settings are already resolved in its Compose definition. The checkout's separate `.env` retains routing and recovery controls; no duplicate environment file needs synchronizing.

Disabling VPN mode removes its stopped Gluetun container while retaining its saved service configuration and data. This prevents ZimaOS Start from starting that orphan and competing with direct downloads for port 8080. Enabling VPN mode recreates Gluetun from the saved settings.

After registration, edit running service settings in ZimaOS or its active Compose file. Changes to repository templates or `.env` interpolation values do not automatically rewrite the resolved app definition; apply upgrades to that active definition deliberately. Use `ops/vpn.py on` and `off` for routing changes. Reverting registration requires stopping the recovery job, restoring `config/pre-zimaos.env` as `.env`, and moving the ZimaOS app definition out of its watched app directory; keep the running project and its app data intact.

## Automatic startup and recovery

The Compose files include health checks and a 60-second shutdown grace period. `depends_on` orders Compose operations, but it does not provide full recovery after a Docker daemon restart. The optional `ops/reconcile.py` job brings this project up without pulling images or building, restarts unhealthy apps, and recreates qBittorrent if its network namespace differs from Gluetun's. Its timer runs 90 seconds after boot and 60 seconds after each completed check.

For a removable media disk, configure both `MEDIA_STACK_MOUNT` and `MEDIA_STACK_UUID` in `/etc/media-stack.conf`. Find the UUID with `findmnt -n -o UUID --target /your/media/mount`. The job checks the mounted disk's identity before starting apps. If it is absent or different, the job stops the stack and retries at the next timer tick. For this guarded deployment, override **media-facing services'** restart policies to `on-failure`: Docker handles process crashes, while the job owns boot/daemon startup so apps do not scan an empty mountpoint first. Gluetun only mounts internal configuration and can keep `unless-stopped`; the recovery job respects a stopped Gluetun and restores the other apps independently. Set `VPN_STOP_ACTION=direct` to switch downloads to the normal connection after a verified Docker stop event, or keep the default `pause`. Use `python3 ops/vpn.py on` to resume its downloads or `off` for normal routing. The regular Compose defaults remain `unless-stopped` for installations without this host job.

The example units use `/DATA/Projects/Media-Stack`. Adjust both paths in the service file for another checkout, then install them as root:

```bash
cp ops/media-stack-reconcile.* /etc/systemd/system/
systemctl daemon-reload
systemctl start media-stack-reconcile.service
systemctl enable --now media-stack-reconcile.timer
systemctl list-timers media-stack-reconcile.timer
journalctl -u media-stack-reconcile.service -n 80
```

The timer recovers individually stopped services. A deliberate Stop of the complete stack is respected when Docker retains its stop event; recovery after a Docker restart still brings services back. For maintenance or upgrades, stop the timer **and the active job** first:

```bash
systemctl stop media-stack-reconcile.timer media-stack-reconcile.service
docker compose stop
# Back up, update, or repair the installation here.
systemctl start media-stack-reconcile.service
systemctl start media-stack-reconcile.timer
```

Keep this checkout, `.env`, its private overrides, and secrets available on the server's internal disk. Updates to `latest` tags are separate from recovery; the recovery job never downloads new images.

## Backups

State is stored in:

- `.env`, `config/`, and optional `secrets/` in the repo. This includes the panel’s credentials, ARR/Jellyfin databases, cache, and VPN keys.
- The `media-stack_seerr-config` named volume. If you changed the Compose project name, find the actual volume name with `docker volume ls`.
- The `media-stack_dispatcharr-data` named volume, containing Dispatcharr settings and its database.
- Your chosen data folder, containing media, downloads, and Dispatcharr recordings.

An adopted installation may use existing AppData bind mounts instead of these defaults. Check `docker compose config` and `docker inspect` privately, and back up every actual configuration source. Include `compose.host.yaml`, its referenced secret files, `/etc/media-stack.conf`, and installed recovery units. Do not publish rendered configuration or container inspection output: they can contain credentials.

For a registered ZimaOS deployment, also archive `/var/lib/casaos/apps/media-stack/` and restore it before starting Compose. The project's `.env` references its active definition there; `config/pre-zimaos.env` is the fallback for restoring the original repository file chain.

Stop the stack before copying databases:

```bash
# If using recovery, stop its timer and job first (see above).
docker compose stop
mkdir -p backups
chmod 700 backups
tar -czf backups/local-config.tar.gz .env config
# Include secrets/ separately when downloads are enabled.
docker run --rm --user 0:0 \
  --mount type=volume,src=media-stack_seerr-config,dst=/source,readonly \
  --mount type=bind,src="$PWD/backups",dst=/backup \
  alpine:3.22 tar -czf /backup/seerr-config.tar.gz -C /source .
docker run --rm --user 0:0 \
  --mount type=volume,src=media-stack_dispatcharr-data,dst=/source,readonly \
  --mount type=bind,src="$PWD/backups",dst=/backup \
  alpine:3.22 tar -czf /backup/dispatcharr-data.tar.gz -C /source .
docker compose up -d
# Restart the recovery timer after maintenance, if installed.
```

Some app files are root-owned; elevated permissions may be needed to copy them. Back up the data folder separately and encrypt backups containing credentials. `backups/` is excluded from Git.

To restore, stop the target stack and restore `.env`, `config/`, and `secrets/` into a checkout. Adjust `DATA_DIR` and `BIND_ADDRESS` for the target host. Restore media separately. Create the Seerr volume with `docker volume create media-stack_seerr-config`, then extract its archive into that volume using the same temporary Alpine container with a writable `/source` mount. Preserve numeric ownership; if changing `PUID`/`PGID`, adjust ownership of the affected folders accordingly.

`docker compose down` keeps the files and named volumes. **`docker compose down -v` deletes Seerr’s and Dispatcharr’s named volumes.** Deleting `config/portal` removes the panel’s credentials and saved connections; deleting other app config folders loses their databases and settings.

## Common problems

**Panel will not start:** check `docker compose logs portal`. Confirm `config/portal` and the data directory are writable by the UID/GID in `.env`. Rebuild with `docker compose build portal` after updating source code. Do not share private settings files or unredacted logs.

**Administrator login is missing:** create a username and password on the first-start screen. An upgraded password-only panel uses username `admin` with its existing password. Use the recovery steps above if access was lost.

**Docker permission denied:** follow Docker’s Linux post-install steps or use appropriate privileges for Compose. Run `setup.py` as your normal user so its UID/GID match the media owner.

**A local app key cannot be read:** complete that app’s first-time setup, confirm its config mount and permissions, or enter the API key manually in Connections. For a custom address, local-key mode is intentionally unavailable.

**An app is connected but stats are missing:** inspect the reported error. API permissions or versions may allow system status but block another endpoint. The panel shows unknown metrics rather than substituting zero.

**Location is rejected:** use a directory inside `/data`, separate movie/TV folders, and keep libraries outside `/data/torrents`. Symlinks escaping the mount are rejected. A new host disk requires a Compose mount change.

**Import check fails:** verify write access and filesystem boundaries. Network shares can have different permissions or lack hardlinks. The check runs as the panel’s user; custom external app installations may use different users.

**An existing connection is kept but broken:** edit that connection in the native app. The panel does not overwrite existing credentials, categories, or defaults. Remove only that specific integration there if you want the panel to recreate it.

**A review expired or a request timed out:** reload the current state and review again. Completed changes are kept and detected on retry. Reviews expire after five minutes, after connection/location changes, or after a panel restart.

**A port is already allocated:** resolve conflicts or change the relevant mapping. Don’t start this Compose stack alongside an unrelated instance using the same ports without adjusting them.

**Gluetun is unhealthy:** verify the WireGuard configuration, `/dev/net/tun`, provider access, and endpoint reachability. See [downloads](downloads.md). Do not disable its firewall to solve connectivity.

**Apps stay stopped or unhealthy after a restart:** if the recovery timer is installed, inspect `journalctl -u media-stack-reconcile.service -n 80`. Confirm the expected media disk is mounted and its UUID matches `/etc/media-stack.conf`. A failed disk check deliberately keeps apps stopped. Replacing Gluetun requires qBittorrent to join its new network namespace; run `systemctl start media-stack-reconcile.service` to reconcile the project.

**Jellyfin rejects a valid API key:** rebuild an older panel. It now sends `Authorization: MediaBrowser Token="..."`; Jellyfin 12 disables the older token headers by default. See the [Jellyfin 12 release notes](https://jellyfin.org/posts/jellyfin-release-12.0/). Existing API keys can be kept.

**qBittorrent login fails:** find the temporary password in `docker compose logs qbittorrent`, then set a permanent one. The ARR/panel host is `qbittorrent`, port `8080`. A connected qBittorrent API is not a VPN-route test.

Newer qBittorrent versions return HTTP 204 with no body for a successful login. The panel accepts that and the older `Ok.` response, then checks an authenticated endpoint using the session cookie. Rebuild the panel if an older copy rejects working credentials.

**Downloads finish but do not import:** check the movie/TV categories and save paths, root folders, completed download handling, and UID/GID. All apps must see the same `/data` paths. Existing custom integrations may still use their previous paths/categories.
