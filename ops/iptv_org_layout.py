"""Keep iptv-org channels in a UK-first layout inside Dispatcharr.

Run with: docker exec -i media-stack-dispatcharr-1 python - < ops/iptv_org_layout.py
The source itself refreshes through Dispatcharr's M3U scheduler.
"""

import json
import os
import re
import urllib.request
from pathlib import Path

UK_NUMBERS = {
    "BBCOne.uk": 1,
    "BBCTwo.uk": 2,
    "Channel4.uk": 4,
    "Channel5.uk": 5,
    "ITV2.uk": 6,
    "BBCFour.uk": 9,
    "ITV3.uk": 10,
    "E4.uk": 13,
    "QVC.uk": 16,
    "More4.uk": 18,
    "5USA.uk": 21,
    "TJC.uk": 22,
    "BBCThree.uk": 23,
    "ITV4.uk": 26,
    "GREATromance.uk": 52,
    "ThatsTV.uk": 56,
    "GREATmovies.uk": 62,
    "Blaze.uk": 64,
    "TBNUK.uk": 66,
    "TrueCrime.uk": 67,
    "TalkingPicturesTV.uk": 82,
    "CBBC.uk": 201,
    "CBeebies.uk": 202,
    "Pop.uk": 205,
    "TinyPop.uk": 206,
    "BBCNews.uk": 231,
    "BBCParliament.uk": 232,
    "SkyNews.uk": 233,
    "GBNews.uk": 236,
}

# Available DTT services, using Freeview's England order (22 October 2026).
# Regional alternatives and duplicate feeds remain in the catalogue after these.
UK_STATIONS = [
    (1, "BBC One", ["BBCOneSouth.uk", "BBCOne.uk"]),
    (2, "BBC Two", ["BBCTwoHD.uk", "BBCTwo.uk"]),
    (3, "STV", ["STVCentral.uk"]),
    (4, "Channel 4", ["Channel4.uk"]),
    (5, "5", ["Channel5.uk"]),
    (6, "ITV2", ["ITV2.uk"]),
    (7, "Latest TV", ["LatestTV.uk"]),
    (9, "BBC Four", ["BBCFourHD.uk", "BBCFour.uk"]),
    (10, "ITV3", ["ITV3.uk"]),
    (13, "E4", ["E4.uk"]),
    (16, "QVC", ["QVC.uk"]),
    (18, "More4", ["More4.uk"]),
    (21, "5USA", ["5USA.uk"]),
    (22, "TJC", ["TJC.uk"]),
    (23, "BBC Three", ["BBCThreeHD.uk", "BBCThree.uk"]),
    (25, "U&W", ["UW.uk"]),
    (26, "ITV4", ["ITV4.uk"]),
    (35, "STV +1", ["STVCentralPlus1.uk"]),
    (45, "Gemporia", ["GemsTV.uk"]),
    (52, "GREAT! Romance", ["GREATromance.uk"]),
    (56, "That's TV", ["ThatsTV.uk"]),
    (62, "GREAT! Movies", ["GREATmovies.uk"]),
    (64, "Blaze", ["Blaze.uk"]),
    (66, "TBN UK", ["TBNUK.uk"]),
    (67, "True Crime", ["TrueCrime.uk"]),
    (73, "HobbyMaker", ["HobbyMaker.uk"]),
    (82, "Talking Pictures TV", ["TalkingPicturesTV.uk"]),
    (83, "Together TV", ["TogetherTV.uk"]),
    (87, "TV Warehouse", ["TVWarehouse.uk"]),
    (201, "CBBC", ["CBBC.uk"]),
    (202, "CBeebies", ["CBeebies.uk"]),
    (205, "POP", ["Pop.uk"]),
    (206, "Tiny Pop", ["TinyPop.uk"]),
    (207, "POP UP", ["PopUp.uk"]),
    (231, "BBC News", ["BBCNews.uk"]),
    (232, "BBC Parliament", ["BBCParliament.uk"]),
    (233, "Sky News", ["SkyNews.uk"]),
    (236, "GB News", ["GBNews.uk"]),
    (250, "BBC Red Button", ["BBCRedButton1.uk"]),
]


