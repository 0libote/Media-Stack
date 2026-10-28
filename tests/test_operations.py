import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from control.operations import Operations
from control.state import Store
from control.storage import Storage
from fake_services import FakeServices, KEY, PASSWORD


class OperationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.upstream = FakeServices()
        self.addCleanup(self.upstream.close)
        root = Path(self.temp.name)
        self.storage = Storage(root / "data")
        self.storage.root.mkdir()
        self.store = Store(root / "state")
        self.store.data["services"] = {
            name: self.upstream.config(name)
            for name in (
                "jellyfin",
                "seerr",
                "radarr",
                "sonarr",
                "prowlarr",
                "qbittorrent",
            )
        }
        self.store.save()
        self.operations = Operations(self.store, self.storage, root / "keys")
        self.options = {
            "folders": True,
            "libraries": True,
            "downloads": True,
            "indexers": True,
            "requests": True,
            "radarr_profile": 1,
            "sonarr_profile": 1,
        }

    def test_review_is_read_only_and_contains_no_credentials(self):
        plan = self.operations.preview(self.options)
        self.assertTrue(plan["can_apply"])
        self.assertTrue(all(step["status"] == "create" for step in plan["steps"]))
        self.assertFalse(self.upstream.writes)
        self.assertFalse((self.storage.root / "media").exists())
        for secret in (KEY, PASSWORD):
            self.assertNotIn(secret, json.dumps(plan))

    def test_complete_setup_and_retry_are_additive_and_idempotent(self):
        plan = self.operations.preview(self.options)
        result = self.operations.apply(plan["token"])
        self.assertTrue(result["complete"], result)
        self.assertTrue(all(item["status"] == "done" for item in result["steps"]))
        self.assertEqual(len(self.upstream.applications), 2)
        self.assertEqual(len(self.upstream.clients["radarr"]), 1)
        self.assertEqual(len(self.upstream.clients["sonarr"]), 1)
        self.assertEqual(len(self.upstream.libraries), 2)
        self.assertEqual(set(self.upstream.categories), {"movies", "tv"})
        self.assertTrue((self.storage.root / "media/movies").is_dir())
        self.assertEqual(
            self.upstream.requests["radarr"][0]["activeProfileName"], "HD-1080p"
        )
        self.assertEqual(
            self.upstream.requests["sonarr"][0]["activeDirectory"], "/data/media/tv"
        )
        before = len(self.upstream.writes)
        again = self.operations.preview(self.options)
        self.assertFalse(again["can_apply"])
        self.assertTrue(all(step["status"] == "exists" for step in again["steps"]))
        retried = self.operations.apply(again["token"])
        self.assertTrue(retried["complete"])
        self.assertEqual(len(self.upstream.writes), before)
        self.assertNotIn(KEY, json.dumps(result))
        self.assertNotIn(PASSWORD, json.dumps(result))

    def test_apply_token_is_single_use_and_expires(self):
        plan = self.operations.preview({"folders": True})
        self.operations.apply(plan["token"])
        with self.assertRaisesRegex(ValueError, "expired"):
            self.operations.apply(plan["token"])
        plan = self.operations.preview({"folders": True})
        self.operations.plans[plan["token"]]["expires"] = time.monotonic() - 1
        with self.assertRaisesRegex(ValueError, "expired"):
            self.operations.apply(plan["token"])

    def test_changed_connections_or_locations_invalidate_review(self):
        for field in ("locations", "services"):
            plan = self.operations.preview({"folders": True})
            if field == "locations":
                self.store.data["locations"]["movies"] = "/data/other/movies"
            else:
                self.store.data["services"]["radarr"]["api_key"] = "changed-test-key"
            with self.assertRaisesRegex(ValueError, "changed"):
                self.operations.apply(plan["token"])
        self.assertFalse(self.upstream.writes)

    def test_existing_libraries_and_integrations_are_never_rewritten(self):
        self.operations.apply(self.operations.preview(self.options)["token"])
        self.upstream.clients["radarr"][0]["name"] = "My custom downloader"
        for field in self.upstream.clients["radarr"][0]["fields"]:
            if field["name"] == "movieCategory":
                field["value"] = "my-category"
        self.upstream.requests["radarr"][0]["activeProfileName"] = "My custom profile"
        previous = copy.deepcopy(self.upstream.clients)
        plan = self.operations.preview(self.options)
        self.operations.apply(plan["token"])
        self.assertEqual(self.upstream.clients, previous)
        self.assertEqual(
            self.upstream.requests["radarr"][0]["activeProfileName"],
            "My custom profile",
        )

    def test_existing_category_at_another_path_is_blocked(self):
        self.upstream.categories["movies"] = {"savePath": "/data/my-existing-downloads"}
        plan = self.operations.preview({"downloads": True})
        self.assertEqual(plan["steps"][0]["status"], "blocked")
        self.assertIn("already uses another folder", plan["steps"][0]["detail"])
        self.assertEqual(
            self.upstream.categories["movies"]["savePath"],
            "/data/my-existing-downloads",
        )
        self.assertFalse(self.upstream.writes)

    def test_blocked_category_prevents_its_client_but_keeps_unrelated_setup(self):
        self.upstream.categories["movies"] = {"savePath": "/outside/shared/movies"}
        plan = self.operations.preview({"downloads": True, "indexers": True})
        result = self.operations.apply(plan["token"])
        self.assertFalse(result["complete"])
        self.assertEqual(self.upstream.clients["radarr"], [])
        self.assertEqual(len(self.upstream.clients["sonarr"]), 1)
        self.assertEqual(len(self.upstream.applications), 2)
        self.assertEqual(self.upstream.categories["movies"]["savePath"], "/outside/shared/movies")
        blocked = next(step for step in result["steps"] if step["id"] == "download:radarr")
        self.assertEqual(blocked["status"], "blocked")
        self.assertIn("category", blocked["detail"])

    def test_category_changed_after_review_prevents_client_creation(self):
        for existed in (False, True):
            with self.subTest(existed=existed):
                self.upstream.categories.clear()
                if existed:
                    self.upstream.categories["movies"] = {"savePath": "/data/torrents/movies"}
                plan = self.operations.preview({"downloads": True})
                self.upstream.categories["movies"] = {"savePath": "/outside/shared/movies"}
                result = self.operations.apply(plan["token"])
                self.assertFalse(result["complete"])
                self.assertEqual(self.upstream.clients["radarr"], [])

    def test_new_client_rechecks_category_immediately_before_writing(self):
        plan = self.operations.preview({"downloads": True})
        action = self.operations.action

        def changed_category(key, options, execute=False):
            if key == "download:radarr" and execute:
                self.upstream.categories["movies"] = {"savePath": "/outside/shared/movies"}
            return action(key, options, execute)

        with patch.object(self.operations, "action", side_effect=changed_category):
            result = self.operations.apply(plan["token"])
        self.assertFalse(result["complete"])
        self.assertEqual(self.upstream.clients["radarr"], [])

    def test_existing_library_name_does_not_get_duplicate(self):
        self.upstream.libraries = [
            {"Name": "Movies", "Locations": ["/existing/library"]}
        ]
        plan = self.operations.preview({"libraries": True})
        self.assertEqual(plan["steps"][0]["status"], "blocked")
        self.assertIn("already has a library", plan["steps"][0]["detail"])
        self.assertFalse(self.upstream.writes)

    def test_failure_stops_later_mutations_and_retry_detects_completed_work(self):
        plan = self.operations.preview(self.options)
        self.upstream.failures[("radarr", "/api/v3/rootfolder")] = 503
        result = self.operations.apply(plan["token"])
        self.assertFalse(result["complete"])
        self.assertEqual(result["steps"][0]["status"], "done")
        self.assertEqual(result["steps"][1]["status"], "failed")
        self.assertTrue(
            all(step["status"] == "skipped" for step in result["steps"][2:])
        )
        self.assertFalse(self.upstream.writes)
        del self.upstream.failures[("radarr", "/api/v3/rootfolder")]
        plan = self.operations.preview(self.options)
        self.assertEqual(plan["steps"][0]["status"], "exists")
        self.assertTrue(self.operations.apply(plan["token"])["complete"])

    def test_quality_profile_is_an_explicit_choice(self):
        plan = self.operations.preview({"requests": True})
        self.assertTrue(all(step["status"] == "blocked" for step in plan["steps"]))
        self.assertFalse(plan["can_apply"])
        self.assertFalse(self.upstream.writes)

    def test_missing_connection_is_actionable(self):
        self.store.data["services"].pop("prowlarr")
        plan = self.operations.preview({"indexers": True})
        self.assertTrue(
            all(
                step["status"] == "blocked"
                and "Connect Prowlarr first" in step["detail"]
                for step in plan["steps"]
            )
        )

    def test_no_qbit_global_preferences_are_changed(self):
        self.operations.apply(self.operations.preview(self.options)["token"])
        self.assertTrue(
            all("setPreferences" not in path for _, path, _ in self.upstream.writes)
        )

    def test_existing_setting_removed_after_review_requires_new_review(self):
        self.operations.apply(self.operations.preview(self.options)["token"])
        plan = self.operations.preview({"indexers": True})
        self.upstream.applications.clear()
        before = len(self.upstream.writes)
        result = self.operations.apply(plan["token"])
        self.assertFalse(result["complete"])
        self.assertEqual(result["steps"][0]["status"], "failed")
        self.assertEqual(len(self.upstream.writes), before)


if __name__ == "__main__":
    unittest.main()
