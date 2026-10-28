import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "iptv_org_layout", Path(__file__).resolve().parents[1] / "ops/iptv_org_layout.py"
)
layout = importlib.util.module_from_spec(spec)
spec.loader.exec_module(layout)


class IPTVLayoutTests(unittest.TestCase):
    def test_uk_classification_keeps_broadcast_feeds_and_uk_origin_channels(self):
        ids = layout.uk_feed_ids(
            '#EXTM3U\n#EXTINF:-1 tvg-id="Cops.us@UK",Cops\nhttps://example.org/live.m3u8\n'
        )
        metadata = {"BBCOne.uk": {"country": "UK"}, "France24.fr": {"country": "FR"}}
        self.assertTrue(layout.is_uk("Cops.us@UK", ids, metadata))
        self.assertTrue(layout.is_uk("BBCOne.uk@London", ids, metadata))
        self.assertFalse(layout.is_uk("France24.fr@French", ids, metadata))
        with self.assertRaises(ValueError):
            layout.uk_feed_ids("<html>Unavailable</html>")

    def test_uk_numbers_preserve_existing_slots_and_stay_before_international(self):
        used = {1, 2, 3, 1000}
        self.assertEqual(layout.choose_number("Channel4.uk@UK", used), 4)
        self.assertEqual(layout.choose_number("BBCOne.uk@London", used), 1001)
        self.assertEqual(layout.choose_number("Another.uk@SD", used), 1002)
        self.assertEqual(layout.choose_number("Channel4.uk@HD", used), 1003)
        self.assertTrue(all(number < 10000 for number in used))

    def test_guide_matching_prefers_region_and_accepts_hd_identifiers(self):
        available = {"BBCOneSouth.uk", "BBCOne.uk", "BBCThreeHD.uk"}
        self.assertEqual(
            layout.guide_id("BBCOne.uk@SouthHD", available), "BBCOneSouth.uk"
        )
        self.assertEqual(layout.guide_id("BBCThree.uk@SD", available), "BBCThreeHD.uk")
        self.assertIsNone(layout.guide_id("Unknown.us@SD", available))

    def test_international_sort_keeps_countries_together_then_sorts_names(self):
        metadata = {"A.fr": {"country": "FR"}, "B.fr": {"country": "FR"}, "C.us": {"country": "US"}}
        countries = {"FR": "France", "US": "United States"}
        rows = [("B.fr@HD", "Zulu"), ("A.fr@HD", "Alpha"), ("C.us@HD", "News")]
        ordered = sorted(rows, key=lambda row: layout.international_key(*row, metadata, countries))
        self.assertEqual(ordered, [rows[2], rows[1], rows[0]])
        self.assertEqual(layout.country_info("Missing@SD", metadata, countries), ("", "Other countries"))

    def test_primary_lineup_uses_one_feed_and_keeps_variants_after_the_main_guide(self):
        records = [
            {"id": 1, "tvg_id": "BBCOneSouth.uk", "name": "BBC One South", "auto_created_by_id": None},
            {"id": 2, "tvg_id": "BBCOne.uk@London", "name": "BBC One London HD", "auto_created_by_id": 3},
            {"id": 3, "tvg_id": "TinyPop.uk@Plus1", "name": "Tiny Pop +1", "auto_created_by_id": 3},
            {"id": 4, "tvg_id": "TinyPop.uk@SD", "name": "Tiny Pop", "auto_created_by_id": 3},
        ]
        plan, primary = layout.curated_uk(records)
        self.assertEqual(primary, {1, 4})
        self.assertEqual(plan[1], {"channel_number": 1, "name": "BBC One"})
        self.assertEqual(plan[4]["channel_number"], 206)
        self.assertTrue(all(plan[pk]["channel_number"] >= 10000 for pk in [2, 3]))

    def test_main_guide_aliases_resolve_real_regional_and_rebranded_ids(self):
        available = {"Channel4South.uk", "5.uk", "QVCUK.uk", "GreatMovies.uk"}
        for feed, expected in [("Channel4.uk@UK", "Channel4South.uk"), ("Channel5.uk@SD", "5.uk"), ("QVC.uk@SD", "QVCUK.uk"), ("GREATmovies.uk@UK", "GreatMovies.uk")]:
            self.assertEqual(layout.guide_id(feed, available), expected)
