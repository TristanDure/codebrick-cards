from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_408_readiness.py"
SPEC = importlib.util.spec_from_file_location("audit_408_readiness", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class ReadinessAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "data/cards").mkdir(parents=True)
        (self.root / "data/reports").mkdir(parents=True)
        (self.root / "data/articles.json").write_text(json.dumps({"articles": [
            {"sourceId": "os"}, {"sourceId": "co"},
        ]}), encoding="utf-8")
        (self.root / "data/cards/cards.json").write_text(json.dumps({"cards": [
            {"id": "template", "sourceId": "os", "question": "请解释「Fixture」本部分的关键概念、条件、过程与结论。",
             "answer": "definition " * 100, "status": "needs-review", "partCount": 2},
            {"id": "extract", "sourceId": "os", "question": "Specific?",
             "answer": "原文内容未能可靠提取。 <svg></svg> ![alt](fixture.png) | a | b | ```code```",
             "status": "needs-review", "reviewReason": "source-extraction-incomplete"},
            {"id": "ordinary", "sourceId": "co", "question": "What?", "answer": "Short.", "status": "inbox"},
        ]}), encoding="utf-8")
        (self.root / "data/knowledge-units.json").write_text(json.dumps({"units": []}), encoding="utf-8")
        (self.root / "data/reports/coverage.json").write_text(json.dumps({
            "sourceArticleCount": 2, "parsedArticleCount": 2, "sectionCount": 2,
            "coverageCount": 1, "missingCardCount": 1, "extractionReviewCount": 1,
            "orphanCardCount": 0, "duplicateCardIds": [], "ambiguousCardMappings": [],
            "sourceParseFailures": [], "bySource": {
                "os": {"name": "操作系统", "articleCount": 1, "sectionCount": 2,
                       "cardCount": 2, "statusCounts": {"needs-human-source-review": 1}},
                "co": {"name": "计算机组成原理", "articleCount": 1, "sectionCount": 0,
                       "cardCount": 1, "statusCounts": {}},
            },
            "sections": [{"sourceId": "os", "cardCount": 1}, {"sourceId": "os", "cardCount": 0}],
        }), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_patched_root_and_mapping_do_not_claim_readiness(self):
        fixed = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        with mock.patch.object(audit, "ROOT", self.root):
            report = audit.build_report(generated_at=fixed)
        self.assertEqual(report["generatedAt"], "2026-01-02T03:04:05Z")
        self.assertEqual(report["inventory"]["cardRecordCount"], 3)
        self.assertEqual(report["inventory"]["subjects"]["os"]["mappedChapterCount"], 1)
        self.assertEqual(report["sourceSectionMapping"]["mappedChapterCount"], 1)
        self.assertEqual(report["verdict"]["status"], "not_demonstrated; human review required")
        self.assertTrue(report["verdict"]["humanReviewRequired"])
        self.assertIn("primary past-paper audit", report["verdict"]["evidenceBoundaryAndNextStep"])
        self.assertEqual(report["sourceSectionMapping"]["sourceUnitCandidateCount"], 0)
        self.assertEqual(report["inventory"]["activeCardRecordCount"], 3)
        self.assertEqual(report["inventory"]["historicalCardRecordCount"], 0)

    def test_flags_and_rendering_markers(self):
        cards = audit.build_report(self.root)["cards"]
        self.assertEqual(cards["genericTemplatePrompts"]["cardCount"], 1)
        self.assertEqual(cards["genericTemplatePrompts"]["distinctPromptCount"], 1)
        self.assertEqual(cards["extractionPlaceholders"]["cardCount"], 1)
        self.assertEqual(cards["extractionPlaceholders"]["extractionReviewReasonCardCount"], 1)
        self.assertEqual(cards["longAndMultipart"]["longAnswerCardCount"], 1)
        self.assertEqual(cards["longAndMultipart"]["multipartCardCount"], 1)
        for marker in ("svg", "image", "table", "code"):
            self.assertEqual(cards["renderingMarkers"]["cardCountsByMarker"][marker], 1)

    def test_generic_prompt_patterns_include_legacy_and_current_generator_templates(self):
        self.assertTrue(audit.GENERIC_PROMPT.fullmatch(
            "请解释「Fixture」本部分的关键概念、条件、过程与结论。"
        ))
        self.assertTrue(audit.GENERIC_PROMPT.fullmatch(
            "请解释「Fixture」本部分的关键概念、条件、过程与结论。（第 2/3 部分）"
        ))
        self.assertTrue(audit.GENERIC_PROMPT.fullmatch(
            "回忆「Fixture」的核心定义、机制与易错点。"
        ))
        self.assertFalse(audit.GENERIC_PROMPT.fullmatch(
            "请解释「Fixture」的关键概念、条件、过程与结论。"
        ))

    def test_hashes_markdown_and_missing_baseline(self):
        report = audit.build_report(self.root)
        self.assertEqual(set(report["snapshot"]["inputs"]), {"articles", "cards", "coverage", "knowledgeUnits"})
        self.assertTrue(all(len(row["sha256"]) == 64 for row in report["snapshot"]["inputs"].values()))
        self.assertEqual(report["officialSyllabusBaseline"]["status"], "missing")
        markdown = audit.render_markdown(report)
        self.assertIn("2027 baseline", markdown)
        self.assertIn("not a syllabus", markdown)
        self.assertIn("primary past-paper audit", markdown)

    def test_limited_2027_baseline_is_distinguished_from_reviewed_official_syllabus(self):
        baseline = {
            "baselineId": "408-2027-fixture", "targetExamYear": 2027,
            "claimBoundaries": {
                "officialAnnualSyllabusFullTextReviewed": False,
                "frameworkBelowIsOfficial2027Syllabus": False,
            },
            "annualSyllabus": {"officialPublisherCatalogRecord": {"recordFound": True}},
        }
        (self.root / "data/exam").mkdir(parents=True, exist_ok=True)
        (self.root / "data/exam/baseline-408.json").write_text(json.dumps(baseline), encoding="utf-8")
        report = audit.build_report(self.root)
        syllabus = report["officialSyllabusBaseline"]
        self.assertEqual(syllabus["status"], "limited_reference_present_official_syllabus_body_not_reviewed")
        self.assertEqual(syllabus["targetExamYear"], 2027)
        self.assertFalse(syllabus["officialSyllabusFullTextReviewed"])
        self.assertFalse(syllabus["referenceTopicTreeIsOfficialAnnualSyllabus"])
        self.assertIn("408Baseline", report["snapshot"]["inputs"])
        self.assertIn("limited 2027 baseline/reference file is present", report["verdict"]["evidenceBoundaryAndNextStep"])


    def test_human_knowledge_unit_decisions_are_counted_separately(self):
        coverage_path = self.root / "data/reports/coverage.json"
        coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
        coverage["knowledgeUnits"] = [
            {"knowledgeUnitId": "accepted", "cardIds": ["c1"], "reviewerDecision": "accepted"},
            {"knowledgeUnitId": "rejected", "cardIds": [], "reviewerDecision": "rejected"},
            {"knowledgeUnitId": "pending", "cardIds": ["c2"], "reviewerDecision": "pending"},
            {"knowledgeUnitId": "stale", "cardIds": ["c3"], "reviewerDecision": "stale"},
        ]
        coverage_path.write_text(json.dumps(coverage), encoding="utf-8")
        (self.root / "data/knowledge-units.json").write_text(json.dumps({"version": 2, "units": [
            {"knowledgeUnitId": "retired", "presentInCurrentSource": False, "reviewerDecision": "accepted"},
        ]}), encoding="utf-8")

        report = audit.build_report(self.root)
        mapping = report["sourceSectionMapping"]
        self.assertEqual(mapping["humanAcceptedKnowledgeUnitCount"], 1)
        self.assertEqual(mapping["humanReviewedKnowledgeUnitCount"], 1)
        self.assertEqual(mapping["humanRejectedKnowledgeUnitCount"], 1)
        self.assertEqual(mapping["humanPendingKnowledgeUnitCount"], 1)
        self.assertEqual(mapping["staleHumanReviewCount"], 1)
        self.assertEqual(mapping["retiredSourceUnitCount"], 1)


if __name__ == "__main__":
    unittest.main()
