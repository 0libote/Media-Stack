# Using the control panel

On first use, choose an administrator username and password in the browser. Sign in with those details on subsequent visits. The panel has one administrator account; each connected app keeps its own accounts. Existing password-only panels upgrade to username `admin` with the same password.

## Connections and addresses

There are two addresses for each app:

- **Internal address:** used by the panel and the other containers. This repo uses `http://jellyfin:8096`, `http://seerr:5055`, `http://radarr:7878`, `http://sonarr:8989`, `http://prowlarr:9696`, and `http://qbittorrent:8080` for qBittorrent in either routing mode, `http://dispatcharr:9191` for TV, and `http://gluetun:9999` for VPN health.
- **Browser address:** the address your phone or computer can open. By default, the panel uses its own hostname and the app’s standard port. Set an override if you use another port or a reverse proxy.

A container’s `localhost` points to that container. Don’t use the browser’s `localhost` address to link separate containers.

Testing a connection does not save it. Saving verifies it again before replacing the panel’s stored connection. A failed save keeps the previous settings. Leave a saved key/password field blank to keep its value. Disconnecting forgets that app in the panel; it does not remove it or alter its integrations elsewhere.

**Connect local apps** reads API keys from the mounted configurations for Radarr, Sonarr, Prowlarr, and Seerr. Finish those apps’ initial account setup first. Local keys are only sent to the installed service’s default internal address; use a manual key for a custom endpoint. Jellyfin requires an API key from Dashboard → API Keys. qBittorrent requires a permanent username/password from its Web UI.

## Storage

The panel only browses or creates directories under the shared `/data` mount. Hidden folders and symlinks are excluded from browsing, and paths resolving outside the mount are rejected. Files are never listed by the folder browser.

Movie and TV folders must be separate, must not contain each other, and must not overlap the download tree under `/data/torrents`. Save your choices, then use Setup to create missing folders and add the locations to the apps. Saving preferences by itself does not modify an upstream app.

**Check folders** creates temporary files in the incomplete download folder, attempts a hardlink into each chosen library location, and removes the temporary files. A passing result verifies access as the panel’s UID/GID at that moment. The Compose stack gives the library tools the same UID/GID. Other installations may use different identities, so still check their permissions separately.

Disk figures describe the filesystem containing `/data`, including space used by other files on that filesystem. They are not a measurement of your library’s size. The panel does not recursively scan media to estimate usage.

## Review and apply

A setup review lasts five minutes and can be applied once. Changing panel connections or preferred locations invalidates it. No configuration writes happen during review; qBittorrent may receive a login request to check its categories.

The review reports:

| Result          | Meaning                                                                                               |
| --------------- | ----------------------------------------------------------------------------------------------------- |
| New             | The setting is missing and can be created.                                                            |
| Already set     | A matching setting exists and will be preserved.                                                      |
| Needs attention | A required connection is missing or an existing setting conflicts. The detail explains where to look. |

Apply creates the ready settings in order. Blocked steps are skipped and reported. If a write fails, later ready steps stop; completed changes remain saved. Review again after fixing the problem. Each create action rechecks the upstream app to avoid duplicates on retries. The operation is not a transaction across several independent apps and does not attempt destructive rollback.

### Settings it can create

- Library/download directories inside `/data`.
- Movie and TV root folders in Radarr and Sonarr.
- Jellyfin Movies and TV Shows libraries, followed by a library scan. A matching path is kept; a name conflict is left for native-app review.
- qBittorrent `movies` and `tv` categories with explicit save paths. Existing categories with another path are blocked. Global save preferences and existing torrents are unchanged.
- qBittorrent download clients in Radarr and Sonarr, using the respective categories. Matching existing clients keep their credentials and categories.
- Prowlarr → Radarr/Sonarr app links with Full Sync, using the upstream schema’s default supported categories.
- Seerr → Radarr/Sonarr links with the quality profile you select and the preferred library folder. A new entry becomes default only if there is no existing non-4K default.

For this setup, every connected app must see the same `/data` paths and be able to resolve the internal service addresses. If you connect apps outside this Compose network, adapt their mounts and addresses first. The panel cannot infer how another host mounts its disks.

### Steps in the native apps

Create the Jellyfin administrator, complete Seerr’s Jellyfin sign-in, add indexers and their accounts in Prowlarr, choose detailed quality/naming settings, configure VPN credentials, and verify the VPN route. The panel never creates remote accounts or downloads media during setup.

If an existing app integration is broken, edit it in that app or remove that specific integration there before reviewing a new connection. The panel deliberately preserves existing integrations rather than overwriting their custom settings. Adding a new root folder does not change existing movie/series paths.

## Status and statistics

The overview reads the APIs in parallel, caching snapshots for 15 seconds. The visible overview refreshes every 30 seconds; other screens refresh when you request it. Missing metrics show “—”; confirmed zero counts show “0”. A failed secondary endpoint leaves the app connected but reports that its statistics could not be read.

Service connection status means the API responded with the saved credentials. It is not Docker container health. The panel does not use Docker’s socket. In particular, qBittorrent API access does not establish whether the VPN exit route is working; verify that on the host.

Panel activity records up to 50 connection/setup events. It is not the download/import history from the apps. Torrents are limited to eight active download entries, and sensitive API error bodies are not forwarded to the browser.

## Supported API families

The adapters use Jellyfin’s system/library/session endpoints; Radarr v3; Sonarr v3 (Sonarr 4); Prowlarr v1; Seerr `/api/v1`; and qBittorrent `/api/v2`. Integration payloads are built from Radarr/Sonarr/Prowlarr’s own schemas to retain upstream defaults. Incompatible fields block the operation instead of guessing.

References: [Jellyfin API](https://api.jellyfin.org/), [Radarr API](https://radarr.video/docs/api/), [Sonarr API](https://sonarr.tv/docs/api/), [Prowlarr API](https://prowlarr.com/docs/api/), [Seerr API](https://docs.seerr.dev/api/), [qBittorrent WebUI API](https://github.com/qbittorrent/qBittorrent/wiki/WebUI-API-%28qBittorrent-5.0%29).

Gluetun and Dispatcharr use read-only health/version checks in the panel and need no app credentials there. Gluetun has no browser UI. Manage TV sources and recordings in Dispatcharr; changing VPN routing uses the host command in [downloads](downloads.md). The panel still has no Docker socket.