def curated_uk(records, previous_primary=()):
    primary = {}
    for number, name, bases in UK_STATIONS:
        candidates = [
            r for r in records
            if (r["tvg_id"] or "").split("@")[0] in bases
            and ("Plus1" in bases[0] or not re.search(r"@Plus|\+\s*1", (r["tvg_id"] or "") + r["name"]))
        ]
        if not candidates:
            continue
        chosen = min(candidates, key=lambda r: (
            r["id"] not in previous_primary,
            bool(r["auto_created_by_id"]),
            "Geo-blocked" in r["name"],
            r["id"],
        ))
        primary[chosen["id"]] = {"channel_number": number, "name": name}
    extra = sorted((r for r in records if r["id"] not in primary), key=lambda r: (r["name"].casefold(), r["id"]))
    plan = dict(primary)
    for number, record in enumerate(extra, 10000):
        plan[record["id"]] = {"channel_number": number, "name": "[UK] " + record["name"]}
    return plan, set(primary)


def uk_feed_ids(playlist):
    if not playlist.lstrip().startswith("#EXTM3U"):
        raise ValueError("The UK source did not return an M3U playlist.")
    ids = set(re.findall(r'tvg-id="([^"]+)"', playlist))
    if not ids:
        raise ValueError("The UK playlist contains no channel identifiers.")
    return ids


def is_uk(feed_id, uk_ids, metadata):
    return (
        feed_id in uk_ids
        or metadata.get(feed_id.split("@")[0], {}).get("country") == "UK"
    )


def choose_number(feed_id, used):
    number = UK_NUMBERS.get(feed_id.split("@")[0], 1000)
    if number in used:
        number = 1000
    while number in used:
        number += 1
    if number >= 10000:
        raise ValueError("The UK channel-number range is full.")
    used.add(number)
    return number


def guide_id(feed_id, available):
    base, _, feed = feed_id.partition("@")
    region = re.sub(r"HD$", "", feed)
    stem = base.removesuffix(".uk")
    candidates = []
    if region and region not in {"SD", "HD", "UK"}:
        candidates.extend([f"{stem}{region}.uk", f"{stem}{region}HD.uk"])
    candidates.extend([base, f"{stem}HD.uk"])
    aliases = {
        "Channel4.uk": ["Channel4South.uk", "Channel4London.uk"],
        "Channel5.uk": ["5.uk"],
        "QVC.uk": ["QVCUK.uk"],
        "QVCBeauty.uk": ["QVCBeautyUK.uk"],
        "QVCExtra.uk": ["QVCExtraUK.uk"],
        "QVCStyle.uk": ["QVCStyleUK.uk"],
        "UW.uk": ["UAndW.uk"],
    }
    candidates.extend(aliases.get(base, []))
    casefolded = {key.casefold(): key for key in available}
    return next((casefolded[c.casefold()] for c in candidates if c.casefold() in casefolded), None)


def country_info(feed_id, metadata, countries):
    code = metadata.get(feed_id.split("@")[0], {}).get("country", "")
    return code, countries.get(code, "Other countries")


def international_key(feed_id, name, metadata, countries):
    code, country = country_info(feed_id, metadata, countries)
    priority = {"IE": 0, "US": 1, "CA": 2, "AU": 3, "NZ": 4}
    return priority.get(code, 5), country.casefold(), name.casefold(), feed_id


