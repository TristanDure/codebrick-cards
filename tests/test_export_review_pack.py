from __future__ import annotations

import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from scripts import export_review_pack as exporter
from scripts import import_knowledge_reviews as review_importer
from scripts import sync_sources


class ExportReviewPackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "data/cards").mkdir(parents=True)
        (self.root / "exports").mkdir()
        self.units = [
            {
                "knowledgeUnitId": "0123456789abcdef", "sourceId": "os",
                "articleTitle": "标题 <script>alert('x')</script>",
                "articleUrl": "https://example.test/os/article.html#sec",
                "sectionIndex": 2, "sectionHeadingPath": "章节 <重点>", "sectionAnchor": "sec",
                "blockIndex": 3, "unitIndex": 1, "tag": "p", "href": "", "title": "",
                "src": "", "alt": "", "text": "原文 <img src=x onerror=alert(1)> & 'quote'",
                "cardIds": ["fedcba9876543210"], "status": "mapped-candidate-unreviewed",
                "presentInCurrentSource": True, "machineMappingStatus": "mapped-candidate-unreviewed",
                "reviewSourceSha256": "", "bodySha256": "", "reviewerDecision": "pending",
            },
            {
                "knowledgeUnitId": "aaaaaaaaaaaaaaaa", "sourceId": "co",
                "articleTitle": "Other title", "articleUrl": "https://example.test/co/other.html",
                "sectionHeadingPath": "Other", "text": "different source text", "cardIds": [],
                "status": "candidate-unreviewed", "reviewerDecision": "pending",
            },
            {
                "knowledgeUnitId": "bbbbbbbbbbbbbbbb", "sourceId": "os",
                "articleTitle": "Reviewed", "articleUrl": "https://example.test/os/article.html",
                "sectionHeadingPath": "Done", "text": "not pending", "cardIds": [],
                "status": "reviewed", "reviewerDecision": "accepted",
            },
        ]
        self.cards = [{
            "id": "fedcba9876543210", "question": "Q <b>literal</b>", "answer": "A & B",
            "status": "needs-review", "knowledgeUnitReviewStatus": "candidate-unreviewed",
            "knowledgeUnitIds": ["0123456789abcdef"],
        }]
        self.articles = [
            {"sourceId": "os", "title": self.units[0]["articleTitle"],
             "url": "https://example.test/os/article.html", "cache": ".cache/os/abc123.html",
             "contentHash": "article-hash"},
            {"sourceId": "co", "title": "Other title", "url": "https://example.test/co/other.html",
             "cache": ".cache/co/def456.html", "contentHash": "other-hash"},
        ]
        self._write("data/knowledge-units.json", {"units": self.units})
        self._write("data/cards/cards.json", {"cards": self.cards})
        self._write("data/articles.json", {"articles": self.articles})

    def tearDown(self):
        self.temp.cleanup()

    def _write(self, relative: str, value):
        (self.root / relative).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def _build(self, **kwargs):
        return exporter.build_review_pack(self.root, **kwargs)

    def _add_verified_article(self, paragraph_count=2, paragraph_chars=32):
        url = "https://example.test/os/verified.html"
        raw = (
            '<main class="vp-doc"><h1>Verified title</h1><h2 id="verified">Verified section</h2>'
            + "".join(f"<p>{str(index + 1) + ':' + ('x' * paragraph_chars)}</p>" for index in range(paragraph_count))
            + "</main>"
        )
        cache = self.root / ".cache/os/verified.html"
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(raw, encoding="utf-8")
        parsed = sync_sources.parse_article(raw, url)
        article_hash = hashlib.sha256(
            json.dumps(parsed["blocks"], ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        section = sync_sources.sections(parsed)[0]
        for block in section["sourceUnits"]:
            for source_unit in block["units"]:
                self.units.append({
                    "knowledgeUnitId": source_unit["id"], "sourceId": "os",
                    "articleTitle": parsed["title"], "articleUrl": url,
                    "sectionIndex": section["sectionIndex"],
                    "sectionHeadingPath": section["headingPath"], "sectionAnchor": section["anchor"],
                    "blockIndex": source_unit["blockIndex"], "unitIndex": source_unit["unitIndex"],
                    "tag": source_unit["tag"], "href": source_unit.get("href", ""), "title": source_unit.get("title", ""),
                    "src": source_unit.get("src", ""), "alt": source_unit.get("alt", ""),
                    "text": source_unit["text"], "cardIds": [], "status": "candidate-unreviewed",
                    "presentInCurrentSource": True, "machineMappingStatus": "candidate-unreviewed",
                    "reviewerDecision": "pending",
                })
        self.articles.append({
            "sourceId": "os", "title": parsed["title"], "url": url,
            "cache": ".cache/os/verified.html", "contentHash": article_hash,
        })
        self._write("data/knowledge-units.json", {"units": self.units})
        self._write("data/articles.json", {"articles": self.articles})
        return url

    def test_pending_only_pack_is_small_and_separate_from_import_schema(self):
        pack = self._build()
        self.assertEqual(pack["schema"], "codebrick-offline-review-pack")
        self.assertNotEqual(pack["schema"], "codebrick-knowledge-unit-review-ledger")
        self.assertFalse(pack["importable"])
        self.assertEqual(pack["selection"]["limit"], 30)
        self.assertEqual([x["knowledgeUnitId"] for x in pack["items"]], ["0123456789abcdef", "aaaaaaaaaaaaaaaa"])
        template = pack["items"][0]["reviewTemplate"]
        self.assertEqual(template["decision"], "pending")
        self.assertEqual(template["reviewer"], "")
        self.assertEqual(template["acceptedCardIds"], [])

    def test_offline_pack_is_rejected_by_decision_ledger_importer(self):
        pack = self._build(limit=1)
        output = self.root / "exports/not-a-decision-ledger.json"
        output.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(review_importer.ImportValidationError, "version-2"):
            review_importer._validate_export(output)

    def test_input_source_and_text_hashes_are_reproducible(self):
        pack = self._build(limit=1)
        paths = {"knowledgeUnits": "data/knowledge-units.json", "cards": "data/cards/cards.json", "articles": "data/articles.json"}
        for key, relative in paths.items():
            self.assertEqual(pack["inputs"]["sha256"][key], hashlib.sha256((self.root / relative).read_bytes()).hexdigest())
        item = pack["items"][0]
        self.assertEqual(item["hashes"]["textSha256"], hashlib.sha256(item["originalText"].encode("utf-8")).hexdigest())
        self.assertEqual(item["hashes"]["sourceSha256"], exporter._review_source_sha256(self.units[0]))

    def test_article_round_robin_sampling_spreads_first_round_across_articles(self):
        extra = []
        for number in (1, 2):
            clone = dict(self.units[0])
            clone["knowledgeUnitId"] = f"os-unit-{number:04d}"
            clone["text"] = f"additional os unit {number}"
            clone["cardIds"] = []
            extra.append(clone)
        os_unit = self.units[0]
        co_unit = self.units[1]
        self.units[:] = [os_unit, *extra, co_unit, self.units[2]]
        self._write("data/knowledge-units.json", {"units": self.units})
        pack = self._build(limit=2, sampling_mode="article-round-robin")
        self.assertEqual(pack["selection"]["samplingMode"], "article-round-robin")
        self.assertEqual(pack["selection"]["sampledArticleCount"], 2)
        self.assertEqual([item["sourceId"] for item in pack["items"]], ["os", "co"])
        self.assertEqual(self._build(limit=1)["items"][0]["sourceId"], "os")

    def test_cli_accepts_article_round_robin_and_reports_selection_metadata(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = exporter.main([
                "--root", str(self.root), "--output", "exports/round-robin.json",
                "--sampling-mode", "article-round-robin",
            ])
        self.assertEqual(result, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["samplingMode"], "article-round-robin")
        self.assertEqual(payload["sampledArticleCount"], 2)
        self.assertFalse(payload["written"])
        self.assertFalse((self.root / "exports/round-robin.json").exists())

    def test_unknown_sampling_mode_is_rejected(self):
        with self.assertRaisesRegex(exporter.ReviewPackError, "sampling_mode"):
            self._build(sampling_mode="random")

    def test_source_and_article_filter_semantics(self):
        self.assertEqual(self._build(source="os")["selection"]["pendingTotalBeforePagination"], 1)
        self.assertEqual(self._build(article_filter="https://example.test/os/article.html#other")["selection"]["pendingTotalBeforePagination"], 1)
        self.assertEqual(self._build(article_filter="abc123")["items"][0]["knowledgeUnitId"], "0123456789abcdef")
        self.assertEqual(self._build(article_filter="0123456789abcdef")["selection"]["pendingTotalBeforePagination"], 1)
        self.assertEqual(self._build(article_filter="SCRIPT>alert")["selection"]["pendingTotalBeforePagination"], 1)

    def test_offset_limit_and_linked_evidence(self):
        pack = self._build(limit=1, offset=1)
        self.assertEqual(pack["selection"]["pendingTotalBeforePagination"], 2)
        self.assertEqual(pack["items"][0]["knowledgeUnitId"], "aaaaaaaaaaaaaaaa")
        item = self._build(limit=1)["items"][0]
        self.assertEqual(item["originalText"], self.units[0]["text"])
        self.assertEqual(item["locator"]["sectionHeadingPath"], "章节 <重点>")
        self.assertEqual(item["cards"][0]["question"], "Q <b>literal</b>")
        self.assertEqual(item["cards"][0]["answer"], "A & B")
        self.assertEqual(item["cards"][0]["status"], "needs-review")

    def test_hash_verified_cache_context_highlights_focus_without_overclaiming(self):
        url = self._add_verified_article()
        pack = self._build(article_filter=url, limit=1)
        item = pack["items"][0]
        context = item["sourceContext"]
        self.assertEqual(context["status"], "verified")
        self.assertEqual(context["sourceUnitCount"], 2)
        self.assertTrue(context["focusUnitDisplayed"])
        rendered = exporter.render_html(pack)
        self.assertIn('class="source-unit focus"', rendered)
        self.assertNotIn("高亮对应知识单元）", rendered)

    def test_cached_article_parse_is_reused_across_units(self):
        url = self._add_verified_article(paragraph_count=3)
        original_parse = sync_sources.parse_article
        with patch.object(sync_sources, "parse_article", wraps=original_parse) as parse:
            pack = self._build(article_filter=url, limit=3)
        self.assertEqual(len(pack["items"]), 3)
        self.assertEqual(parse.call_count, 1)
        self.assertTrue(all(item["sourceContext"]["status"] == "verified" for item in pack["items"]))

    def test_content_hash_mismatch_excludes_source_context(self):
        url = self._add_verified_article()
        self.articles[-1]["contentHash"] = "not-the-article-hash"
        self._write("data/articles.json", {"articles": self.articles})
        item = self._build(article_filter=url, limit=1)["items"][0]
        self.assertEqual(item["sourceContext"]["status"], "content-hash-mismatch")
        self.assertEqual(item["sourceContext"]["sectionUnits"], [])

    def test_changed_unit_text_fails_locator_verification(self):
        url = self._add_verified_article()
        target = next(unit for unit in self.units if unit["articleUrl"] == url)
        target["text"] += " tampered"
        self._write("data/knowledge-units.json", {"units": self.units})
        item = self._build(article_filter=target["knowledgeUnitId"], limit=1)["items"][0]
        self.assertEqual(item["sourceContext"]["status"], "locator-mismatch")
        self.assertEqual(item["sourceContext"]["sectionUnits"], [])

    def test_cache_path_escape_is_unavailable(self):
        url = self._add_verified_article()
        self.articles[-1]["cache"] = "../outside.html"
        self._write("data/articles.json", {"articles": self.articles})
        item = self._build(article_filter=url, limit=1)["items"][0]
        self.assertEqual(item["sourceContext"]["status"], "unavailable")
        self.assertEqual(item["sourceContext"]["reason"], "article-cache-path-escapes-project")

    def test_truncated_context_reports_visible_and_total_units(self):
        url = self._add_verified_article(paragraph_count=20, paragraph_chars=1000)
        item = self._build(article_filter=url, limit=1)["items"][0]
        context = item["sourceContext"]
        self.assertTrue(context["sectionUnitsTruncated"])
        self.assertEqual(context["displayedUnitCount"], len(context["sectionUnits"]))
        self.assertLess(context["displayedUnitCount"], context["sourceUnitCount"])
        rendered = exporter.render_html({
            "inputs": {"sha256": {}}, "items": [item], "selection": {"itemCount": 1},
            "schema": exporter.PACK_SCHEMA, "notice": "test",
        })
        self.assertIn("未显示内容不能据此视为已审阅", rendered)
        self.assertIn(f"{context['displayedUnitCount']} / {context['sourceUnitCount']} 个单元", rendered)

    def test_html_escapes_injection_and_has_no_executable_remote_assets(self):
        rendered = exporter.render_html(self._build(limit=1))
        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", rendered)
        self.assertIn("Q &lt;b&gt;literal&lt;/b&gt;", rendered)
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("<img src=x", rendered)
        self.assertNotIn("<iframe", rendered)
        self.assertNotIn("<link", rendered)
        self.assertNotIn("<img src=\"https://", rendered)
        self.assertNotIn("<script src=", rendered)

    def test_default_cli_is_dry_run_and_does_not_write_or_change_inputs(self):
        before = {p: p.read_bytes() for p in self.root.rglob("*.json")}
        self.assertEqual(exporter.main(["--root", str(self.root), "--output", "exports/dry.json"]), 0)
        self.assertFalse((self.root / "exports/dry.json").exists())
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob("*.json")})

    def test_apply_writes_json_and_html_and_preserves_inputs(self):
        before = {p: p.read_bytes() for p in self.root.rglob("*.json")}
        self.assertEqual(exporter.main(["--root", str(self.root), "--output", "exports/pack.json", "--apply"]), 0)
        saved = json.loads((self.root / "exports/pack.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["schema"], "codebrick-offline-review-pack")
        self.assertFalse(saved["importable"])
        self.assertEqual(exporter.main(["--root", str(self.root), "--output", "exports/pack.html", "--apply"]), 0)
        self.assertIn("离线知识单元待审包", (self.root / "exports/pack.html").read_text(encoding="utf-8"))
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob("*.json") if p.name != "pack.json"})

    def test_existing_output_is_never_overwritten(self):
        output = self.root / "exports/existing.json"
        output.write_bytes(b"keep me")
        with self.assertRaisesRegex(exporter.ReviewPackError, "refusing to overwrite"):
            exporter.write_review_pack(self.root, self._build(), Path("exports/existing.json"))
        self.assertEqual(output.read_bytes(), b"keep me")

    def test_path_validation_rejects_inputs_bad_suffix_missing_parent_and_escape(self):
        pack = self._build()
        checks = [
            (Path("data/articles.json"), "input data file"),
            (Path("exports/out.txt"), ".json or .html"),
            (Path("missing/out.json"), "does not exist"),
            (self.root.parent / "outside.json", "inside the project root"),
        ]
        for path, message in checks:
            with self.subTest(path=path), self.assertRaisesRegex(exporter.ReviewPackError, message):
                exporter.write_review_pack(self.root, pack, path)

    def test_duplicate_unit_card_and_article_ids_are_rejected(self):
        self.units[1]["knowledgeUnitId"] = self.units[0]["knowledgeUnitId"]
        self._write("data/knowledge-units.json", {"units": self.units})
        with self.assertRaisesRegex(exporter.ReviewPackError, "duplicate knowledgeUnitId"):
            self._build()

    def test_duplicate_card_ids_are_rejected(self):
        self.cards.append(dict(self.cards[0]))
        self._write("data/cards/cards.json", {"cards": self.cards})
        with self.assertRaisesRegex(exporter.ReviewPackError, "duplicate id"):
            self._build()

    def test_duplicate_article_cache_ids_are_rejected(self):
        self.articles[1]["cache"] = ".cache/co/abc123.html"
        self._write("data/articles.json", {"articles": self.articles})
        with self.assertRaisesRegex(exporter.ReviewPackError, "duplicate article ID"):
            self._build()

    def test_duplicate_article_urls_are_rejected(self):
        self.articles.append(dict(self.articles[0]))
        self._write("data/articles.json", {"articles": self.articles})
        with self.assertRaisesRegex(exporter.ReviewPackError, "duplicate article URL"):
            self._build()

    def test_bad_source_and_pagination_are_rejected(self):
        with self.assertRaisesRegex(exporter.ReviewPackError, "unknown source"):
            self._build(source="nope")
        for kwargs, message in (({"offset": -1}, "offset"), ({"limit": 0}, "limit")):
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(exporter.ReviewPackError, message):
                self._build(**kwargs)

    def test_duplicate_json_keys_fail_closed(self):
        (self.root / "data/articles.json").write_text('{"articles":[],"articles":[]}', encoding="utf-8")
        with self.assertRaisesRegex(exporter.ReviewPackError, "duplicate JSON object key"):
            self._build()


if __name__ == "__main__":
    unittest.main()
