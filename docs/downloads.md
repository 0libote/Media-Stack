# Add VPN-protected downloads

This starter accepts a **single-peer WireGuard configuration with an IPv4 endpoint** from your VPN provider. The config needs `[Interface]` with `PrivateKey` and `Address`, and `[Peer]` with `PublicKey`, `AllowedIPs`, and `Endpoint`. Download the file privately from your provider; do not paste it into an issue or commit it.

Gluetun’s [custom provider documentation](https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/custom.md) explains the supported fields. Its custom endpoint currently requires an IP address. Configurations with hostnames, multiple peers, IPv6-only endpoints, or provider login scripts need adaptation and are outside this setup flow.

## During first install

Give setup the file path when prompted, or run:

```bash
python3 setup.py --vpn-config /path/to/provider.conf
```

Setup copies it into ignored `secrets/wg0.conf` with private permissions and enables the downloads Compose file in `.env`. Your original file stays in place.

## After an install

Keep your existing `.env`. From the repo folder:

```bash
mkdir -p secrets config/gluetun config/qbittorrent
chmod 700 secrets
install -m 600 /path/to/provider.conf secrets/wg0.conf
```

Change the `COMPOSE_FILE` line in `.env` to:

```dotenv
COMPOSE_FILE=compose.yaml:compose.downloads.yaml
DOWNLOADS_ENABLED=true
```

Then validate and start:

```bash
docker compose config --quiet
docker compose up -d
docker compose ps
docker compose logs gluetun
```

The Linux host must have `/dev/net/tun` and permit `NET_ADMIN` for Gluetun. Some NAS or nested container environments need host configuration first. Gluetun stays unhealthy if the VPN cannot connect; qBittorrent then waits instead of starting on the normal network.

Once Gluetun is healthy, connect qBittorrent in the panel and use **Setup → Download clients** to create the categories and ARR connections. The manual guide’s step 4 covers the same settings if you prefer to do it yourself. Get qBittorrent’s temporary admin password from `docker compose logs qbittorrent` and replace it in the Web UI. Select `tun0` as its network interface.

This setup does not configure provider port forwarding. No torrent port is published on the host. Outbound peer connections can still work; incoming connectivity depends on your provider and requires separate configuration.

## Check the route

Before adding downloads, check qBittorrent’s namespace against a public IP service:

```bash
docker compose exec qbittorrent curl -fsS https://ipinfo.io/ip
```

It should report the VPN exit IP, not your home IP. If that image lacks `curl`, use Gluetun’s connection logs to inspect its reported public IP. This route check alone does not prove behavior during an outage; verify the firewall and interface binding with a controlled VPN interruption before relying on the setup.

Gluetun’s built-in firewall is the network boundary. A healthy-start dependency does not stop qBittorrent when VPN health later changes. The shared namespace keeps its traffic under Gluetun’s firewall; the explicit `tun0` binding adds a second restriction. Never disable Gluetun’s firewall to solve connectivity problems.

To recreate the VPN namespace after changing its configuration, recreate both services together:

```bash
docker compose up -d --force-recreate gluetun qbittorrent
```

To disable downloads, stop and remove the optional containers _before_ changing `.env` back to `COMPOSE_FILE=compose.yaml`:

```bash
docker compose stop qbittorrent gluetun
docker compose rm -f qbittorrent gluetun
```

Configuration and downloaded files stay on disk. Disconnect qBittorrent in the panel and set `DOWNLOADS_ENABLED=false` in `.env` when disabling downloads. The panel keeps downloads available as an optional connection.