def download(url):
    with urllib.request.urlopen(url, timeout=45) as response:
        return response.read().decode()


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dispatcharr.settings")
    import django

    django.setup()
    from django.db import transaction
    from django.db.models import Min
    from apps.channels.models import (
        Channel,
        ChannelGroup,
        ChannelGroupM3UAccount,
        ChannelOverride,
        ChannelProfile,
        ChannelProfileMembership,
    )
    from apps.m3u.models import M3UAccount
    from apps.m3u.tasks import sync_auto_channels
    from apps.epg.models import EPGData
    from core.models import StreamProfile

    uk_ids = uk_feed_ids(download("https://iptv-org.github.io/iptv/countries/uk.m3u"))
    metadata = {
        item["id"]: item
        for item in json.loads(download("https://iptv-org.github.io/api/channels.json"))
    }
    countries = {
        item["code"]: item["name"]
        for item in json.loads(download("https://iptv-org.github.io/api/countries.json"))
    }
    state_path = Path("/data/iptv-org-layout.json")
    managed = json.loads(state_path.read_text()) if state_path.exists() else {}
    uk_state_path = Path("/data/uk-lineup.json")
    uk_state = json.loads(uk_state_path.read_text()) if uk_state_path.exists() else {}
    account = M3UAccount.objects.get(name="iptv-org Worldwide")
    if account.status != "success" or not account.streams.exists():
        raise SystemExit("Wait for the iptv-org M3U import to finish successfully.")
    uk, _ = ChannelProfile.objects.get_or_create(name="UK")
    international, _ = ChannelProfile.objects.get_or_create(name="International")
    uk_group, _ = ChannelGroup.objects.get_or_create_manual(name="UK TV")
    guide_profile, _ = ChannelProfile.objects.get_or_create(name="UK Guide")
    profile = StreamProfile.objects.filter(
        name="UK TV (best video)"
    ).first() or StreamProfile.objects.get(name="FFmpeg")
    changed_groups = False
    for relation in ChannelGroupM3UAccount.objects.filter(
        m3u_account=account
    ).select_related("channel_group"):
        target, _ = ChannelGroup.objects.get_or_create_manual(
            name="International - " + relation.channel_group.name
        )
        props = dict(relation.custom_properties or {})
        desired = dict(
            props,
            group_override=target.id,
            channel_numbering_mode="fixed",
            channel_sort_order="name",
            channel_profile_ids=[international.id],
            skip_channel_profile_memberships=True,
            stream_profile_id=profile.id,
        )
        if (
            not relation.auto_channel_sync
            or relation.auto_sync_channel_start != 10000
            or props != desired
        ):
            relation.auto_channel_sync = True
            relation.auto_sync_channel_start = 10000
            relation.custom_properties = desired
            relation.save(
                update_fields=[
                    "auto_channel_sync",
                    "auto_sync_channel_start",
                    "custom_properties",
                ]
            )
            changed_groups = True
    if changed_groups or not Channel.objects.filter(auto_created_by=account).exists():
        cutoff = account.streams.filter(is_stale=False).aggregate(
            first=Min("last_seen")
        )["first"]
        result = sync_auto_channels(account.id, scan_start_time=cutoff)
        if result.get("channels_failed"):
            raise RuntimeError(
                "Some iptv-org channels failed to import: "
                + str(result["channels_failed"])
            )
        print("Native channel sync:", result, flush=True)

    channels = list(Channel.objects.filter(auto_created_by=account).order_by("tvg_id"))
    used = set(
        Channel.objects.exclude(auto_created_by=account).values_list(
            "channel_number", flat=True
        )
    )
    used.update(
        ChannelOverride.objects.exclude(channel_number=None).values_list(
            "channel_number", flat=True
        )
    )
    epg = {
        item.tvg_id: item
        for item in EPGData.objects.filter(
            epg_source__name="UK Freeview programme guide"
        )
    }
    uk_channels = set(
        Channel.objects.exclude(auto_created_by=account)
        .filter(channel_group=uk_group)
        .values_list("id", flat=True)
    )
    international_channels = set()
    mapped = 0
    with transaction.atomic():
        for channel in channels:
            if not is_uk(channel.tvg_id or "", uk_ids, metadata):
                international_channels.add(channel.id)
                continue
            uk_channels.add(channel.id)
            override, _ = ChannelOverride.objects.get_or_create(channel=channel)
            fields = []
            if override.channel_number is None:
                override.channel_number = choose_number(channel.tvg_id, used)
                fields.append("channel_number")
            if override.channel_group_id is None:
                override.channel_group = uk_group
                fields.append("channel_group")
            matched = guide_id(channel.tvg_id, epg)
            if matched:
                mapped += 1
                if override.epg_data_id is None:
                    override.epg_data = epg[matched]
                    fields.append("epg_data")
            if fields:
                override.save(update_fields=fields)
        uk_records = list(Channel.objects.filter(id__in=uk_channels).values("id", "tvg_id", "name", "auto_created_by_id"))
        uk_plan, primary_ids = curated_uk(uk_records, uk_state.get("primary_ids", []))
        ChannelOverride.objects.bulk_create(
            [ChannelOverride(channel_id=pk) for pk in uk_channels], ignore_conflicts=True, batch_size=500
        )
        uk_overrides = {o.channel_id: o for o in ChannelOverride.objects.filter(channel_id__in=uk_channels)}
        main_group, _ = ChannelGroup.objects.get_or_create_manual(name="UK / Freeview")
        extra_group, _ = ChannelGroup.objects.get_or_create_manual(name="UK / Regional and other")
        owned_uk = {}
        for pk, desired in uk_plan.items():
            desired = dict(desired, channel_group_id=main_group.id if pk in primary_ids else extra_group.id)
            override = uk_overrides[pk]
            previous = uk_state.get("managed", {}).get(str(pk), {})
            owned_uk[str(pk)] = dict(previous)
            for field, value in desired.items():
                current = getattr(override, field)
                if not uk_state or current is None or current == previous.get(field):
                    setattr(override, field, value)
                    owned_uk[str(pk)][field] = value
            matched = guide_id(next(r["tvg_id"] or "" for r in uk_records if r["id"] == pk), epg)
            if matched and override.epg_data_id is None:
                override.epg_data = epg[matched]
        ChannelOverride.objects.bulk_update(
            list(uk_overrides.values()), ["channel_number", "name", "channel_group", "epg_data"], batch_size=500
        )
        # Manage only our own values: a user's later edits stay in place.
        international_rows = [c for c in channels if c.id in international_channels]
        ChannelOverride.objects.bulk_create(
            [ChannelOverride(channel_id=c.id) for c in international_rows],
            ignore_conflicts=True,
            batch_size=500,
        )
        overrides = {
            o.channel_id: o
            for o in ChannelOverride.objects.select_related("channel").all()
        }
        reserved = {
            overrides[c.id].channel_number
            if c.id in overrides and overrides[c.id].channel_number is not None
            else c.channel_number
            for c in Channel.objects.exclude(id__in=international_channels)
        }
        for c in international_rows:
            current = overrides[c.id].channel_number
            if current is not None and current != managed.get(str(c.id), {}).get("channel_number"):
                reserved.add(current)
        groups = {}
        changed = []
        number = 20000
        for c in sorted(
            international_rows,
            key=lambda c: international_key(c.tvg_id or "", c.name, metadata, countries),
        ):
            code, country = country_info(c.tvg_id or "", metadata, countries)
            if country not in groups:
                groups[country], _ = ChannelGroup.objects.get_or_create_manual(
                    name="International / " + country
                )
            while number in reserved:
                number += 1
            desired = {
                "channel_number": number,
                "name": f"[{code or 'INT'}] {c.name}",
                "channel_group_id": groups[country].id,
            }
            override = overrides[c.id]
            previous = managed.get(str(c.id), {})
            owned = dict(previous)
            for field, value in desired.items():
                current = getattr(override, field)
                if current is None or current == previous.get(field):
                    setattr(override, field, value)
                    owned[field] = value
            reserved.add(override.channel_number)
            managed[str(c.id)] = owned
            changed.append(override)
            number += 1
        ChannelOverride.objects.bulk_update(
            changed, ["channel_number", "name", "channel_group"], batch_size=500
        )
        for channel_profile, selected in [
            (uk, uk_channels),
            (international, international_channels),
            (guide_profile, primary_ids),
        ]:
            ChannelProfileMembership.objects.bulk_create(
                [
                    ChannelProfileMembership(
                        channel_profile=channel_profile, channel_id=pk, enabled=True
                    )
                    for pk in selected
                ],
                ignore_conflicts=True,
                batch_size=500,
            )
            channel_profile.channelprofilemembership_set.filter(
                channel_id__in=selected
            ).update(enabled=True)
            channel_profile.channelprofilemembership_set.exclude(
                channel_id__in=selected
            ).update(enabled=False)
    temporary = state_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(managed) + "\n")
    temporary.replace(state_path)
    temporary = uk_state_path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"primary_ids": sorted(primary_ids), "managed": owned_uk}) + "\n")
    temporary.replace(uk_state_path)
    print(
        json.dumps(
            {
                "uk_channels": len(uk_channels),
                "international_channels": len(international_channels),
                "iptv_org_channels": len(channels),
                "uk_guide_matches": mapped,
                "primary_uk_channels": len(primary_ids),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
