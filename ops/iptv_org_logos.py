"""Cache channel logos locally; never send clients to Imgur.

Run inside Dispatcharr after iptv_org_layout.py. Existing custom logos are kept.
"""

import concurrent.futures
import hashlib
import io
import json
import os
import re
import tarfile
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path


def normalise(name):
    name = re.sub(r"\[[^]]*\]|\([^)]*\)", "", name.casefold())
    name = re.sub(r"\b(?:hd|uhd|fhd|tv|channel)\b", "", name)
    for word, number in [("one", "1"), ("two", "2"), ("three", "3"), ("four", "4"), ("five", "5")]:
        name = re.sub(r"\b" + word + r"\b", number, name)
    name = name.replace("+", "plus")
    return "".join(c for c in unicodedata.normalize("NFKD", name) if c.isalnum())


def allowed_logo(url):
    parsed = urllib.parse.urlsplit(url or "")
    host = (parsed.hostname or "").lower()
    return parsed.scheme in {"http", "https"} and bool(host) and not (
        host == "imgur.com" or host.endswith(".imgur.com")
    )


def json_source(name, cache):
    path = cache / (name + ".json")
    if not path.exists() or time.time() - path.stat().st_mtime > 86400:
        with urllib.request.urlopen("https://iptv-org.github.io/api/" + name + ".json", timeout=45) as response:
            body = response.read()
        json.loads(body)
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(body)
        temporary.replace(path)
    return json.loads(path.read_text())


