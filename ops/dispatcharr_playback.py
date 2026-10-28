"""Allow extensionless Amagi HLS segments without allowing local-file inputs.

Run inside Dispatcharr after the channel layout helper. Custom profiles stay intact.
"""

import json
import os
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit

PROFILE = "Media Stack Amagi HLS"
PARAMETERS = (
    "-fflags +genpts+discardcorrupt -protocol_whitelist http,https,tcp,tls,crypto "
    "-allowed_extensions ALL -allowed_segment_extensions ALL -extension_picky 0 "
    "-user_agent {userAgent} -i {streamUrl} -max_interleave_delta 100000 "
    "-c copy -sn -dn -mpegts_flags +resend_headers+initial_discontinuity -f mpegts pipe:1"
)


def amagi_hls(url):
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme in {"http", "https"} and host.endswith(".amagi.tv") and parsed.path.endswith(".m3u8")


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dispatcharr.settings")
    import django

    django.setup()
    from django.db import transaction
    from apps.channels.models import Channel, ChannelOverride, ChannelStream
    from apps.channels.managers import with_effective_values
    from core.models import StreamProfile

    profile, _ = StreamProfile.objects.get_or_create(
        name=PROFILE, defaults={"command": "ffmpeg", "parameters": PARAMETERS}
    )
    urls = defaultdict(list)
    for pk, url in ChannelStream.objects.values_list("channel_id", "stream__url"):
        urls[pk].append(url)
    state_path = Path("/data/iptv-org-playback.json")
    previous = json.loads(state_path.read_text()) if state_path.exists() else {}
    managed = {}
    changed = []
    with transaction.atomic():
        for channel in with_effective_values(Channel.objects.all(), select_related_fks=True):
            pk = str(channel.id)
            override = getattr(channel, "override", None)
            eligible = bool(urls[channel.id]) and all(amagi_hls(u) for u in urls[channel.id])
            if not eligible:
                if pk in previous and override and override.stream_profile_id == profile.id:
                    override.stream_profile_id = previous[pk]
                    changed.append(override)
                continue
            effective = channel.effective_stream_profile_obj
            if override and override.stream_profile_id and override.stream_profile_id != profile.id:
                continue
            if effective and effective.name not in {"FFmpeg", "UK TV (best video)", PROFILE}:
                continue
            override, _ = ChannelOverride.objects.get_or_create(channel=channel)
            managed[pk] = previous.get(pk, override.stream_profile_id)
            if override.stream_profile_id != profile.id:
                override.stream_profile = profile
                changed.append(override)
        ChannelOverride.objects.bulk_update(changed, ["stream_profile"], batch_size=500)
    temporary = state_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(managed) + "\n")
    temporary.replace(state_path)
    print(json.dumps({"amagi_channels": len(managed), "updated_profiles": len(changed)}), flush=True)


if __name__ == "__main__":
    main()
