"""Emit the curated, real UK listings inside the Dispatcharr container."""

import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def clean_guide(body, mapped_ids):
    root = ET.fromstring(body)
    icons = {c.get("id"): c.find("icon").get("src") for c in root.findall("channel") if c.find("icon") is not None}
    for programme in list(root.findall("programme")):
        channel = programme.get("channel")
        if channel not in mapped_ids:
            root.remove(programme)
            continue
        if programme.find("icon") is None and icons.get(channel):
            ET.SubElement(programme, "icon", src=icons[channel])
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def main():
    if not os.environ.get("DJANGO_SECRET_KEY") and Path("/data/jwt").is_file():
        os.environ["DJANGO_SECRET_KEY"] = Path("/data/jwt").read_text().strip()
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dispatcharr.settings")
    import django

    django.setup()
    from django.test import RequestFactory
    from apps.channels.models import Channel
    from apps.channels.managers import with_effective_values
    from apps.channels.utils import format_channel_number
    from apps.output.epg import generate_epg

    rows = with_effective_values(
        Channel.objects.filter(channelprofilemembership__channel_profile__name="UK Guide", channelprofilemembership__enabled=True),
        select_related_fks=True,
    )
    mapped = {
        str(format_channel_number(c.effective_channel_number))
        for c in rows
        if c.effective_epg_data_obj and c.effective_epg_data_obj.epg_source
        and c.effective_epg_data_obj.epg_source.source_type == "xmltv"
    }
    request = RequestFactory().get("/output/epg/UK%20Guide", HTTP_HOST="dispatcharr:9191")
    response = generate_epg(request, "UK Guide")
    body = b"".join(chunk if isinstance(chunk, bytes) else chunk.encode() for chunk in response.streaming_content)
    sys.stdout.buffer.write(clean_guide(body, mapped))


if __name__ == "__main__":
    main()
