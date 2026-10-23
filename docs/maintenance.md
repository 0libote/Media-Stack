# Maintenance and troubleshooting

## Administrator access

The panel has one administrator account. Its hashed password, saved app credentials, preferred locations, and recent events live in `config/portal/settings.json`. The file is private to the owning user (`0600`). Manual API keys and qBittorrent credentials must be readable by the backend, so they are stored in plaintext on disk; keep the host and backups private.

First startup creates `config/portal/setup-code`. Read it on the server and use it to create your password in the browser. The code is removed after use. Other apps retain their own accounts and permissions.

To recover access, stop the panel, reset its administrator login, and restart it:

```bash
docker compose stop portal
docker compose run --rm --no-deps portal python -m control reset-admin
docker compose up -d portal
cat config/portal/setup-code
```

The reset keeps saved connections and locations, invalidates old panel sessions, and issues a new setup code. Do not run it against a live panel process; that process holds its settings in memory.

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
cat config/portal/setup-code
```

The control panel starts unlinked; connect the apps to grant it access. This repository does not import an unrelated existing Docker project or change its mounts automatically.

## Backups

State is stored in:

- `.env`, `config/`, and optional `secrets/` in the repo. This includes the panel’s credentials, ARR/Jellyfin databases, cache, and VPN keys.
- The `media-stack_seerr-config` named volume. If you changed the Compose project name, find the actual volume name with `docker volume ls`.
- Your chosen data folder, containing media and downloads.

Stop the stack before copying databases:

```bash
docker compose stop
mkdir -p backups
chmod 700 backups
tar -czf backups/local-config.tar.gz .env config
# Include secrets/ separately when downloads are enabled.
docker run --rm --user 0:0 \
  --mount type=volume,src=media-stack_seerr-config,dst=/source,readonly \
  --mount type=bind,src="$PWD/backups",dst=/backup \
  alpine:3.22 tar -czf /backup/seerr-config.tar.gz -C /source .
docker compose up -d
```

Some app files are root-owned; elevated permissions may be needed to copy them. Back up the data folder separately and encrypt backups containing credentials. `backups/` is excluded from Git.

To restore, stop the target stack and restore `.env`, `config/`, and `secrets/` into a checkout. Adjust `DATA_DIR` and `BIND_ADDRESS` for the target host. Restore media separately. Create the Seerr volume with `docker volume create media-stack_seerr-config`, then extract its archive into that volume using the same temporary Alpine container with a writable `/source` mount. Preserve numeric ownership; if changing `PUID`/`PGID`, adjust ownership of the affected folders accordingly.

`docker compose down` keeps the files and named volumes. **`docker compose down -v` deletes Seerr’s named volume.** Deleting `config/portal` removes the panel’s credentials and saved connections; deleting other app config folders loses their databases and settings.

## Common problems

**Panel will not start:** check `docker compose logs portal`. Confirm `config/portal` and the data directory are writable by the UID/GID in `.env`. Rebuild with `docker compose build portal` after updating source code. Do not share private settings files or unredacted logs.

**Setup code is missing:** it only exists before the panel is claimed. Try signing in if the panel was already configured. For an unclaimed new panel, wait for startup and check its container logs. Use the recovery steps above if access was lost.

**Docker permission denied:** follow Docker’s Linux post-install steps or use appropriate privileges for Compose. Run `setup.py` as your normal user so its UID/GID match the media owner.

**A local app key cannot be read:** complete that app’s first-time setup, confirm its config mount and permissions, or enter the API key manually in Connections. For a custom address, local-key mode is intentionally unavailable.

**An app is connected but stats are missing:** inspect the reported error. API permissions or versions may allow system status but block another endpoint. The panel shows unknown metrics rather than substituting zero.

**Location is rejected:** use a directory inside `/data`, separate movie/TV folders, and keep libraries outside `/data/torrents`. Symlinks escaping the mount are rejected. A new host disk requires a Compose mount change.

**Import check fails:** verify write access and filesystem boundaries. Network shares can have different permissions or lack hardlinks. The check runs as the panel’s user; custom external app installations may use different users.

**An existing connection is kept but broken:** edit that connection in the native app. The panel does not overwrite existing credentials, categories, or defaults. Remove only that specific integration there if you want the panel to recreate it.

**A review expired or a request timed out:** reload the current state and review again. Completed changes are kept and detected on retry. Reviews expire after five minutes, after connection/location changes, or after a panel restart.

**A port is already allocated:** resolve conflicts or change the relevant mapping. Don’t start this Compose stack alongside an unrelated instance using the same ports without adjusting them.

**Gluetun is unhealthy:** verify the WireGuard configuration, `/dev/net/tun`, provider access, and endpoint reachability. See [downloads](downloads.md). Do not disable its firewall to solve connectivity.

**qBittorrent login fails:** find the temporary password in `docker compose logs qbittorrent`, then set a permanent one. The ARR/panel host is `gluetun`, port `8080`. A connected qBittorrent API is not a VPN-route test.

**Downloads finish but do not import:** check the movie/TV categories and save paths, root folders, completed download handling, and UID/GID. All apps must see the same `/data` paths. Existing custom integrations may still use their previous paths/categories.
