from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts import import_review_batches
from scripts.sync_sources import parse_article, sections
from tests.test_sync import ARTICLE_HTML, ARTICLE_URL


class ReviewBatchImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        cache_path = self.root / ".cache" / "html" / "offline.html"
        cache_path.parent.mkdir(parents=True)
        cache_path.write_text(ARTICLE_HTML, encoding="utf-8")
        self.cache_relative = cache_path.relative_to(self.root).as_posix()
        parsed_sections = sections(parse_article(ARTICLE_HTML, ARTICLE_URL))
        self.section = parsed_sections[0]
        source_unit = self.section["sourceUnits"][0]["units"][0]
        self.unit_id = source_unit["id"]
        unit = {
            "knowledgeUnitId": self.unit_id,
            "sourceId": "os",
            "articleTitle": "Offline fixture",
            "articleUrl": ARTICLE_URL,
            "sectionIndex": self.section["sectionIndex"],
            "sectionHeadingPath": self.section["headingPath"],
            "sectionAnchor": self.section["anchor"],
            "blockIndex": source_unit["blockIndex"],
            "unitIndex": source_unit["unitIndex"],
            "tag": source_unit["tag"],
            "text": source_unit["text"],
            "href": source_unit["href"],
            "title": source_unit["title"],
            "src": source_unit["src"],
            "alt": source_unit["alt"],
            "cardIds": [],
        }
        self.unit = unit
        self._write_json("data/articles.json", {"articles": [{
            "sourceId": "os", "title": "Offline fixture", "url": ARTICLE_URL,
            "cache": self.cache_relative, "contentHash": "fixture-hash",
        }]})
        self._write_json("data/knowledge-units.json", {"units": [unit]})
        self._write_json("data/cards/cards.json", {"cards": []})
        self.row = {
            "sourceId": "os",
            "articleUrl": ARTICLE_URL,
            "sectionAnchor": self.section["anchor"],
            "sectionIndex": self.section["sectionIndex"],
            "sourceKnowledgeUnitIds": [self.unit_id],
            "question": "What does the source state about this topic?",
            "answer": source_unit["text"],
            "evidence": {
                "excerpt": source_unit["text"],
                "locator": f"{self.section['heading']} · {self.unit_id}",
                "cachePath": self.cache_relative,
            },
            "tags": ["fixture"],
            "status": "needs-review",
        }
        self.batch_path = self.root / "data" / "review-batches" / "fixture.json"
        self.batch_path.parent.mkdir(parents=True)
        self._write_json(self.batch_path.relative_to(self.root), [self.row])

    def tearDown(self):
        self.temp.cleanup()

    def _write_json(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def _plan(self):
        return import_review_batches.plan_import(self.root, [self.batch_path])

    def test_valid_proposal_is_imported_as_needs_review_with_source_text(self):
        result = self._plan()
        self.assertEqual(result["errors"], [])
        self.assertEqual(len(result["new"]), 1)
        card = result["new"][0]
        self.assertEqual(card["knowledgeUnitIds"], [self.unit_id])
        self.assertEqual(card["status"], "needs-review")
        self.assertEqual(card["provenance"]["sourceExcerpt"], self.unit["text"])
        self.assertEqual(card["provenance"]["evidenceExcerptMatchesSource"], True)

    def test_rejects_parent_traversal_cache_path(self):
        self.row["evidence"]["cachePath"] = "../outside.html"
        self._write_json(self.batch_path.relative_to(self.root), [self.row])
        result = self._plan()
        self.assertEqual(len(result["new"]), 0)
        self.assertTrue(any("project-relative" in issue for issue in result["errors"][0]["errors"]))

    def test_rejects_existing_cache_file_from_another_article(self):
        other = self.root / ".cache" / "html" / "other.html"
        other.write_text(ARTICLE_HTML, encoding="utf-8")
        self.row["evidence"]["cachePath"] = other.relative_to(self.root).as_posix()
        self._write_json(self.batch_path.relative_to(self.root), [self.row])
        result = self._plan()
        self.assertEqual(len(result["new"]), 0)
        self.assertTrue(any("does not match the article cache" in issue for issue in result["errors"][0]["errors"]))

    def test_rejects_duplicate_snapshot_unit_ids(self):
        self._write_json("data/knowledge-units.json", {"units": [self.unit, self.unit]})
        with self.assertRaisesRegex(ValueError, "duplicate knowledge-unit ID"):
            self._plan()

    def test_rejects_duplicate_existing_card_ids(self):
        self._write_json("data/cards/cards.json", {"cards": [{"id": "same"}, {"id": "same"}]})
        with self.assertRaisesRegex(ValueError, "duplicate card ID"):
            self._plan()

    def test_generic_template_candidates_are_rejected(self):
        self.row["question"] = "请解释本节关键内容"
        self._write_json(self.batch_path.relative_to(self.root), [self.row])
        result = self._plan()
        self.assertEqual(len(result["new"]), 0)
        self.assertTrue(any("generic template" in issue for issue in result["errors"][0]["errors"]))


if __name__ == "__main__":
    unittest.main()
