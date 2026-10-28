# Live TV with Dispatcharr

Dispatcharr is included in the stack at **http://YOUR-SERVER-IP:9191**. Open it from the panel and create its first administrator account. Its panel connection checks the public version endpoint; manage channels, sources, guide data, users and recordings in Dispatcharr itself.

Dispatcharr runs on the normal connection independently of Gluetun. Its database/settings use the `media-stack_dispatcharr-data` named volume. Recordings use `DATA_DIR/recordings`, mounted at `/data/recordings`. Keep both in backups. The database volume stays on Docker's internal filesystem, even when media uses an external disk.

## Add channels and guide data

1. In Dispatcharr's M3U/EPG Manager, add a working M3U file/URL or Xtream Codes provider, then refresh it. For a Freeview aerial, a working tuner backend such as Tvheadend must supply an M3U playlist first.
2. Select the channels to expose, assign their names/numbers and a channel group, and add backup streams where available. A stream appearing in a playlist does not establish that it plays.
3. Add a matching XMLTV programme guide, refresh it, and match each channel's EPG ID. Set a refresh interval so schedules stay current. One public UK guide is [Freeview-EPG](https://github.com/dp247/Freeview-EPG), which documents its coverage and update schedule.
4. Use Dispatcharr's TV Guide to watch or record programmes. For DASH/HLS sources, choose an appropriate FFmpeg stream profile. Do not map every video representation from a DASH source into a single output; one video/audio pair is sufficient.

The software does not supply a UK channel subscription. A complete BBC/ITV/Channel 4/Channel 5 lineup needs working sources for those channels. Public streams vary by channel, geography and availability; an aerial reception fault remains a tuner/aerial issue. A guide supplies schedules, not the streams themselves.

## Watch in Jellyfin

In Jellyfin **Dashboard → Live TV**, add an M3U tuner:

```text
http://dispatcharr:9191/output/m3u
```

Add an XMLTV guide:

```text
http://dispatcharr:9191/output/epg
```

Associate the guide with that tuner and refresh Jellyfin's guide. Both services share the Compose network, so host networking or UDP discovery is unnecessary for this M3U setup. Existing TV sources can be retained; remove a retired source only after the replacement plays.

Before considering setup complete, verify actual audio/video from Dispatcharr, guide entries in Jellyfin, recordings in the mounted directory, and operation with Gluetun stopped.

