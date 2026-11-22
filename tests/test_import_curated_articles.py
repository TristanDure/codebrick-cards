from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import import_curated_articles as auditor
from scripts import sync_sources


class CuratedArticleAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.url = "https://example.test/os/article.html"
        self.cache_relative = ".cache/html/os/article.html"
        self.cache = self.root / self.cache_relative
        self.cache.parent.mkdir(parents=True)
        self.raw = (
            '<main class="vp-doc"><h1>Fixture Article</h1>'
            '<h2 id="concept">Concepts</h2>'
            '<p>First source fact describes a reliable concept.</p>'
            '<p>Second source fact gives a separate useful detail.</p>'
            '</main>'
        )
        self.cache.write_text(self.raw, encoding="utf-8")
        self.parsed = sync_sources.parse_article(self.raw, self.url)
        self.sections = sync_sources.sections(self.parsed)
        self.units = []
        for section in self.sections:
            for block in section["sourceUnits"]:
                for unit in block["units"]:
                    self.units.append({
                        "knowledgeUnitId": unit["id"],
                        "sourceId": "os",
                        "articleTitle": self.parsed["title"],
                        "articleUrl": self.url,
                        "sectionIndex": section["sectionIndex"],
                        "sectionHeadingPath": section["headingPath"],
                        "sectionAnchor": section["anchor"],
                        "blockIndex": unit["blockIndex"],
                        "unitIndex": unit["unitIndex"],
                        "tag": unit["tag"],
                        "text": unit["text"],
                        "href": unit.get("href", ""),
                        "title": unit.get("title", ""),
                        "src": unit.get("src", ""),
                        "alt": unit.get("alt", ""),
                        "cardIds": [],
                    })
        self.content_hash = hashlib.sha256(
            json.dumps(self.parsed["blocks"], ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        self.article_record = {
            "sourceId": "os", "title": self.parsed["title"], "url": self.url,
            "cache": self.cache_relative, "contentHash": self.content_hash,
        }
        self._write_json("data/articles.json", {"version": 1, "articles": [self.article_record]})
        self._write_json("data/knowledge-units.json", {"version": 2, "units": self.units})
        self.formal_path = self.root / "data/cards/cards.json"
        self._write_json("data/cards/cards.json", {"version": 1, "cards": []})
        self.proposal = self.valid_proposal()
        self.proposal_path = self.root / "data/curated/fixture.json"
        self._write_proposal()

    def tearDown(self):
        self.temp.cleanup()

    def _write_json(self, relative: str, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_proposal(self):
        self._write_json("data/curated/fixture.json", self.proposal)

    def valid_proposal(self):
        primary, context = self.units
        card_id = auditor.stable_card_id(self.url, [primary["knowledgeUnitId"]])
        return {
            "schema": auditor.SCHEMA,
            "version": auditor.VERSION,
            "article": {
                "sourceId": "os", "url": self.url, "cache": self.cache_relative,
                "contentHash": self.content_hash, "title": self.parsed["title"],
            },
            "sourceUnits": [
                {"knowledgeUnitId": primary["knowledgeUnitId"], "disposition": "card", "cardId": card_id},
                {"knowledgeUnitId": context["knowledgeUnitId"], "disposition": "context", "reason": "Provides context for the adjacent fact."},
            ],
            "cards": [{
                "cardId": card_id,
                "articleUrl": self.url,
                "front": "What does the first source fact establish?",
                "back": "It describes a reliable concept.",
                "knowledgeUnitIds": [primary["knowledgeUnitId"]],
            }],
        }

    def audit(self):
        return auditor.audit_article(self.proposal_path, self.root)

    def assert_error_code(self, code: str):
        result = self.audit()
        self.assertFalse(result["ok"], result)
        self.assertIn(code, {item["code"] for item in result["errors"]}, result["errors"])

    def test_malformed_article_metadata_returns_errors_without_raising(self):
        for bad in (None, [], "article", 42):
            with self.subTest(article=bad):
                self.proposal["article"] = bad
                self.proposal["metadata"] = {"supplementalSources": []}
                self._write_proposal()
                result = self.audit()
                self.assertFalse(result["ok"])
                self.assertTrue(any(e["code"] == "article_metadata" for e in result["errors"]))

    def test_valid_article_proposal_passes_and_reports_full_counts(self):
        result = self.audit()
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["counts"]["parsedKnowledgeUnits"], 2)
        self.assertEqual(result["counts"]["curatedSourceUnits"], 2)
        self.assertEqual(result["counts"]["cards"], 1)
        self.assertEqual(result["counts"]["dispositions"]["card"], 1)
        self.assertEqual(result["counts"]["dispositions"]["context"], 1)
        self.assertFalse(result["projectFilesWritten"])

    def test_card_id_is_deterministic_and_order_independent(self):
        ids = [unit["knowledgeUnitId"] for unit in self.units]
        self.assertEqual(auditor.stable_card_id(self.url, ids), auditor.stable_card_id(self.url, list(reversed(ids))))
        self.assertEqual(auditor.stable_card_id(self.url, ids), auditor.stable_card_id(self.url + "#fragment", ids))

    def test_cli_default_check_emits_machine_readable_json_without_writes(self):
        before_candidate = self.proposal_path.read_bytes()
        before_cards = self.formal_path.read_bytes()
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", str(Path(auditor.__file__)), "--root", str(self.root), "--article", "data/curated/fixture.json", "--check"],
            check=False, capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        result = json.loads(proc.stdout)
        self.assertTrue(result["ok"])
        self.assertEqual(before_candidate, self.proposal_path.read_bytes())
        self.assertEqual(before_cards, self.formal_path.read_bytes())

    def test_cli_fails_closed_and_still_emits_json_on_invalid_input(self):
        self.proposal["article"]["contentHash"] = "0" * 64
        self._write_proposal()
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", str(Path(auditor.__file__)), "--root", str(self.root), "--article", "data/curated/fixture.json"],
            check=False, capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(json.loads(proc.stdout)["ok"])

    def test_rejects_wrong_schema_and_version(self):
        self.proposal["schema"] = "other"
        self.proposal["version"] = True
        self._write_proposal()
        result = self.audit()
        codes = {item["code"] for item in result["errors"]}
        self.assertIn("schema", codes)
        self.assertIn("version", codes)

    def test_rejects_missing_and_duplicate_dispositions(self):
        self.proposal["sourceUnits"].pop()
        self._write_proposal()
        self.assert_error_code("missing_disposition")
        self.proposal["sourceUnits"].append(dict(self.proposal["sourceUnits"][0]))
        self._write_proposal()
        self.assert_error_code("duplicate_disposition")

    def test_rejects_unknown_unit_and_invalid_disposition(self):
        self.proposal["sourceUnits"][1]["knowledgeUnitId"] = "f" * 16
        self.proposal["sourceUnits"][1]["disposition"] = "ignore"
        self.proposal["sourceUnits"][1]["reason"] = "not applicable"
        self._write_proposal()
        result = self.audit()
        codes = {item["code"] for item in result["errors"]}
        self.assertIn("unknown_source_unit", codes)
        self.assertIn("disposition", codes)

    def test_rejects_article_url_cache_and_manifest_hash_mismatch(self):
        self.proposal["article"]["url"] = "https://example.test/os/other.html"
        self._write_proposal()
        self.assert_error_code("article_not_in_manifest")
        self.proposal = self.valid_proposal()
        self.proposal["article"]["cache"] = ".cache/html/os/other.html"
        self._write_proposal()
        self.assert_error_code("article_binding_mismatch")
        self.proposal = self.valid_proposal()
        self.proposal["article"]["contentHash"] = "0" * 64
        self._write_proposal()
        self.assert_error_code("article_binding_mismatch")

    def test_rejects_current_cache_hash_drift(self):
        self.cache.write_text(self.raw.replace("reliable", "changed"), encoding="utf-8")
        self.assert_error_code("cache_hash_mismatch")

    def test_rejects_cache_path_escape_in_manifest(self):
        self.article_record["cache"] = "../outside.html"
        self._write_json("data/articles.json", {"version": 1, "articles": [self.article_record]})
        self.assert_error_code("cache_unavailable")

    def test_rejects_ledger_missing_extra_or_stale_unit(self):
        self._write_json("data/knowledge-units.json", {"version": 2, "units": self.units[:1]})
        self.assert_error_code("ledger_missing_unit")
        stale = [dict(row) for row in self.units]
        stale[0]["text"] += " stale"
        self._write_json("data/knowledge-units.json", {"version": 2, "units": stale})
        self.assert_error_code("ledger_text_mismatch")

    def test_rejects_card_missing_front_back_or_units(self):
        for field in ("front", "back", "knowledgeUnitIds"):
            with self.subTest(field=field):
                self.proposal = self.valid_proposal()
                self.proposal["cards"][0].pop(field)
                self._write_proposal()
                result = self.audit()
                self.assertFalse(result["ok"])
                self.assertTrue(result["errors"])

    def test_rejects_missing_card_and_mismatched_bidirectional_references(self):
        self.proposal["cards"] = []
        self._write_proposal()
        self.assert_error_code("card_reference")
        self.proposal = self.valid_proposal()
        self.proposal["cards"][0]["knowledgeUnitIds"] = [self.units[1]["knowledgeUnitId"]]
        self._write_proposal()
        self.assert_error_code("card_reference")

    def test_rejects_card_from_another_article(self):
        self.proposal["cards"][0]["articleUrl"] = "https://example.test/os/other.html"
        self._write_proposal()
        self.assert_error_code("card_scope")

    def test_rejects_duplicate_card_id_and_formal_collision(self):
        extra = dict(self.proposal["cards"][0])
        self.proposal["cards"].append(extra)
        self._write_proposal()
        self.assert_error_code("duplicate_card_id")

        self.proposal = self.valid_proposal()
        formal_id = self.proposal["cards"][0]["cardId"]
        self._write_json("data/cards/cards.json", {"version": 1, "cards": [{"id": formal_id}]})
        self._write_proposal()
        self.assert_error_code("formal_card_collision")

    def test_rejects_card_disposition_without_card_id_and_context_without_reason(self):
        self.proposal["sourceUnits"][0].pop("cardId")
        self.proposal["sourceUnits"][1].pop("reason")
        self._write_proposal()
        result = self.audit()
        codes = {item["code"] for item in result["errors"]}
        self.assertIn("card_reference", codes)
        self.assertIn("reason", codes)

    def test_duplicate_json_keys_fail_closed(self):
        self.proposal_path.write_text('{"schema":"one","schema":"two"}', encoding="utf-8")
        result = self.audit()
        self.assertFalse(result["ok"])
        self.assertEqual(result["errors"][0]["code"], "audit_failure")

    def test_candidate_path_outside_root_fails_closed(self):
        outside = self.root.parent / (self.root.name + "-outside.json")
        outside.write_text("{}", encoding="utf-8")
        try:
            result = auditor.audit_article(outside, self.root)
            self.assertFalse(result["ok"])
        finally:
            outside.unlink(missing_ok=True)

    def test_unknown_cli_write_option_is_not_available(self):
        original_bytes = self.formal_path.read_bytes()
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", str(Path(auditor.__file__)), "--root", str(self.root), "--article", "data/curated/fixture.json", "--apply"],
            check=False, capture_output=True, text=True, encoding="utf-8",
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(self.formal_path.read_bytes(), original_bytes)


    def authored_proposal(self):
        legacy = self.valid_proposal()
        card = legacy["cards"][0]
        return {
            "schema": legacy["schema"], "version": legacy["version"],
            "sourceId": legacy["article"]["sourceId"], "articleUrl": self.url,
            "articleContentHash": legacy["article"]["contentHash"],
            "author": {"kind": "ai", "agent": "test-author"}, "issues": [],
            "cards": [{"id": "curated-authored-001", "question": card["front"],
                       "answer": card["back"], "unitIds": card["knowledgeUnitIds"],
                       "examSkill": "recall", "tags": [], "assumptions": [], "sourceNotes": []}],
            "unitDisposition": [
                {"unitId": self.units[0]["knowledgeUnitId"], "action": "card",
                 "cardIds": ["curated-authored-001"], "reason": "Directly answers this knowledge point."},
                {"unitId": self.units[1]["knowledgeUnitId"], "action": "context", "cardIds": [],
                 "reason": "Context, not a separate fact."},
            ],
        }

    def supplemental_fixture(self, use_link):
        url = "https://example.test/evidence"
        if use_link:
            raw = self.raw.replace(
                "<p>First source fact describes a reliable concept.</p>",
                '<a href="https://example.test/evidence">First source fact describes a reliable concept.</a>')
            self.cache.write_text(raw, encoding="utf-8")
            self.parsed = sync_sources.parse_article(raw, self.url)
            self.units = auditor._parsed_units(self.parsed, "os")
            self.content_hash = auditor._hash_parsed_article(self.parsed)
            self.article_record["contentHash"] = self.content_hash
            self._write_json("data/articles.json", {"version": 1, "articles": [self.article_record]})
            self._write_json("data/knowledge-units.json", {"version": 2, "units": self.units})
        self.proposal = self.authored_proposal()
        snapshot = {"schema": "codebrick-supplement-snapshot", "version": 1,
                    "url": url, "capturedAt": "2026-11-20", "captureMethod": "fixture DOM",
                    "payloadType": "dom-extract", "payload": {"url": url, "text": "Captured evidence"}}
        path = "data/supplements/evidence.json"
        self._write_json(path, snapshot)
        self.proposal["metadata"] = {"supplementalSources": [{
            "id": "evidence", "parentSectionIndex": self.units[0]["sectionIndex"], "url": url,
            "snapshotPath": path, "snapshotSha256": hashlib.sha256((self.root / path).read_bytes()).hexdigest(),
            "anchorUnitIds": [self.units[0]["knowledgeUnitId"]], "items": [{
                "id": "fact", "locator": "body", "text": "Fact summary",
                "cardIds": [self.proposal["cards"][0]["id"]], "evidencePointer": "/payload/text"}]}]}
        self._write_proposal()

    def test_supplemental_audit_rejects_plain_paragraph_anchor(self):
        self.supplemental_fixture(use_link=False)
        self.assert_error_code("supplemental_source")

    def test_supplemental_audit_passes_real_parsed_link_metadata(self):
        self.supplemental_fixture(use_link=True)
        result = self.audit()
        self.assertTrue(result["structuralOk"], result["errors"])
        self.assertFalse(result["contentApproved"])
        before = self.proposal_path.read_bytes()
        self.proposal["metadata"]["supplementalSources"][0]["url"] = "https://example.test/unrelated"
        self._write_proposal()
        self.assertNotEqual(before, self.proposal_path.read_bytes())
        self.assert_error_code("supplemental_source")

    def test_authored_schema_accepts_stable_ids_and_preserves_file_bytes(self):
        self.proposal = self.authored_proposal()
        self._write_proposal()
        before = self.proposal_path.read_bytes()
        result = self.audit()
        self.assertTrue(result["ok"], result["errors"])
        self.assertTrue(result["structuralOk"])
        self.assertFalse(result["contentApproved"])
        self.assertEqual(result["contentReviewStatus"], "not-evaluated")
        self.assertEqual(result["candidateSha256"], hashlib.sha256(before).hexdigest())
        self.assertEqual(before, self.proposal_path.read_bytes())

    def test_authored_unit_may_support_multiple_atomic_cards(self):
        self.proposal = self.authored_proposal()
        extra = dict(self.proposal["cards"][0], id="curated-authored-002", question="A second atomic question?")
        self.proposal["cards"].append(extra)
        self.proposal["unitDisposition"][0]["cardIds"].append(extra["id"])
        self._write_proposal()
        result = self.audit()
        self.assertTrue(result["ok"], result["errors"])
        self.proposal["cards"][1]["unitIds"] = [self.units[1]["knowledgeUnitId"]]
        self._write_proposal()
        self.assert_error_code("card_reference")

    def test_authored_missing_unknown_duplicate_and_invalid_references_fail_closed(self):
        for refs in ([], ["missing"], ["curated-authored-001", "curated-authored-001"], [None]):
            with self.subTest(refs=refs):
                self.proposal = self.authored_proposal()
                self.proposal["unitDisposition"][0]["cardIds"] = refs
                self._write_proposal()
                self.assert_error_code("card_reference")

    def test_authored_unresolved_units_and_open_issues_never_grant_approval(self):
        self.proposal = self.authored_proposal()
        self.proposal["unitDisposition"][1]["action"] = "unresolved"
        self.proposal["issues"] = [{"severity": "high", "description": "unread diagram"}]
        self._write_proposal()
        result = self.audit()
        self.assertTrue(result["ok"], result["errors"])
        self.assertTrue(result["contentBlocked"])
        self.assertEqual(result["blockedUnitCount"], 1)
        self.assertEqual(result["openIssueCount"], 1)
        self.assertFalse(result["contentApproved"])

    def test_authored_mixed_schema_and_unsupported_fields_fail_closed(self):
        self.proposal = self.authored_proposal()
        self.proposal["article"] = self.valid_proposal()["article"]
        self._write_proposal()
        self.assert_error_code("schema_fields")
        self.proposal = self.authored_proposal()
        self.proposal["cards"][0]["accepted"] = True
        self._write_proposal()
        self.assert_error_code("card_fields")

    def test_authored_all_non_card_dispositions_require_reason(self):
        for action in ("context", "navigation", "duplicate", "conflict", "unresolved"):
            with self.subTest(action=action):
                self.proposal = self.authored_proposal()
                self.proposal["unitDisposition"][1] = {"unitId": self.units[1]["knowledgeUnitId"], "action": action}
                self._write_proposal()
                self.assert_error_code("reason")

    def test_authored_invalid_arrays_and_unit_coverage_fail_closed(self):
        self.proposal = self.authored_proposal()
        self.proposal["cards"][0]["assumptions"] = "not an array"
        self.proposal["unitDisposition"].pop()
        self._write_proposal()
        result = self.audit()
        self.assertFalse(result["ok"])
        codes = {row["code"] for row in result["errors"]}
        self.assertIn("card_field", codes)
        self.assertIn("missing_disposition", codes)


    def test_container_author_kind_and_issue_status_return_structured_errors(self):
        for field in ("author.kind", "issues.status"):
            for value in ([], {}, [None], [{}]):
                with self.subTest(field=field, value=value):
                    self.proposal = self.authored_proposal()
                    if field == "author.kind":
                        self.proposal["author"]["kind"] = value
                    else:
                        self.proposal["issues"] = [{"status": value, "description": "pending"}]
                    self._write_proposal()
                    result = self.audit()
                    self.assertFalse(result["ok"])
                    self.assertFalse(result["contentApproved"])
                    proc = subprocess.run(
                        [sys.executable, "-X", "utf8", str(Path(auditor.__file__)), "--root", str(self.root),
                         "--article", "data/curated/fixture.json"], capture_output=True, text=True, encoding="utf-8")
                    self.assertNotEqual(proc.returncode, 0)
                    self.assertFalse(json.loads(proc.stdout)["ok"])
                    self.assertNotIn("Traceback", proc.stderr)

    def test_surrogate_duplicate_key_still_produces_safe_cli_json(self):
        self.proposal_path.write_bytes(b'{"\\ud800":0,"\\ud800":1}')
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", str(Path(auditor.__file__)), "--root", str(self.root),
             "--article", "data/curated/fixture.json"], capture_output=True, text=True, encoding="utf-8")
        self.assertNotEqual(proc.returncode, 0)
        result = json.loads(proc.stdout)
        self.assertFalse(result["ok"])
        self.assertFalse(result["contentApproved"])
        self.assertNotIn("Traceback", proc.stderr)


if __name__ == "__main__":
    unittest.main()
