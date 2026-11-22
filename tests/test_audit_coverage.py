from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import audit_coverage
from scripts.sync_sources import parse_article, sections


class CoverageAuditTests(unittest.TestCase):
    def _build_report(self, html: str, cards: list[dict], prior_ledger=None, stable_unit_id=None, review_export=None) -> dict:
        source = {
            "id": "os",
            "name": "Operating systems",
            "prefix": "os-blog",
            "base": "https://example.test/os-blog/",
            "extension": "",
        }
        article_url = source["base"] + "fixture"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache = root / ".cache" / "fixture.html"
            cache.parent.mkdir(parents=True)
            cache.write_text(html, encoding="utf-8")
            data = root / "data"
            (data / "cards").mkdir(parents=True)
            (data / "articles.json").write_text(json.dumps({"articles": [
                {"sourceId": "os", "url": article_url, "cache": cache.relative_to(root).as_posix()}
            ]}), encoding="utf-8")
            (data / "cards" / "cards.json").write_text(json.dumps({"cards": cards}), encoding="utf-8")
            if prior_ledger is not None:
                (data / "knowledge-units.json").write_text(json.dumps(prior_ledger), encoding="utf-8")
            review_export_path = None
            if review_export is not None:
                review_export_path = root / "review-export.json"
                review_export_path.write_text(json.dumps(review_export), encoding="utf-8")

            patches = [
                mock.patch.object(audit_coverage, "ROOT", root),
                mock.patch.object(audit_coverage, "SOURCES", [source]),
            ]
            if stable_unit_id is not None:
                patches.append(mock.patch("scripts.sync_sources.stable_id", return_value=stable_unit_id))
            with patches[0], patches[1]:
                if len(patches) == 3:
                    with patches[2]:
                        return audit_coverage.build_report(review_export_path)
                return audit_coverage.build_report(review_export_path)

    def test_maps_each_card_and_preserves_orphan_and_duplicate_id_reporting(self):
        article_url = "https://example.test/os-blog/fixture"
        html = (
            '<main class="vp-doc"><h1>Fixture</h1>'
            '<h2 id="one">One</h2><p>One source body.</p>'
            '<h2 id="two">Two</h2></main>'
        )
        report = self._build_report(html, [
            {"id": "one-card", "sourceId": "os", "articleUrl": article_url, "sectionIndex": 1},
            {"id": "orphan", "sourceId": "os", "articleUrl": article_url, "sectionIndex": 9},
            {"id": "duplicate", "sourceId": "os", "articleUrl": article_url, "sectionIndex": 1},
            {"id": "duplicate", "sourceId": "os", "articleUrl": article_url, "sectionIndex": 1},
        ])

        self.assertEqual(report["sectionCount"], 2)
        self.assertEqual(report["coverageCount"], 1)
        self.assertEqual(report["missingCardCount"], 1)
        self.assertEqual(report["orphanCardCount"], 1)
        self.assertEqual(report["orphanCards"][0]["cardId"], "orphan")
        self.assertEqual(report["duplicateCardIds"], ["duplicate"])
        self.assertEqual(report["ambiguousCardMappings"], [])

    def test_practice_index_section_stays_blocked_even_when_linked_to_candidate_card(self):
        article_url = "https://example.test/os-blog/fixture"
        html = (
            '<main class="vp-doc"><h1>Fixture</h1><h2 id="practice">真题练习</h2>'
            '<a class="exam-tile" href="/practice/q/os-2020-28" title="2020 年第 28 题">2020 Q28</a></main>'
        )
        parsed = parse_article(html, article_url)
        unit_ids = [unit["id"] for block in sections(parsed)[0]["sourceUnits"] for unit in block["units"]]
        report = self._build_report(html, [{
            "id": "practice-card", "sourceId": "os", "articleUrl": article_url,
            "sectionIndex": 1, "reviewReason": "knowledge-point-and-408-review-required",
            "auditFlags": ["linked-question-index-not-question-content"],
            "knowledgeUnitIds": unit_ids,
        }])
        self.assertEqual(report["coverageCount"], 1)
        self.assertEqual(report["extractionReviewCount"], 1)
        self.assertEqual(report["sections"][0]["status"], "needs-human-source-review")
        self.assertEqual(report["knowledgeUnits"][0]["status"], "linked-reference-pending-review")

    def test_historical_cards_are_separately_counted_and_excluded_from_coverage(self):
        article_url = "https://example.test/os-blog/fixture"
        report = self._build_report(
            '<main class="vp-doc"><h1>Fixture</h1><h2 id="one">One</h2><p>Body.</p></main>',
            [{"id": "removed", "sourceId": "os", "articleUrl": article_url,
              "sectionIndex": 1, "sourceSectionRemoved": True}],
        )
        self.assertEqual(report["historicalCardCount"], 1)
        self.assertEqual(report["activeCardCount"], 0)
        self.assertEqual(report["coverageCount"], 0)
        self.assertEqual(report["missingCardCount"], 1)
        self.assertEqual(report["orphanCardCount"], 0)

    def test_unique_anchor_maps_legacy_card_when_heading_changed(self):
        article_url = "https://example.test/os-blog/fixture"
        html = (
            '<main class="vp-doc"><h1>Fixture</h1>'
            '<h2 id="stable-anchor">Current heading with [SVG formula]</h2></main>'
        )
        report = self._build_report(html, [{
            "id": "legacy-card", "sourceId": "os", "articleUrl": article_url,
            "sectionAnchor": "stable-anchor", "section": "Old heading",
        }])

        self.assertEqual(report["orphanCardCount"], 0)
        self.assertEqual(report["ambiguousCardMappings"], [])
        self.assertEqual(report["sections"][0]["cardIds"], ["legacy-card"])

    def test_duplicate_anchor_uses_heading_to_disambiguate(self):
        article_url = "https://example.test/os-blog/fixture"
        html = (
            '<main class="vp-doc"><h1>Fixture</h1>'
            '<h2 id="reused">Alpha</h2><h2 id="reused">Beta</h2></main>'
        )
        report = self._build_report(html, [{
            "id": "beta-card", "sourceId": "os", "articleUrl": article_url,
            "sectionAnchor": "reused", "section": "Beta",
        }])

        self.assertEqual(report["orphanCardCount"], 0)
        self.assertEqual(report["ambiguousCardMappings"], [])
        self.assertEqual([section["cardIds"] for section in report["sections"]], [[], ["beta-card"]])

    def test_duplicate_anchor_without_unique_heading_is_ambiguous_and_orphaned(self):
        article_url = "https://example.test/os-blog/fixture"
        html = (
            '<main class="vp-doc"><h1>Fixture</h1>'
            '<h2 id="reused">Alpha</h2><h2 id="reused">Beta</h2></main>'
        )
        report = self._build_report(html, [{
            "id": "unclear-card", "sourceId": "os", "articleUrl": article_url,
            "sectionAnchor": "reused", "section": "Changed heading",
        }])

        self.assertEqual(report["orphanCardCount"], 1)
        self.assertEqual(report["ambiguousCardMappings"], [{
            "cardId": "unclear-card",
            "articleUrl": article_url,
            "candidateSectionIndexes": [1, 2],
        }])
        self.assertEqual([section["cardCount"] for section in report["sections"]], [0, 0])

    def test_matching_title_without_anchor_is_not_blindly_mapped(self):
        article_url = "https://example.test/os-blog/fixture"
        html = '<main class="vp-doc"><h1>Fixture</h1><h2 id="one">One</h2></main>'
        report = self._build_report(html, [{
            "id": "title-only-card", "sourceId": "os", "articleUrl": article_url,
            "section": "One",
        }])

        self.assertEqual(report["orphanCardCount"], 1)
        self.assertEqual(report["ambiguousCardMappings"], [])
        self.assertEqual(report["sections"][0]["cardCount"], 0)


    def test_review_source_fingerprint_matches_browser_snapshot_contract(self):
        unit = {
            "sourceId": "os", "articleTitle": "进程管理", "articleUrl": "https://example.test/os/1",
            "sectionIndex": 2, "sectionHeadingPath": "操作系统 / 进程", "sectionAnchor": "process",
            "blockIndex": 4, "unitIndex": 1, "tag": "img", "text": "图示说明",
            "href": "", "title": "示意图", "src": "/process.svg", "alt": "进程状态图",
            "cardIds": ["card-b", "card-a", "card-b"], "status": "rich-content-pending-review",
            "bodySha256": "a" * 64, "presentInCurrentSource": True,
            "machineMappingStatus": "rich-content-pending-review",
        }
        self.assertEqual(
            audit_coverage._review_source_snapshot(unit),
            ["os", "进程管理", "https://example.test/os/1", "2", "操作系统 / 进程", "process",
             "4", "1", "img", "图示说明", "", "示意图", "/process.svg", "进程状态图",
             ["card-a", "card-b"], "rich-content-pending-review", "a" * 64, True,
             "rich-content-pending-review"],
        )
        expected_sha256 = "c09bda65cf9720fd2be5b1914dd0b1e04fe348a07da328b7ce1963a67c0df956"
        self.assertEqual(audit_coverage._review_source_sha256(unit), expected_sha256)

        # Every browser-bound source, locator, rich-content, and mapping field
        # participates in the fingerprint even when the extracted text is unchanged.
        for field in audit_coverage.REVIEW_SOURCE_FIELDS:
            changed = dict(unit)
            if field == "cardIds":
                changed[field] = ["different-card"]
            elif field == "presentInCurrentSource":
                changed[field] = False
            elif field == "bodySha256":
                changed[field] = "b" * 64
            else:
                changed[field] = f"changed:{field}"
            with self.subTest(field=field):
                self.assertNotEqual(audit_coverage._review_source_sha256(unit), audit_coverage._review_source_sha256(changed))

        reordered = dict(unit, cardIds=["card-a", "card-b"])
        self.assertEqual(audit_coverage._review_source_sha256(unit), audit_coverage._review_source_sha256(reordered))

    def test_preserves_human_decision_only_for_exact_source_snapshot(self):
        article_url = "https://example.test/os-blog/fixture"
        html = '<main class="vp-doc"><h1>Fixture</h1><h2 id="one">One</h2><p>Verified body.</p></main>'
        parsed = parse_article(html, article_url)
        unit_id = next(unit["id"] for block in sections(parsed)[0]["sourceUnits"] for unit in block["units"])
        card_id = "0123456789abcdef"
        card = {
            "id": card_id, "articleUrl": article_url, "sectionIndex": 1,
            "knowledgeUnitIds": [unit_id],
            "question": "What does this verified source explain?",
            "answer": "A concrete answer grounded in the verified source.",
        }
        baseline = self._build_report(html, [card])
        current_unit = baseline["knowledgeUnits"][0]
        human_fields = {
            "reviewerDecision": "accepted",
            "reviewerNote": "核对过原文与卡片。",
            "reviewer": "reviewer-1",
            "reviewedAt": "2026-11-20T01:02:03Z",
            "acceptedCardIds": [card_id],
            "examPointIds": ["408-os-1"],
        }
        prior = {"version": 2, "units": [{
            "knowledgeUnitId": current_unit["knowledgeUnitId"],
            "bodySha256": current_unit["bodySha256"],
            "reviewSourceSha256": current_unit["reviewSourceSha256"],
            "machineMappingStatus": current_unit["machineMappingStatus"], **human_fields,
        }]}
        report = self._build_report(html, [card], prior)

        current = report["knowledgeUnits"][0]
        for key, value in human_fields.items():
            self.assertEqual(current[key], value, key)
        self.assertEqual(current["reviewSourceSha256"], current_unit["reviewSourceSha256"])
        self.assertEqual(current["reviewerDecision"], "accepted")
        self.assertEqual(report["humanAcceptedKnowledgeUnitCount"], 1)
        self.assertEqual(report["pendingKnowledgeUnitReviewCount"], 0)

    def test_changed_source_locator_invalidates_approval_when_text_is_unchanged(self):
        article_url = "https://example.test/os-blog/fixture"
        old_html = ('<main class="vp-doc"><h1>Fixture</h1><h2 id="one">One</h2>'
                    '<p>Verified body.</p></main>')
        new_html = ('<main class="vp-doc"><h1>Fixture</h1><h2 id="renamed">One</h2>'
                    '<p>Verified body.</p></main>')
        card = {"id": "card-1", "articleUrl": article_url, "sectionIndex": 1}
        baseline = self._build_report(old_html, [card], stable_unit_id="stable-unit")
        old_unit = baseline["knowledgeUnits"][0]
        human_fields = {
            "reviewerDecision": "accepted", "reviewerNote": "old note",
            "reviewer": "reviewer-1", "reviewedAt": "2026-11-19T00:00:00Z",
            "acceptedCardIds": ["card-1"], "examPointIds": ["old-point"],
        }
        prior = {"version": 2, "units": [{
            "knowledgeUnitId": "stable-unit", "bodySha256": old_unit["bodySha256"],
            "reviewSourceSha256": old_unit["reviewSourceSha256"],
            "machineMappingStatus": old_unit["machineMappingStatus"], **human_fields,
        }]}
        report = self._build_report(new_html, [card], prior, stable_unit_id="stable-unit")
        current = report["knowledgeUnits"][0]

        self.assertEqual(current["text"], old_unit["text"])
        self.assertNotEqual(current["sectionAnchor"], old_unit["sectionAnchor"])
        self.assertEqual(current["bodySha256"], old_unit["bodySha256"])
        self.assertNotEqual(current["reviewSourceSha256"], old_unit["reviewSourceSha256"])
        self.assertEqual(current["reviewerDecision"], "stale")
        self.assertEqual(current["reviewStaleReason"], "source-snapshot-changed")
        self.assertEqual(current["staleFromSourceSha256"], old_unit["reviewSourceSha256"])
        for key in ("reviewerNote", "reviewer", "reviewedAt", "acceptedCardIds", "examPointIds"):
            self.assertNotIn(key, current)
        self.assertEqual(report["humanAcceptedKnowledgeUnitCount"], 0)
        self.assertEqual(report["staleKnowledgeUnitReviewCount"], 1)

    def test_legacy_text_only_approval_is_unbound_and_cannot_be_carried_forward(self):
        article_url = "https://example.test/os-blog/fixture"
        html = '<main class="vp-doc"><h1>Fixture</h1><h2 id="one">One</h2><p>Verified body.</p></main>'
        text_hash = hashlib.sha256(b"Verified body.").hexdigest()
        prior = {"version": 2, "units": [{
            "knowledgeUnitId": "stable-unit", "bodySha256": text_hash,
            "reviewerDecision": "accepted", "reviewerNote": "legacy text-only review",
            "reviewer": "reviewer-1", "acceptedCardIds": ["old-card"], "examPointIds": ["old-point"],
        }]}
        report = self._build_report(html, [], prior, stable_unit_id="stable-unit")
        current = report["knowledgeUnits"][0]

        self.assertEqual(current["reviewerDecision"], "stale")
        self.assertEqual(current["reviewStaleReason"], "source-snapshot-unbound")
        self.assertNotIn("reviewerNote", current)
        self.assertNotIn("acceptedCardIds", current)
        self.assertEqual(report["humanAcceptedKnowledgeUnitCount"], 0)
        self.assertEqual(report["staleKnowledgeUnitReviewCount"], 1)

    def test_v2_review_export_binds_accepted_card_ids_into_coverage(self):
        article_url = "https://example.test/os-blog/fixture"
        html = '<main class="vp-doc"><h1>Fixture</h1><h2 id="one">One</h2><p>Verified body.</p></main>'
        parsed = parse_article(html, article_url)
        unit_id = next(unit["id"] for block in sections(parsed)[0]["sourceUnits"] for unit in block["units"])
        card_id = "89abcdef01234567"
        card = {
            "id": card_id, "articleUrl": article_url, "sectionIndex": 1,
            "knowledgeUnitIds": [unit_id],
            "question": "What does this verified source explain?",
            "answer": "A concrete answer grounded in the verified source.",
        }
        baseline = self._build_report(html, [card])
        unit = baseline["knowledgeUnits"][0]
        review_export = {
            "schema": audit_coverage.REVIEW_EXPORT_SCHEMA,
            "version": 2,
            "exportedAt": "2026-11-20T01:02:03Z",
            "records": [{
                "knowledgeUnitId": unit["knowledgeUnitId"],
                "decision": "accepted",
                "reason": "Reviewed against source and a concrete card.",
                "reviewer": "reviewer-1",
                "examPoints": ["408-os-1"],
                "acceptedCardIds": [card_id],
                "reviewedAt": "2026-11-20T01:02:03Z",
                "sourceHash": unit["reviewSourceSha256"],
                "textHash": unit["bodySha256"],
            }],
        }

        report = self._build_report(html, [card], review_export=review_export)
        reviewed = report["knowledgeUnits"][0]
        ledger = report["knowledgeUnitLedger"]["units"][0]
        self.assertEqual(reviewed["reviewerDecision"], "accepted")
        self.assertEqual(reviewed["acceptedCardIds"], [card_id])
        self.assertEqual(ledger["acceptedCardIds"], [card_id])
        self.assertEqual(report["humanAcceptedKnowledgeUnitCount"], 1)
        self.assertEqual(report["pendingKnowledgeUnitReviewCount"], 0)

    def test_legacy_approval_without_accepted_card_ids_is_stale(self):
        article_url = "https://example.test/os-blog/fixture"
        html = '<main class="vp-doc"><h1>Fixture</h1><h2 id="one">One</h2><p>Verified body.</p></main>'
        parsed = parse_article(html, article_url)
        unit_id = next(unit["id"] for block in sections(parsed)[0]["sourceUnits"] for unit in block["units"])
        card = {
            "id": "0011223344556677", "articleUrl": article_url, "sectionIndex": 1,
            "knowledgeUnitIds": [unit_id],
            "question": "What does this verified source explain?",
            "answer": "A concrete answer grounded in the verified source.",
        }
        baseline = self._build_report(html, [card])
        current_unit = baseline["knowledgeUnits"][0]
        prior = {"version": 2, "units": [{
            "knowledgeUnitId": current_unit["knowledgeUnitId"],
            "bodySha256": current_unit["bodySha256"],
            "reviewSourceSha256": current_unit["reviewSourceSha256"],
            "machineMappingStatus": current_unit["machineMappingStatus"],
            "reviewerDecision": "accepted",
            "reviewerNote": "legacy approval without a card binding",
            "reviewer": "reviewer-1",
            "reviewedAt": "2026-11-20T01:02:03Z",
            "examPointIds": ["408-os-1"],
        }]}

        report = self._build_report(html, [card], prior)
        current = report["knowledgeUnits"][0]
        self.assertEqual(current["reviewerDecision"], "stale")
        self.assertEqual(current["reviewStaleReason"], "accepted-card-evidence-invalid")
        self.assertNotIn("acceptedCardIds", current)
        self.assertEqual(current["previousReview"]["reviewerDecision"], "accepted")
        self.assertEqual(report["humanAcceptedKnowledgeUnitCount"], 0)
        self.assertEqual(report["staleKnowledgeUnitReviewCount"], 1)

    def test_removed_unit_is_retained_as_retired_ledger_record(self):
        removed_text = "Removed source unit."
        prior_unit = {
            "knowledgeUnitId": "removed-unit",
            "bodySha256": hashlib.sha256(removed_text.encode("utf-8")).hexdigest(),
            "machineMappingStatus": "mapped-candidate-unreviewed",
            "text": removed_text,
            "reviewerDecision": "accepted", "reviewer": "reviewer-1",
            "reviewedAt": "2026-11-19T00:00:00Z", "reviewerNote": "retain history",
            "acceptedCardIds": ["old-card"], "examPointIds": ["point-1"],
        }
        prior = {"version": 2, "units": [prior_unit]}
        html = '<main class="vp-doc"><h1>Fixture</h1><h2 id="one">One</h2></main>'
        report = self._build_report(html, [], prior)

        self.assertEqual(report["knowledgeUnitCount"], 0)
        self.assertEqual(report["retiredKnowledgeUnitCount"], 1)
        retired = report["knowledgeUnitLedger"]["units"][0]
        self.assertEqual(retired["knowledgeUnitId"], "removed-unit")
        self.assertEqual(retired["machineMappingStatus"], "source-unit-removed")
        self.assertFalse(retired["presentInCurrentSource"])
        self.assertEqual(retired["reviewerDecision"], "accepted")
        self.assertEqual(retired["reviewerNote"], "retain history")

    def test_invalid_prior_ledger_schema_fails_closed(self):
        html = '<main class="vp-doc"><h1>Fixture</h1><h2 id="one">One</h2><p>Body.</p></main>'
        with self.assertRaisesRegex(ValueError, "knowledge-units ledger"):
            self._build_report(html, [], {"version": 2, "units": {"not": "a list"}})

    def test_human_pending_is_reported_separately_from_machine_exit_status(self):
        article_url = "https://example.test/os-blog/fixture"
        html = (
            '<main class="vp-doc"><h1>Fixture</h1><h2 id="one">One</h2>'
            '<p>First body.</p><p>Second body.</p></main>'
        )
        parsed = parse_article(html, article_url)
        units = [unit for block in sections(parsed)[0]["sourceUnits"] for unit in block["units"]]
        card = {
            "id": "fedcba9876543210", "articleUrl": article_url, "sectionIndex": 1,
            "knowledgeUnitIds": [unit["id"] for unit in units],
            "question": "What do the verified source units explain?",
            "answer": "A concrete answer grounded in the verified source units.",
        }
        baseline = self._build_report(html, [card])
        prior_units = []
        for unit, current, decision in zip(units, baseline["knowledgeUnits"], ["accepted", "rejected"]):
            prior_units.append({
                "knowledgeUnitId": unit["id"],
                "bodySha256": current["bodySha256"],
                "reviewSourceSha256": current["reviewSourceSha256"],
                "machineMappingStatus": current["machineMappingStatus"],
                "reviewerDecision": decision,
                **({"acceptedCardIds": [card["id"]]} if decision == "accepted" else {}),
            })
        prior = {"version": 2, "units": prior_units}
        report = self._build_report(html, [card], prior)

        self.assertEqual(report["humanAcceptedKnowledgeUnitCount"], 1)
        self.assertEqual(report["humanRejectedKnowledgeUnitCount"], 1)
        self.assertEqual(report["pendingKnowledgeUnitReviewCount"], 0)
        self.assertEqual(report["machineAuditExitCode"], 0)
        self.assertEqual(report["machineAuditStatus"], "pass")

    def test_missing_human_review_does_not_make_machine_audit_fail(self):
        article_url = "https://example.test/os-blog/fixture"
        html = '<main class="vp-doc"><h1>Fixture</h1><h2 id="one">One</h2><p>Body.</p></main>'
        parsed = parse_article(html, article_url)
        unit = sections(parsed)[0]["sourceUnits"][0]["units"][0]
        card = {"id": "covering-card", "articleUrl": article_url, "sectionIndex": 1,
                "knowledgeUnitIds": [unit["id"]]}
        report = self._build_report(html, [card])
        self.assertEqual(report["pendingKnowledgeUnitReviewCount"], 1)
        self.assertEqual(report["machineAuditExitCode"], 0)
        self.assertEqual(report["machineAuditStatus"], "pass")


if __name__ == "__main__":
    unittest.main()
