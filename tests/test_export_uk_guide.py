import importlib.util
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

spec = importlib.util.spec_from_file_location("export_uk_guide", Path(__file__).resolve().parents[1] / "ops/export_uk_guide.py")
guide = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guide)


class GuideExportTests(unittest.TestCase):
    def test_unmapped_dummy_cards_are_removed_but_real_news_with_a_channel_title_is_kept(self):
        body = b'<tv><channel id="1"><icon src="http://dispatcharr/logo.png"/></channel><channel id="2"/><programme channel="1"><title>BBC News</title></programme><programme channel="2"><title>Channel 4</title></programme></tv>'
        root = ET.fromstring(guide.clean_guide(body, {"1"}))
        self.assertEqual(len(root.findall("channel")), 2)
        self.assertEqual([p.findtext("title") for p in root.findall("programme")], ["BBC News"])
        self.assertEqual(root.find("programme/icon").get("src"), "http://dispatcharr/logo.png")
