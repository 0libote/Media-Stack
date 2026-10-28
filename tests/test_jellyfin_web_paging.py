import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "jellyfin_web_paging", Path(__file__).resolve().parents[1] / "ops/jellyfin_web_paging.py"
)
paging = importlib.util.module_from_spec(spec)
spec.loader.exec_module(paging)


class PagingTests(unittest.TestCase):
    def test_known_workarounds_are_idempotent(self):
        for _, _, old, new in paging.PATCHES:
            body = "before;" + old + "after;"
            repaired = paging.patch_text(body, old, new)
            self.assertIn(new, repaired)
            self.assertEqual(paging.patch_text(repaired, old, new), repaired)

    def test_unrecognised_or_ambiguous_code_is_rejected(self):
        for _, _, old, new in paging.PATCHES:
            for body in ["different build", old + old]:
                with self.assertRaises(ValueError):
                    paging.patch_text(body, old, new)
