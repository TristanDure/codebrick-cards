from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.repair_legacy_metadata import build_plan, resolve_section


class LegacyMetadataRepairTests(unittest.TestCase):
    def test_unique_anchor_wins_over_stale_index(self):
        sections = [
            {"sectionIndex": 1, "anchor": "old", "heading": "Old"},
            {"sectionIndex": 2, "anchor": "stable", "heading": "Current"},
        ]
        result = resolve_section({"sectionAnchor": "stable", "sectionIndex": 1, "section": "Old"}, sections)
        self.assertEqual(result["sectionIndex"], 2)

    def test_duplicate_anchor_requires_heading_disambiguation(self):
        sections = [
            {"sectionIndex": 1, "anchor": "same", "heading": "A"},
            {"sectionIndex": 2, "anchor": "same", "heading": "B"},
        ]
        self.assertIsNone(resolve_section({"sectionAnchor": "same", "section": "Changed"}, sections))
        result = resolve_section({"sectionAnchor": "same", "section": "B"}, sections)
        self.assertEqual(result["sectionIndex"], 2)

    def test_build_plan_only_marks_flagged_cards_and_keeps_unresolved(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / ".cache").mkdir()
            (root / "data/cards").mkdir(parents=True)
            html = '<main class="vp-doc"><h1>Fixture</h1><h2 id="stable">Current</h2><p>body</p></main>'
            cache = root / ".cache" / "fixture.html"
            cache.write_text(html, encoding="utf-8")
            (root / "data/articles.json").write_text(json.dumps({"articles": [{
                "url": "https://example.test/os-blog/fixture", "cache": ".cache/fixture.html"
            }]}), encoding="utf-8")
            cards = [
                {"id": "repair", "articleUrl": "https://example.test/os-blog/fixture#stable", "sectionAnchor": "stable", "section": "Old", "sourceSectionRemoved": True},
                {"id": "untouched", "articleUrl": "https://example.test/os-blog/fixture", "sectionAnchor": "stable", "section": "Current"},
            ]
            (root / "data/cards/cards.json").write_text(json.dumps({"cards": cards}), encoding="utf-8")
            _, summary = build_plan(root)
            self.assertEqual(summary["flaggedCardCount"], 1)
            self.assertEqual(summary["repairableCardCount"], 1)
            self.assertEqual(summary["unresolvedCardCount"], 0)
            self.assertEqual(summary["changes"][0]["toSectionIndex"], 1)


if __name__ == "__main__":
    unittest.main()
