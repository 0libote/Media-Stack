"""Reviewable, additive setup actions using upstream APIs."""

import copy
import secrets
import threading
import time
from urllib.parse import urlencode, urlsplit

from .integrations import Client, ServiceError, config_for
from .state import SERVICES


def fields(resource):
    return {field["name"]: field.get("value") for field in resource.get("fields", [])}


def schema_resource(client, resource, implementation, values):
    schema = next(
        (
            item
            for item in client.api(f"/{resource}/schema")
            if item.get("implementation") == implementation
        ),
        None,
    )
    if not schema:
        raise ServiceError(
            "This app version does not offer the expected integration schema."
        )
    result = copy.deepcopy(schema)
    result.pop("id", None)
    available = {field["name"] for field in result.get("fields", [])}
    if not set(values).issubset(available):
        raise ServiceError(
            "This app's integration fields have changed. Configure this connection in the app."
        )
    for field in result["fields"]:
        if field["name"] in values:
            field["value"] = values[field["name"]]
    return result


class Operations:
    def __init__(self, store, storage, key_directory):
        self.store, self.storage, self.key_directory = store, storage, key_directory
        self.plans = {}
        self.lock = threading.RLock()

    def client(self, service):
        config = config_for(self.store, service, self.key_directory)
        if not config:
            raise ServiceError(f"Connect {SERVICES[service]['name']} first.")
        return Client(service, config)

    def profiles(self):
        result = {}
        for name in ("radarr", "sonarr"):
            try:
                client = self.client(name)
                result[name] = {
                    "profiles": [
                        {"id": item["id"], "name": item["name"]}
                        for item in client.api("/qualityprofile")
                    ]
                }
            except ServiceError as error:
                result[name] = {"profiles": [], "error": str(error)}
        return result

    def action(self, key, options, execute=False):
        locations = self.store.data["locations"]
        if key == "folders":
            values = list(locations.values()) + [
                "/data/torrents/movies",
                "/data/torrents/tv",
                "/data/torrents/incomplete",
            ]
            missing = [
                value for value in values if not self.storage.inspect(value)["exists"]
            ]
            if any(not self.storage.inspect(value)["writable"] for value in values):
                raise ServiceError(
                    "The panel cannot write to these folders. Check ownership on the host."
                )
            if execute:
                for value in missing:
                    self.storage.mkdir(value)
            return (
                "create" if missing else "exists",
                "Create missing library and download folders"
                if missing
                else "Library and download folders already exist",
            )
        kind, _, target = key.partition(":")
        if kind == "root":
            path = locations["movies" if target == "radarr" else "tv"]
            client = self.client(target)
            existing = client.api("/rootfolder")
            if any(
                item.get("path", "").rstrip("/") == path.rstrip("/")
                for item in existing
            ):
                return "exists", path
            if execute:
                if not self.storage.inspect(path)["exists"]:
                    raise ServiceError(
                        "Create the library folder before adding its root folder."
                    )
                client.api("/rootfolder", method="POST", payload={"path": path})
            return (
                "create",
                path + " (new root folder; existing libraries stay in place)",
            )
        if kind == "library":
            client = self.client("jellyfin")
            path = locations[target]
            libraries = client.request("/Library/VirtualFolders")
            if any(path in item.get("Locations", []) for item in libraries):
                return "exists", path
            title = "Movies" if target == "movies" else "TV Shows"
            if any(
                item.get("Name", "").casefold() == title.casefold()
                for item in libraries
            ):
                raise ServiceError(
                    f"Jellyfin already has a library named {title}. Add the new location in Jellyfin to keep its settings."
                )
            if execute:
                query = urlencode(
                    {
                        "name": title,
                        "collectionType": "movies" if target == "movies" else "tvshows",
                        "refreshLibrary": "true",
                    }
                )
                client.request(
                    "/Library/VirtualFolders?" + query,
                    method="POST",
                    payload={"LibraryOptions": {"PathInfos": [{"Path": path}]}},
                )
            return "create", path + " (new Jellyfin library)"
        if kind == "category":
            client = self.client("qbittorrent")
            client.login()
            categories = client.request("/api/v2/torrents/categories")
            path = f"/data/torrents/{target}"
            if target in categories:
                if categories[target].get("savePath", "").rstrip("/") != path:
                    raise ServiceError(
                        f"The {target} category already uses another folder. Review it in qBittorrent before continuing."
                    )
                return "exists", path
            if execute:
                client.request(
                    "/api/v2/torrents/createCategory",
                    method="POST",
                    form={"category": target, "savePath": path},
                    raw=True,
                )
            return "create", f"{target} → {path}"
        if kind == "download":
            client = self.client(target)
            qbit = self.client("qbittorrent")
            url = urlsplit(qbit.url)
            port = url.port or (443 if url.scheme == "https" else 80)
            existing = client.api("/downloadclient")
            for item in existing:
                values = fields(item)
                if (
                    item.get("implementation") == "QBittorrent"
                    and values.get("host") == url.hostname
                    and values.get("port") == port
                ):
                    return (
                        "exists",
                        "Existing qBittorrent connection kept; its category and credentials are unchanged",
                    )
            category = "movies" if target == "radarr" else "tv"
            category_status, _ = self.action("category:" + category, options)
            if execute and category_status != "exists":
                raise ServiceError(
                    "The download category changed since review. Review setup again before adding the client."
                )
            values = {
                "host": url.hostname,
                "port": port,
                "useSsl": url.scheme == "https",
                "urlBase": url.path,
                "username": qbit.config["username"],
                "password": qbit.config["password"],
                "movieCategory" if target == "radarr" else "tvCategory": category,
            }
            payload = schema_resource(client, "downloadclient", "QBittorrent", values)
            payload.update(name="Media Stack qBittorrent", enable=True, priority=1)
            if any(item.get("name") == payload["name"] for item in existing):
                raise ServiceError(
                    "A Media Stack download client already exists at another address. Review it in the app."
                )
            if execute:
                client.api("/downloadclient/test", method="POST", payload=payload)
                client.api("/downloadclient", method="POST", payload=payload)
            return "create", f"qBittorrent with the {category} category"
        if kind == "indexer":
            client = self.client("prowlarr")
            downstream = self.client(target)
            implementation = "Radarr" if target == "radarr" else "Sonarr"
            existing = client.api("/applications")
            if any(
                item.get("implementation") == implementation
                and fields(item).get("baseUrl", "").rstrip("/") == downstream.url
                for item in existing
            ):
                return "exists", "Existing Prowlarr app connection kept"
            payload = schema_resource(
                client,
                "applications",
                implementation,
                {
                    "prowlarrUrl": client.url,
                    "baseUrl": downstream.url,
                    "apiKey": downstream.config["api_key"],
                },
            )
            payload.update(
                name=f"Media Stack {implementation}", syncLevel="fullSync", tags=[]
            )
            if any(item.get("name") == payload["name"] for item in existing):
                raise ServiceError(
                    "A Media Stack indexer connection already exists at another address. Review it in Prowlarr."
                )
            if execute:
                client.api("/applications/test", method="POST", payload=payload)
                client.api("/applications", method="POST", payload=payload)
            return "create", f"Sync Prowlarr indexers to {implementation}"
        if kind == "request":
            client = self.client("seerr")
            downstream = self.client(target)
            url = urlsplit(downstream.url)
            existing = client.request(f"/api/v1/settings/{target}")
            if any(
                item.get("hostname") == url.hostname
                and item.get("port")
                == (url.port or (443 if url.scheme == "https" else 80))
                for item in existing
            ):
                return (
                    "exists",
                    "Existing Seerr connection kept; its quality profile stays unchanged",
                )
            profile = next(
                (
                    item
                    for item in downstream.api("/qualityprofile")
                    if item["id"] == options.get(f"{target}_profile")
                ),
                None,
            )
            if not profile:
                raise ServiceError(
                    f"Choose a quality profile for {SERVICES[target]['name']} before linking Seerr."
                )
            payload = {
                "name": f"Media Stack {SERVICES[target]['name']}",
                "hostname": url.hostname,
                "port": url.port or (443 if url.scheme == "https" else 80),
                "baseUrl": url.path,
                "apiKey": downstream.config["api_key"],
                "useSsl": url.scheme == "https",
                "activeProfileId": profile["id"],
                "activeProfileName": profile["name"],
                "activeDirectory": locations["movies" if target == "radarr" else "tv"],
                "tags": [],
                "is4k": False,
                "isDefault": not any(
                    item.get("isDefault") and not item.get("is4k") for item in existing
                ),
                "syncEnabled": True,
                "preventSearch": False,
                "tagRequests": False,
                "overrideRule": [],
                "minimumAvailability": "released",
                "seriesType": "standard",
                "animeSeriesType": "anime",
                "enableSeasonFolders": True,
                "monitorNewItems": "all",
            }
            if execute:
                client.request(
                    f"/api/v1/settings/{target}/test", method="POST", payload=payload
                )
                client.request(
                    f"/api/v1/settings/{target}", method="POST", payload=payload
                )
            return (
                "create",
                f"Use {profile['name']} for new {('movie' if target == 'radarr' else 'TV')} requests",
            )
        raise ValueError("Unknown setup action.")

    def preview(self, options):
        actions = []
        if options.get("folders"):
            actions += [
                ("folders", "Prepare shared folders"),
                ("root:radarr", "Radarr movie folder"),
                ("root:sonarr", "Sonarr TV folder"),
            ]
        if options.get("libraries"):
            actions += [
                ("library:movies", "Jellyfin movie library"),
                ("library:tv", "Jellyfin TV library"),
            ]
        if options.get("downloads"):
            actions += [
                ("category:movies", "Movie download category"),
                ("category:tv", "TV download category"),
                ("download:radarr", "Radarr → qBittorrent"),
                ("download:sonarr", "Sonarr → qBittorrent"),
            ]
        if options.get("indexers"):
            actions += [
                ("indexer:radarr", "Prowlarr → Radarr"),
                ("indexer:sonarr", "Prowlarr → Sonarr"),
            ]
        if options.get("requests"):
            actions += [
                ("request:radarr", "Seerr → Radarr"),
                ("request:sonarr", "Seerr → Sonarr"),
            ]
        if not actions:
            raise ValueError("Choose at least one setup task to review.")
        steps = []
        for key, label in actions:
            try:
                status, detail = self.action(key, options)
            except (ServiceError, OSError) as error:
                status, detail = (
                    "blocked",
                    str(error)
                    if isinstance(error, ServiceError)
                    else "Cannot access the data folder. Check its permissions.",
                )
            steps.append(
                {"id": key, "label": label, "status": status, "detail": detail}
            )
        token = secrets.token_urlsafe(24)
        with self.lock:
            self.plans = {
                key: plan
                for key, plan in self.plans.items()
                if plan["expires"] > time.monotonic()
            }
            if len(self.plans) >= 20:
                self.plans.clear()
            self.plans[token] = {
                "steps": steps,
                "options": options,
                "fingerprint": self.store.fingerprint(),
                "expires": time.monotonic() + 300,
            }
        return {
            "token": token,
            "steps": steps,
            "can_apply": any(step["status"] == "create" for step in steps),
        }

    def apply(self, token):
        with self.lock, self.store.lock:
            plan = self.plans.pop(token, None)
            if not plan or plan["expires"] < time.monotonic():
                raise ValueError("This review has expired. Review the changes again.")
            if plan["fingerprint"] != self.store.fingerprint():
                raise ValueError(
                    "Connections or locations changed. Review the changes again."
                )
            results = []
            failed = False
            for step in plan["steps"]:
                result = dict(step)
                if step["status"] == "blocked":
                    results.append(result)
                    continue
                if failed:
                    result.update(
                        status="skipped",
                        detail="Stopped after an earlier failure. Resolve it and review again.",
                    )
                else:
                    try:
                        if step["status"] == "exists":
                            status, detail = self.action(step["id"], plan["options"])
                            if status != "exists":
                                raise ServiceError(
                                    "An existing setting changed since review. Review the changes again."
                                )
                            result.update(status="kept", detail=detail)
                            results.append(result)
                            continue
                        # Recheck each resource before creating it, so retries do not duplicate connections.
                        status, detail = self.action(
                            step["id"], plan["options"], execute=True
                        )
                        result.update(
                            status="kept" if status == "exists" else "done",
                            detail=detail,
                        )
                        self.store.event(
                            step["label"]
                            + (
                                ": already configured"
                                if status == "exists"
                                else ": configured"
                            ),
                            "success",
                        )
                    except (ServiceError, OSError) as error:
                        failed = True
                        result.update(
                            status="failed",
                            detail=str(error)
                            if isinstance(error, ServiceError)
                            else "Cannot write the data folder. Check permissions.",
                        )
                        self.store.event(
                            step["label"] + ": failed; review the connection", "warning"
                        )
                results.append(result)
            return {
                "steps": results,
                "complete": all(item["status"] in ("done", "kept") for item in results),
            }
