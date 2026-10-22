# Maintenance and troubleshooting

## Keep it on your home network

The portal is a set of links and instructions. It provides no authentication, proxying, or service health monitoring. Each app handles its own login. Finish those logins before sharing the server address.

Choose your server’s LAN IPv4 address for `BIND_ADDRESS` to make the apps available to other home devices. `127.0.0.1` is local access only; `0.0.0.0` listens on all IPv4 interfaces. Do not forward these ports on your router. Docker’s published ports need firewall rules that account for Docker networking; do not assume a host firewall alone blocks them.

Ports are fixed across the Compose files and portal. To change a port, edit both the mapping and corresponding `data-port` attributes in `portal/`. For qBittorrent, also update `WEBUI_PORT`, Gluetun’s `FIREWALL_INPUT_PORTS`, its mapping on both sides, and the download client settings in Radarr/Sonarr.

## Backups

An install has three kinds of state:

- `.env`, `config/`, and optional `secrets/` in this repo: settings, databases, cache, and VPN credentials.
- The Compose named volume `media-stack_seerr-config`: Seerr’s database and settings. If you changed the project name, inspect `docker volume ls` for the actual name.
- Your chosen data folder: media and downloads.

Stop the stack before copying databases:

```bash
docker compose stop
mkdir -p backups
chmod 700 backups
tar -czf backups/local-config.tar.gz .env config
# Include secrets/ separately if downloads are enabled. Keep backups private.
docker run --rm --user 0:0 \
  --mount type=volume,src=media-stack_seerr-config,dst=/source,readonly \
  --mount type=bind,src="$PWD/backups",dst=/backup \
  alpine:3.22 tar -czf /backup/seerr-config.tar.gz -C /source .
docker compose up -d
```

`config/` may have root-owned files; use elevated permissions to read them if required. Back up the data folder separately. Add `backups/` to your local exclusions if you keep it in the repo; it is ignored by this project. Encrypt backups that contain accounts, API keys, or VPN credentials.

For restore, stop the target stack and restore `.env`, `config/`, and `secrets/` to a checkout. Adjust `DATA_DIR` and `BIND_ADDRESS` for the new machine. Restore media to the data folder. Create the Seerr volume with `docker volume create media-stack_seerr-config`, then extract its archive into that volume using the same temporary Alpine container with a writable `/source` mount. Preserve numeric ownership during restore; update `PUID`/`PGID` only if you also adjust the corresponding file ownership. Start with `docker compose up -d`.

`docker compose down` removes containers and networks but keeps named volumes and bind-mounted files. **`docker compose down -v` deletes Seerr’s named volume.** Deleting `config/` loses the other apps’ settings. Keep backups before either action.

## Common problems

**Docker permission denied:** follow Docker’s Linux post-install steps or run Compose with appropriate privileges. Do not run `setup.py` as root; it takes your UID/GID for media permissions.

**Setup cannot create the data folder:** have the host administrator create a dedicated folder your user owns. Do not recursively change permissions on an existing disk. Check `id` against `PUID`/`PGID` in `.env`. Network shares may not support the ownership or hardlinks you expect.

**An app cannot write its configuration:** for Jellyfin, `config/jellyfin` and `config/jellyfin-cache` must be writable by the UID/GID in `.env`. The LinuxServer images initialize their own config folders. Seerr runs as the image’s node user and uses its own named volume, rather than a host UID override.

**A port is already allocated:** use a different host or change the ports as described above. On a machine that already runs these apps, do not bring up this starter until conflicts are resolved. This repo does not import, replace, or migrate an existing installation.

**Gluetun is unhealthy:** inspect `docker compose logs gluetun`, verify the WireGuard file and `/dev/net/tun`, check the provider account, and confirm the host can reach the endpoint. Do not share unredacted logs. See [the downloads guide](downloads.md).

**qBittorrent login fails:** the first password is in `docker compose logs qbittorrent`. Set a permanent one; otherwise it changes on restart. The host used by ARR apps is `gluetun`, port `8080`, not `localhost` or `qbittorrent`.

**Downloads finish but do not import:** check the `movies`/`tv` categories, save paths, media root folders, completed download handling, and permissions. The same `/data` path should appear in all apps. Hardlinks require media and downloads on the same filesystem; separate child mounts prevent them even under one directory.

**Service links point to the wrong place:** open the portal using the server address your device can reach. It builds links from that hostname. This starter uses plain HTTP on a trusted LAN; serving the portal through an HTTPS reverse proxy does not configure the other services for HTTPS.

## Validation for changes

```bash
python3 -m unittest discover -s tests
docker compose --env-file .env.example -f compose.yaml config --quiet
docker compose --env-file .env.example -f compose.yaml -f compose.downloads.yaml config --quiet
```

The automated checks cover setup and Compose structure. They do not prove playback, provider compatibility, hardlink support, or VPN outage behavior on a particular machine.
