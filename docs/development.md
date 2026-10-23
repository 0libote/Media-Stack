# Development

The control panel uses Flask, Gunicorn, and the Python standard library. There is no frontend framework, CDN, external analytics, or build process for browser assets. Fonts are bundled with their license.

Python 3.12 is used in the container. The independent host setup script needs Python 3.9+. Use Node 20+ to run the browser utility tests.

## Run locally

```bash
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements.txt
mkdir -p /tmp/media-stack-dev/data
PANEL_STATE_DIR=/tmp/media-stack-dev/state \
PANEL_DATA_DIR=/tmp/media-stack-dev/data \
PANEL_KEY_DIR=/tmp/media-stack-dev/keys \
.venv/bin/gunicorn --bind 127.0.0.1:8088 --workers 1 --threads 8 'control.app:create_app()'
```

Read `/tmp/media-stack-dev/state/setup-code` to claim this development panel. Use local test instances or deliberately configured app endpoints. Settings changes use their actual APIs; don’t connect production credentials when testing writes.

Keep one Gunicorn worker: settings, the snapshot cache, review tokens, and login rate limits are process-local. Threads handle overlapping requests. Container restarts discard pending reviews and reload persistent settings.

## Validate

```bash
.venv/bin/python -m unittest discover -s tests -v
node --check portal/app.js
node --test tests/frontend.test.mjs
docker compose --env-file .env.example -f compose.yaml config --quiet
docker compose --env-file .env.example -f compose.yaml -f compose.downloads.yaml config --quiet
.venv/bin/python tests/check_compose.py
docker build -t media-stack-panel:test .
.venv/bin/python tests/check_container.py
```

`tests/check_compose.py` uses the Docker Compose CLI. A standalone Compose binary can be supplied with `COMPOSE_BINARY=/path/to/docker-compose`.

The integration tests run local HTTP fixtures with synthetic credentials. They exercise actual HTTP authentication, response parsing, preview/apply, retries, partial failures, and upstream schema payloads. They don’t contact real indexers, VPNs, or media services. Browser-format tests check unknown/zero values, progress bounds, and address generation. CI builds the panel image and smoke-tests it in a non-root, read-only container with fresh temporary mounts and no external network.

For a real install, additionally verify playback, provider connectivity, qBittorrent’s tunnel binding, actual peer traffic during a controlled VPN interruption, and the import path end to end. A passing fixture suite does not establish those host/provider behaviors.

## Project structure

- `control/app.py`: authenticated HTTP API and static assets.
- `control/integrations.py`: bounded upstream API clients and snapshots.
- `control/operations.py`: additive setup review and apply.
- `control/storage.py`: confined paths, folder browsing, disk and hardlink checks.
- `control/state.py`: private, atomic local settings.
- `portal/`: static browser application and manual guide.
- `setup.py`: standard-library host setup.

Never send saved keys or passwords back in an API response. Do not forward arbitrary upstream error bodies or add a generic API proxy. Preserve current media and third-party settings when adding setup operations.

## Dependencies

`requirements.in` lists the direct dependencies; `requirements.txt` pins the full set with hashes. If changing them, regenerate the lock and rerun validation:

```bash
uv pip compile requirements.in --generate-hashes --output-file requirements.txt
```

The panel uses the local filesystem for its private state. API keys and download-client credentials are stored in plaintext with file mode `0600`; the administrator password is hashed. Protect and encrypt host backups rather than relying on file mode alone.
