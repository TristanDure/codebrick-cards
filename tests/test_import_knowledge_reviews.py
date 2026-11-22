from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import audit_coverage
from scripts import import_knowledge_reviews as importer


UNIT_ID = "0123456789abcdef"
CARD_ID = "fedcba9876543210"
NOW = "2026-11-20T10:20:30Z"


class ImportKnowledgeReviewsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.ledger_path = self.root / "knowledge-units.json"
        self.cards_path = self.root / "cards.json"
        self.export_path = self.root / "review-export.json"

        text = "A source-backed, independently answerable knowledge point."
        self.unit = {
            "knowledgeUnitId": UNIT_ID,
            "sourceId": "os",
            "articleTitle": "Fixture article",
            "articleUrl": "https://example.test/os-blog/fixture",
            "sectionIndex": 1,
            "sectionHeadingPath": "Processes / Scheduling",
            "sectionAnchor": "scheduling",
            "blockIndex": 3,
            "unitIndex": 1,
            "tag": "p",
            "text": text,
            "href": "",
            "title": "",
            "src": "",
            "alt": "",
            "cardIds": [CARD_ID],
            "status": "mapped-candidate-unreviewed",
            "bodySha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "presentInCurrentSource": True,
            "machineMappingStatus": "mapped-candidate-unreviewed",
            "reviewSourceSha256": "",
            "reviewerDecision": "pending",
        }
        self.unit["reviewSourceSha256"] = audit_coverage._review_source_sha256(self.unit)
        self.card = {
            "id": CARD_ID,
            "question": "Under what condition does the scheduler preempt a running process?",
            "answer": "When a higher-priority process becomes ready in a preemptive priority scheduler.",
            "knowledgeUnitIds": [UNIT_ID],
            "status": "candidate-unreviewed",
        }
        self.ledger = {"version": 2, "generatedAt": NOW, "units": [self.unit]}
        self.cards_doc = {"version": 1, "cards": [self.card]}
        self._write_json(self.ledger_path, self.ledger)
        self._write_json(self.cards_path, self.cards_doc)
        self._write_export([self._record()])

    def tearDown(self):
        self.temp_dir.cleanup()

    @staticmethod
    def _write_json(path: Path, value):
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _record(self, **overrides):
        record = {
            "knowledgeUnitId": UNIT_ID,
            "decision": "accepted",
            "reason": "Verified the source passage and checked that this card tests one explicit scheduling condition.",
            "reviewer": "Reviewer A",
            "examPoints": ["进程调度：抢占式优先级调度的触发条件"],
            "acceptedCardIds": [CARD_ID],
            "reviewedAt": NOW,
            "sourceHash": self.unit["reviewSourceSha256"],
            "textHash": self.unit["bodySha256"],
        }
        record.update(overrides)
        return record

    def _write_export(self, records, **envelope_overrides):
        value = {
            "schema": importer.SCHEMA,
            "version": 2,
            "exportedAt": NOW,
            "records": records,
        }
        value.update(envelope_overrides)
        self._write_json(self.export_path, value)

    def _import(self, *, apply=False):
        return importer.import_reviews(
            self.export_path, self.ledger_path, self.cards_path, apply=apply
        )

    def _expect_rejected(self, message_fragment=None):
        before = self.ledger_path.read_bytes()
        with self.assertRaises(importer.ImportValidationError) as caught:
            self._import(apply=True)
        self.assertEqual(self.ledger_path.read_bytes(), before)
        self.assertEqual(list(self.root.glob("*.pre-review-import-*.json")), [])
        if message_fragment:
            self.assertIn(message_fragment, str(caught.exception))

    def test_default_is_dry_run_and_does_not_mark_candidate_accepted(self):
        before = self.ledger_path.read_bytes()
        result = self._import()
        self.assertEqual(result["mode"], "dry-run")
        self.assertEqual(result["imported"], 1)
        self.assertIsNone(result["backup"])
        self.assertEqual(self.ledger_path.read_bytes(), before)
        self.assertEqual(list(self.root.glob("*.pre-review-import-*.json")), [])
        self.assertEqual(json.loads(before)["units"][0]["reviewerDecision"], "pending")

    def test_apply_creates_exact_backup_and_merges_human_decision(self):
        before = self.ledger_path.read_bytes()
        result = self._import(apply=True)
        self.assertEqual(result["mode"], "apply")
        self.assertEqual(result["imported"], 1)
        backup = Path(result["backup"])
        self.assertTrue(backup.is_file())
        self.assertEqual(backup.read_bytes(), before)
        saved = json.loads(self.ledger_path.read_text(encoding="utf-8"))["units"][0]
        self.assertEqual(saved["reviewerDecision"], "accepted")
        self.assertEqual(saved["reviewer"], "Reviewer A")
        self.assertEqual(saved["reviewerNote"], self._record()["reason"])
        self.assertEqual(saved["acceptedCardIds"], [CARD_ID])
        self.assertEqual(saved["examPointIds"], self._record()["examPoints"])
        self.assertEqual(saved["reviewSourceSha256"], self.unit["reviewSourceSha256"])
        self.assertEqual(saved["bodySha256"], self.unit["bodySha256"])

    def test_reimport_of_identical_decision_is_idempotent(self):
        self._import(apply=True)
        before = self.ledger_path.read_bytes()
        result = self._import(apply=True)
        self.assertEqual(result["imported"], 0)
        self.assertEqual(result["unchanged"], 1)
        self.assertIsNone(result["backup"])
        self.assertEqual(self.ledger_path.read_bytes(), before)

    def test_unknown_record_field_fails_closed(self):
        self._write_export([self._record(extra="not allowed")])
        self._expect_rejected("unknown fields")

    def test_unknown_envelope_field_fails_closed(self):
        self._write_export([self._record()], debug="extra")
        self._expect_rejected("version-2")

    def test_only_version_two_is_accepted(self):
        self._write_export([self._record()], version=1)
        self._expect_rejected("version-2")

    def test_duplicate_unit_records_fail_closed(self):
        self._write_export([self._record(), self._record()])
        self._expect_rejected("duplicate knowledgeUnitId")

    def test_duplicate_json_properties_fail_closed(self):
        self.export_path.write_text(
            '{"schema":"codebrick-knowledge-unit-review-ledger",'
            '"schema":"codebrick-knowledge-unit-review-ledger",'
            '"version":2,"exportedAt":"2026-11-20T10:20:30Z","records":[]}',
            encoding="utf-8",
        )
        self._expect_rejected("duplicate JSON object key")

    def test_nonstandard_json_constant_fails_closed(self):
        self.export_path.write_text(
            '{"schema":"codebrick-knowledge-unit-review-ledger",'
            '"version":NaN,"exportedAt":"2026-11-20T10:20:30Z","records":[]}',
            encoding="utf-8",
        )
        self._expect_rejected("non-standard JSON numeric constant")
    def test_unknown_unit_fails_closed(self):
        self._write_export([self._record(knowledgeUnitId="aaaaaaaaaaaaaaaa")])
        self._expect_rejected("unknown knowledgeUnitId")

    def test_stale_source_hash_fails_closed(self):
        self._write_export([self._record(sourceHash="0" * 64)])
        self._expect_rejected("stale sourceHash")

    def test_stale_text_hash_fails_closed(self):
        self._write_export([self._record(textHash="0" * 64)])
        self._expect_rejected("stale sourceHash")

    def test_internally_stale_ledger_fingerprint_fails_closed(self):
        self.unit["text"] += " changed"
        self.unit["reviewSourceSha256"] = audit_coverage._review_source_sha256(self.unit)
        self._write_json(self.ledger_path, {"version": 2, "units": [self.unit]})
        self._expect_rejected("text fingerprint is inconsistent")

    def test_unit_not_confirmed_in_current_source_fails_closed(self):
        self.unit["presentInCurrentSource"] = False
        self.unit["reviewSourceSha256"] = audit_coverage._review_source_sha256(self.unit)
        self._write_json(self.ledger_path, {"version": 2, "units": [self.unit]})
        self._write_export([self._record(sourceHash=self.unit["reviewSourceSha256"])])
        self._expect_rejected("not confirmed in the current source")

    def test_accepted_review_requires_exam_point(self):
        self._write_export([self._record(examPoints=[])])
        self._expect_rejected("needs explicit examPoints")

    def test_accepted_review_requires_card(self):
        self._write_export([self._record(acceptedCardIds=[])])
        self._expect_rejected("needs explicit examPoints")

    def test_accepted_review_requires_reason_and_reviewer(self):
        for field, value in (("reason", "  "), ("reviewer", "")):
            with self.subTest(field=field):
                self._write_export([self._record(**{field: value})])
                self._expect_rejected("needs a non-empty" if field == "reason" else "explicit reviewer")

    def test_illegal_decision_fails_closed(self):
        self._write_export([self._record(decision="approved")])
        self._expect_rejected("invalid decision")

    def test_nonaccepted_review_cannot_claim_accepted_cards_or_exam_points(self):
        self._write_export([self._record(decision="rejected")])
        self._expect_rejected("must not claim examPoints")

    def test_rejected_decision_is_imported_as_rejected_not_accepted(self):
        self._write_export([self._record(decision="rejected", examPoints=[], acceptedCardIds=[])])
        self._import(apply=True)
        unit = json.loads(self.ledger_path.read_text(encoding="utf-8"))["units"][0]
        self.assertEqual(unit["reviewerDecision"], "rejected")
        self.assertEqual(unit["acceptedCardIds"], [])

    def test_duplicate_card_ids_in_export_fail_closed(self):
        self._write_export([self._record(acceptedCardIds=[CARD_ID, CARD_ID])])
        self._expect_rejected("duplicate acceptedCardIds")

    def test_duplicate_exam_points_fail_closed(self):
        point = self._record()["examPoints"][0]
        self._write_export([self._record(examPoints=[point, point])])
        self._expect_rejected("duplicate examPoints")

    def test_accepted_card_must_be_linked_to_unit_from_both_sides(self):
        self.card["knowledgeUnitIds"] = ["aaaaaaaaaaaaaaaa"]
        self._write_json(self.cards_path, {"cards": [self.card]})
        self._expect_rejected("not bound")

    def test_accepted_card_must_be_concrete_not_generic(self):
        self.card["question"] = "回忆「进程调度」的核心定义、机制与易错点。"
        self._write_json(self.cards_path, {"cards": [self.card]})
        self._expect_rejected("non-concrete")

    def test_accepted_card_must_not_be_archived_or_placeholder(self):
        self.card["status"] = "archived"
        self._write_json(self.cards_path, {"cards": [self.card]})
        self._expect_rejected("non-concrete")

    def test_duplicate_matching_card_ids_fail_closed(self):
        duplicate = dict(self.card)
        duplicate["answer"] = "A distinct duplicate record."
        self._write_json(self.cards_path, {"cards": [self.card, duplicate]})
        self._expect_rejected("duplicated")

    def test_duplicate_ids_in_existing_ledger_fail_closed(self):
        self._write_json(self.ledger_path, {"version": 2, "units": [self.unit, self.unit]})
        self._expect_rejected("duplicate knowledgeUnitId in current ledger")

    def test_existing_conflicting_human_decision_is_not_overwritten(self):
        current = dict(self.unit)
        current.update({
            "reviewerDecision": "rejected",
            "reviewerNote": "Existing manual decision.",
            "reviewer": "Reviewer B",
            "reviewedAt": NOW,
            "acceptedCardIds": [],
            "examPointIds": [],
        })
        self._write_json(self.ledger_path, {"version": 2, "units": [current]})
        self._expect_rejected("conflicting prior human decision")

    def test_naive_timestamps_fail_closed(self):
        self._write_export([self._record(reviewedAt="2026-11-20T10:20:30")])
        self._expect_rejected("must include a timezone")


if __name__ == "__main__":
    unittest.main()