def logo_pack(root, url="https://codeload.github.com/tv-logo/tv-logos/tar.gz/refs/heads/main", prefix="countries"):
    marker = root / "downloaded"
    if marker.exists() and time.time() - marker.stat().st_mtime < 7 * 86400:
        return
    with urllib.request.urlopen(url, timeout=45) as response:
        with tarfile.open(fileobj=response, mode="r|gz") as archive:
            for member in archive:
                parts = Path(member.name).parts[1:]
                if not member.isfile() or not parts or parts[0] != prefix:
                    continue
                if ".." in parts or member.size > 5 * 1024 * 1024 or not member.name.endswith(".png"):
                    continue
                destination = root.joinpath(*parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination.with_suffix(".tmp")
                temporary.write_bytes(archive.extractfile(member).read())
                temporary.replace(destination)
    marker.write_text(str(time.time()))


def validate_image(body):
    from PIL import Image

    with Image.open(io.BytesIO(body)) as image:
        if image.width > 8000 or image.height > 8000 or image.format not in {"PNG", "JPEG", "WEBP"}:
            raise ValueError("Unsupported image")
        image.load()  # Header/CRC verification alone accepts some undecodable files.
        # Imgur can return a fully valid PNG containing a regional-block notice.
        if image.size == (336, 478) and hashlib.sha256(image.convert("RGB").tobytes()).hexdigest() == (
            "3dc61e8b22368c7b4c48c2fd5e47dab2e8b3833745ee951c244e206d98540670"
        ):
            raise ValueError("Blocked-notice image")
        return {"JPEG": ".jpg", "WEBP": ".webp", "PNG": ".png"}[image.format]


def fetch_logo(url):
    import requests
    from core.http_security import validate_outbound_http_url

    deadline = time.monotonic() + 10
    for _ in range(4):
        if not allowed_logo(url):
            raise ValueError("Unsupported logo host")
        validate_outbound_http_url(url, allow_private=False, allow_loopback=False)
        with requests.get(url, timeout=(3, 4), stream=True, allow_redirects=False) as response:
            if response.is_redirect:
                url = urllib.parse.urljoin(url, response.headers["Location"])
                continue
            response.raise_for_status()
            body = bytearray()
            for chunk in response.iter_content(16384):
                body.extend(chunk)
                if len(body) > 2 * 1024 * 1024 or time.monotonic() > deadline:
                    raise ValueError("Logo size or time limit exceeded")
            return bytes(body)
    raise ValueError("Too many logo redirects")


def fallback_image(name, country):
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (320, 180), "#172638")
    draw = ImageDraw.Draw(image)
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    font = ImageFont.truetype(font_path, 23)
    label = re.sub(r"\([^)]*\)|\[[^]]*\]", "", name).strip()
    words = label.split()
    lines = [""]
    for word in words:
        if draw.textlength((lines[-1] + " " + word).strip(), font=font) > 290:
            lines.append(word)
        else:
            lines[-1] = (lines[-1] + " " + word).strip()
    draw.text((18, 18), country or "TV", font=font, fill="#8cb9e6")
    draw.multiline_text((18, 65), "\n".join(lines[:3]), font=font, fill="white", spacing=5)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dispatcharr.settings")
    import django

    django.setup()
    from django.db import transaction
    from apps.channels.models import Channel, ChannelOverride, Logo

    cache = Path("/data/logos/iptv-org")
    cache.mkdir(parents=True, exist_ok=True)
    pack = Path("/data/logos/tv-logo")
    pack.mkdir(parents=True, exist_ok=True)
    uk_pack = Path("/data/logos/mediaportal-uk")
    uk_pack.mkdir(parents=True, exist_ok=True)
    print("Loading local logo pack", flush=True)
    logo_pack(pack)
    logo_pack(uk_pack, "https://codeload.github.com/Jasmeet181/mediaportal-uk-logos/tar.gz/refs/heads/master", "TV")
    metadata = {c["id"]: c for c in json_source("channels", cache)}
    alternatives = {}
    for logo in json_source("logos", cache):
        if allowed_logo(logo.get("url")) and logo.get("format") in {"PNG", "JPEG", "WebP"}:
            alternatives.setdefault(logo["channel"], []).append(logo["url"])
    index = {}
    for path in sorted(pack.rglob("*.png")):
        stem, _, country = path.stem.rpartition("-")
        index.setdefault((country.upper(), normalise(stem.replace("-", " "))), path)
    uk_index = {}
    for path in sorted(uk_pack.rglob("*.png"), key=lambda p: (".Light" not in p.parts, str(p))):
        uk_index.setdefault(normalise(path.stem.replace("Plus", "+")), path)
    channels = list(Channel.objects.select_related("logo", "override__logo").all())
    state_path = cache / "manifest.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    jobs = {}
    channel_keys = {}
    for c in channels:
        original = c.effective_logo_obj
        override = getattr(c, "override", None)
        if override and override.logo_id and not override.logo.url.startswith((str(cache) + "/", str(pack) + "/", str(uk_pack) + "/")):
            continue
        base = (c.tvg_id or "").split("@")[0]
        key = base or str(c.uuid)
        timeshift = re.search(r"(?:@Plus|\+)\s*(\d+)", (c.tvg_id or "") + " " + c.name, re.I)
        if timeshift:
            key += "-plus-" + timeshift.group(1)
        info = metadata.get(base, {})
        country = info.get("country", "UK" if c.channel_number < 10000 else "")
        names = [override.name if override and override.name else c.name, info.get("name", ""), c.name]
        path = next((uk_index[normalise(n)] for n in names if n and normalise(n) in uk_index), None) if country == "UK" else None
        if path is None:
            path = next((index[(country, normalise(n))] for n in names if n and (country, normalise(n)) in index), None)
        # Country-neutral branding is a safe fallback for international networks.
        if path is None:
            path = next((index[("INT", normalise(n))] for n in names if n and ("INT", normalise(n)) in index), None)
        url = next(iter(alternatives.get(base, [])), None)
        if not url and original and allowed_logo(original.url):
            url = original.url
        jobs.setdefault(key, (c.name, country, path, url))
        channel_keys[c.id] = key

    def prepare(item):
        key, (name, country, path, url) = item
        previous = state.get(key, {})
        if path is not None:
            try:
                validate_image(path.read_bytes())
                return key, {"path": str(path), "fallback": False, "source": "Jasmeet181/mediaportal-uk-logos" if uk_pack in path.parents else "tv-logo/tv-logos"}
            except Exception:
                path = None
        if previous and Path(previous["path"]).is_file() and (
            not previous["fallback"] or time.time() - previous.get("checked", 0) < 7 * 86400
        ):
            try:
                validate_image(Path(previous["path"]).read_bytes())
                return key, previous
            except Exception:
                pass
        fallback = True
        suffix = ".png"
        body = None
        if url:
            try:
                body = fetch_logo(url)
                suffix = validate_image(body)
                fallback = False
            except Exception:
                body = None
        if body is None:
            body = fallback_image(name, country)
        destination = cache / (hashlib.sha256(key.encode() + body).hexdigest()[:24] + suffix)
        temporary = destination.with_suffix(".tmp")
        temporary.write_bytes(body)
        temporary.replace(destination)
        return key, {"path": str(destination), "fallback": fallback, "source": url if not fallback else "name badge", "checked": time.time()}

    print("Preparing", len(jobs), "distinct channel logos", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        for count, (key, value) in enumerate(pool.map(prepare, jobs.items()), 1):
            state[key] = value
            if count % 500 == 0:
                print("Prepared", count, "/", len(jobs), flush=True)
    temporary = state_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state) + "\n")
    temporary.replace(state_path)
    paths = {state[key]["path"] for key in channel_keys.values()}
    with transaction.atomic():
        Logo.objects.bulk_create(
            [Logo(url=path, name=Path(path).stem) for path in paths], ignore_conflicts=True, batch_size=500
        )
        logos = dict(Logo.objects.filter(url__in=paths).values_list("url", "id"))
        ChannelOverride.objects.bulk_create(
            [ChannelOverride(channel_id=pk) for pk in channel_keys], ignore_conflicts=True, batch_size=500
        )
        overrides = list(ChannelOverride.objects.filter(channel_id__in=channel_keys))
        for override in overrides:
            override.logo_id = logos[state[channel_keys[override.channel_id]]["path"]]
        ChannelOverride.objects.bulk_update(overrides, ["logo"], batch_size=500)
    print(json.dumps({"local_channels": len(channel_keys), "real_logos": sum(not state[k]["fallback"] for k in channel_keys.values()), "name_badges": sum(state[k]["fallback"] for k in channel_keys.values())}), flush=True)


if __name__ == "__main__":
    main()