See the upstream [installation](https://github.com/Dispatcharr/Dispatcharr/blob/main/docker/docker-compose.aio.yml), [channel management](https://dispatcharr.github.io/Dispatcharr-Docs/channels/) and [Jellyfin Live TV](https://jellyfin.org/docs/general/server/live-tv/) documentation.

## Public UK sources

Public lists are starting points: test video and audio before exposing a channel. [Free-TV's UK list](https://github.com/Free-TV/IPTV/blob/master/lists/uk.md) and [iptv-org's UK playlist](https://iptv-org.github.io/iptv/countries/uk.m3u) include links that may stop working. Keep failed entries out of the published lineup.

For STV's ITV-network programming, the built-in Streamlink profile can use `https://player.stv.tv/live/stv` and `https://player.stv.tv/live/stv-plus-1`. It resolves the current manifests on playback. [Streamlink documents the STV plugin](https://streamlink.github.io/plugins.html#stv). Label STV as STV and use the matching regional guide, rather than presenting it as ITV1 England.

Sky News can use the Streamlink profile with its official `https://www.youtube.com/@SkyNews/live` page. Plain HLS/DASH broadcaster feeds can use an FFmpeg profile selecting one video/audio pair. Channel-specific profiles should be saved on the channel so source refreshes keep the intended player.

## iptv-org with a UK-first guide

Add an M3U account named **iptv-org Worldwide**, using `https://iptv-org.github.io/iptv/index.m3u` and a 24-hour refresh interval. In its advanced settings, set the stream hash key to `tvg_id` so channel identity survives stream URL changes. Keep existing working channels and their sources; the full public catalogue is added alongside them.

For UK schedules, add an XMLTV source named **UK Freeview programme guide** using `https://raw.githubusercontent.com/dp247/Freeview-EPG/master/epg.xml`, refresh it and set a 12-hour refresh interval. The helper uses that source for guide matches and the built-in FFmpeg stream profile, or the existing **UK TV (best video)** profile when present.

After the first source refresh succeeds, run this from the deployed checkout:

```bash
sudo sh -c 'docker exec -i media-stack-dispatcharr-1 python - < ops/iptv_org_layout.py'
sudo sh -c 'docker exec -i media-stack-dispatcharr-1 python - < ops/iptv_org_logos.py'
```

The layout helper enables native channel auto-sync for the source and adds persistent number/group/guide overrides. The main available UK services use current Freeview logical channel numbers, with one feed per station. Regional variants and other UK channels start at 10000. International channels start at 20000, grouped by country and sorted by name within each country. Ireland, the US, Canada, Australia and New Zealand come before the remaining countries in alphabetical order. International names include a country code such as `[FR]`, making the country visible in players that do not expose playlist groups.

The **UK** and **International** profiles provide filtered playlists, and **UK Guide** selects only the primary UK services for programme listings, while the normal **All** output retains the complete lineup. New UK channels are identified using the project's UK playlist and channel-country metadata. Available schedules are matched against the existing **UK Freeview programme guide** source; playlist import alone does not supply programme listings. `/data/iptv-org-layout.json` and `/data/uk-lineup.json` record the international and UK overrides managed by the helper, so later manual name/number/group edits are retained.

For all channels in Jellyfin with UK channels first, use two M3U tuners: `http://dispatcharr:9191/output/m3u/UK` and `http://dispatcharr:9191/output/m3u/International`. Run `sudo python3 ops/update_uk_guide.py --output /DATA/AppData/jellyfin/config/media-stack-uk-guide.xml` and use `/config/config/media-stack-uk-guide.xml` as Jellyfin’s XMLTV path, enabled only for the UK tuner. Adjust the host path to match the Jellyfin config mount. This exports real listings from **UK Guide**, removes generated channel-name placeholder programmes and supplies a local channel logo when programme art is missing. Corrected source aliases cover Channel 4, 5, QVC and GREAT! Movies. The international catalogue starts at 20000 and has no invented programme listings. Keep the existing UK tuner ID when adding the international tuner so its channel setup is preserved. Jellyfin's channel-number sorting puts UK channels first. International channels remain available without programme listings unless another guide is configured for them.

For a UK-only Jellyfin guide, omit the international tuner. The single `/output/m3u` endpoint also exposes the complete catalogue, but applying a guide to that large lineup takes much longer to refresh. Dispatcharr's Channels and TV Guide screens have a profile selector for **All**, **UK** and **International**.

On the example server, install `ops/iptv-org-layout.service` and `ops/iptv-org-layout.timer` in `/etc/systemd/system/`, reload systemd and enable the timer. Adjust its checkout path and container name for another host. It runs five minutes after boot and hourly thereafter, maintaining the layout, local logos and atomic XMLTV export. The M3U account's own daily refresh updates streams; existing user overrides are retained. To stop layout maintenance, disable its timer. Back up the Dispatcharr volume and the installed units before changing the lineup.

### Local logos and browsing performance

`ops/iptv_org_logos.py` downloads the PNG packs from [tv-logo/tv-logos](https://github.com/tv-logo/tv-logos) and [MediaPortal UK logos](https://github.com/Jasmeet181/mediaportal-uk-logos), preferring the light UK artwork for dark guides, matches names within the correct country, and caches other usable public logos from [iptv-org's logo API](https://github.com/iptv-org/api#logos). Imgur is excluded, including redirects to it. Files must fully decode; an HTTP success or valid image header alone is insufficient. Existing Jellyfin image caches may need replacement when repairing an old blocked-notice image. When no reliable logo is available, the channel gets a local name badge. Manual logo overrides are retained. These are image files in the Dispatcharr volume under `/data/logos/`; clients receive local image URLs and do not wait for external image hosts. The pack is refreshed weekly, source metadata daily, and unsuccessful logo lookups are retried weekly. Include the volume's logo files and manifest in backups; the database dump alone does not contain them.

The installed Jellyfin 12 web build omits a page limit from its newer Channels screen, rendering the entire catalogue at once. `ops/jellyfin_web_paging.py` applies a narrowly scoped workaround to two known bundles: Channels uses the normal library page size, and the guide uses 100 channels per page. Run `sudo python3 ops/jellyfin_web_paging.py --container jellyfin` from the deployed checkout. Recovery reapplies it after a container replacement. Original bundles are saved in `config/jellyfin-web-originals/`. Unknown builds are left unchanged and reported for review after upgrades. Browsers need a hard refresh to replace their cached bundles. Native TV/mobile clients keep their own pagination behaviour; local logos and country ordering apply to them too.

In Jellyfin's scheduled tasks, set **Refresh Guide** to a daily time outside normal viewing hours. The example server uses 03:00 in its `Europe/London` timezone, replacing the rolling 24-hour interval. A large first scan can still take a while to populate metadata; browsing uses pages rather than waiting for every channel to render.

For native TV/mobile clients, local artwork and channel ordering still apply, but the web pagination workaround cannot change their code. Some apps fetch the entire channel list before drawing their guide. Keep the full catalogue available and mark the main UK channels as favourites for a smaller browsing view. Favourite flags are per Jellyfin account; choose the client's **Favourites** view/filter where supported. The example server has all 39 primary UK services favourited for its existing accounts, while preserving earlier regional favourites (44 total per account). Other channels remain under **All**. Some native guides preload the full list even when filtering, so this does not guarantee that every guide opens as quickly as the web client.

After a large import or guide cleanup, Jellyfin's built-in **Optimize Database** task can reclaim unused database space. Take a consistent database backup first. This maintenance preserves channel and user-data records; it does not change how many channels a native app requests. Jellyfin already generates numeric sort titles for live-TV channels, so its native `SortBy=SortName` requests also follow channel-number order.

Public streams can be offline or restricted by location. Imported entries remain available for selection even when a playback check fails; they are not silently removed from the catalogue.

Do not assume a Channel 4 or Channel 5 playlist entry is usable in Dispatcharr just because it opens in a browser. Their current broadcaster integrations use protected playback ([Channel 4](https://github.com/Catch-up-TV-and-More/plugin.video.catchuptvandmore/blob/dev/resources/lib/channels/uk/channel4.py), [5](https://github.com/Catch-up-TV-and-More/plugin.video.catchuptvandmore/blob/dev/resources/lib/channels/uk/my5.py)), and the public alternatives must be verified separately. A working provider/tuner feed can be added later without replacing existing channels. Their official players remain alternatives outside Jellyfin.

### Guide-first Jellyfin web layout

The deployed Jellyfin 12 server uses [JavaScript Injector](https://github.com/n00bcodr/Jellyfin-JavaScript-Injector) 4.1.0.0, installed through Jellyfin’s plugin catalogue. After installing a compatible version and restarting Jellyfin, run:

```bash
sudo python3 ops/configure_jellyfin_guide.py \
  --url http://YOUR-SERVER-IP:8096 \
  --seerr-settings /DATA/AppData/jellyseerr/settings.json
```

The helper reads the existing Jellyfin API key without displaying it. It preserves other injected scripts and custom branding, installs `integrations/jellyfin/guide.js` and `guide.css`, and retains the existing tuner/provider IDs. Do not replace the UK/International tuner URLs during a layout change: their identities determine Jellyfin’s channel IDs and favourites.

Live TV opens the timetable by default; explicitly selected tabs remain accessible. Compact rows show channel numbers, contained logos and readable names beside programme blocks, with a visible keyboard focus indicator. Styling is scoped to the guide and stored in Jellyfin’s persistent configuration. The 39 primary services available at deployment follow Freeview order; missing services require a working stream source, and regional variants and international channels remain after the primary block. The large placeholder-card overview remains an optional tab rather than the default entry screen.

This extension changes Jellyfin web and clients that use its injected web interface. Native apps retain their own menus and guide layout; they receive the same repaired artwork, numbering, schedules and favourites. Reopen the app or hard-refresh the web client after deployment. The complete catalogue still requires client pagination or a favourites filter for fast browsing.

### Fatal player errors

Check Jellyfin's FFmpeg log and Dispatcharr's stream log for the same playback attempt. A tuner returning HTTP 200 does not prove it contains video: a dead upstream can leave Jellyfin with no audio/video streams and a generic fatal-player message. A programme guide and channel logo do not validate the stream either.

`ops/dispatcharr_playback.py` installs a separate **Media Stack Amagi HLS** profile for channels whose linked inputs are all Amagi HLS feeds. Amagi's extensionless segment URLs can be rejected by FFmpeg's segment-extension checks. This profile permits those extensions while restricting input protocols to HTTP/HTTPS and their transport/encryption protocols; local-file access remains disabled. Other stream profiles and explicit user overrides are retained. The hourly layout unit applies it after channel/logo maintenance. Its ownership state is `/data/iptv-org-playback.json`; include that file in Dispatcharr backups. Run it manually with:

```bash
sudo sh -c 'docker exec -i media-stack-dispatcharr-1 python - < ops/dispatcharr_playback.py'
```

Feeds whose hostnames no longer exist, or which return access errors, still need a usable replacement source. Retain the channel and its identity while repairing its streams; deleting/recreating the channel can lose favourites. The example server's Channel 4, 5, ITV2/3/4, E4, More4 and 5USA entries currently share the unavailable `lb.iptvnetwork.net` host. Changing server DNS cannot repair a public NXDOMAIN result. Recheck the provider before treating a newly imported URL as a fix.

The example server also retains a verified BBC Red Button IPTV variant as a native custom backup stream on the existing channel. It is preferred over the failing imported variant, and its custom account uses the VLC user agent. Both links survive the normal source refresh; the channel UUID, guide number and favourites stay intact. This stream and its account settings live in Dispatcharr’s database backup.

### Intel/AMD GPU access on Linux

Jellyfin's hardware-acceleration setting must agree with its container devices. Enabling VA-API while `/dev/dri/renderD128` is absent from the container breaks playback that requires video transcoding, even if direct playback works. The optional `compose.gpu.yaml` maps that render node and adds its host group. On a supported Linux host, set `JELLYFIN_RENDER_GID` in `.env` to the output of `stat -c %g /dev/dri/renderD128`, then append `:compose.gpu.yaml` to the existing `COMPOSE_FILE` value. Keep all existing Compose files in that value. Recreate only Jellyfin and configure the matching acceleration method/supported codecs in its dashboard. See [Jellyfin's Intel GPU instructions](https://jellyfin.org/docs/general/post-install/transcoding/hardware-acceleration/intel/).

For an already registered ZimaOS stack, add the equivalent `devices` and `group_add` entries to its canonical Compose settings so the dashboard retains the device mapping. The example server maps `/dev/dri/renderD128` with group 109 and uses VA-API. Its hardware decoder list excludes VP9 and HEVC/VP9 10-bit decoding because the installed render device does not advertise those capabilities; unsupported formats use software decoding. CPU-only installations keep the default Compose configuration and should leave hardware acceleration disabled. Verify an actual transcode, not only the presence of a device or a successful direct-play stream.
