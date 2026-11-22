from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.diagnose_empty_sections import (
    _captured_nodes,
    _category_for,
    _flatten_with_parents,
    build_report,
)
from scripts.sync_sources import Tree, parse_article, walk


class EmptySectionTriageTests(unittest.TestCase):
    def _base_record(self) -> dict:
        return {
            "recordIntegrity": "verified",
            "directBodyBlockCount": 0,
            "subtreeBodyBlockCount": 0,
            "dynamicSkeletonCount": 0,
            "subtreePracticeQuestionLinkCount": 0,
            "hasDeeperHeading": False,
            "sectionLocator": {"heading": "父标题", "sectionLevel": "h2"},
        }

    def test_capture_matches_parser_skip_semantics_for_controls(self):
        parser = Tree()
        parser.feed(
            '<main class="vp-doc"><h2 id="x">标题</h2>'
            '<div><button><svg><path></path></svg><span>图标</span></button>'
            '<p>实际正文</p><a class="header-anchor" href="#x">#</a></div>'
            '<h2 id="next">下节</h2></main>'
        )
        doc = next(node for node in walk(parser.root) if "vp-doc" in node.attrs.get("class", "").split())
        nodes, parents = _flatten_with_parents(doc)
        heading_index = next(i for i, node in enumerate(nodes) if node.tag == "h2" and node.attrs.get("id") == "x")
        next_index = next(i for i, node in enumerate(nodes) if node.tag == "h2" and node.attrs.get("id") == "next")
        captured = _captured_nodes(nodes, parents, heading_index + 1, next_index)
        self.assertEqual([(node.tag, "".join(child for child in node.children if isinstance(child, str)).strip()) for node in captured], [("p", "实际正文")])

    def test_descendant_question_link_is_evidence_but_not_resolution(self):
        record = self._base_record()
        record["subtreePracticeQuestionLinkCount"] = 2
        self.assertEqual(_category_for(record, None, []), "empty_parent_with_descendant_practice_links")

    def test_dynamic_skeleton_has_its_own_class(self):
        record = self._base_record()
        record["dynamicSkeletonCount"] = 1
        self.assertEqual(_category_for(record, None, []), "dynamic_component_static_skeleton")

    def test_mermaid_diagram_is_detected_as_dynamic_evidence(self):
        from scripts.diagnose_empty_sections import _dynamic_evidence

        tree = Tree()
        tree.feed('<div class="mermaid">graph TD; A-->B</div>')
        nodes, _ = _flatten_with_parents(tree.root)
        evidence = _dynamic_evidence(nodes, 0, len(nodes))
        self.assertEqual(len(evidence), 1)
        self.assertIn("mermaid", evidence[0]["selector"])

    def test_bad_integrity_and_same_level_component_are_conservative(self):
        record = self._base_record()
        record["recordIntegrity"] = "unresolved"
        related = Tree()
        related.feed('<h2>相关真题（1题）</h2>')
        heading = next(node for node in walk(related.root) if node.tag == "h2")
        self.assertEqual(
            _category_for(record, heading, [{"href": "/practice/q/example"}]),
            "unresolved",
        )

        record = self._base_record()
        record["recordIntegrity"] = "verified"
        self.assertEqual(
            _category_for(record, heading, [{"href": "/practice/q/example"}]),
            "same_level_exam_component_followed_by_related_links",
        )

    def test_offline_report_preserves_locator_evidence_and_never_closes(self):
        raw = (
            '<main class="vp-doc"><h1>离线夹具</h1>'
            '<h2 id="父标题">父标题</h2><h3 id="子标题">子标题</h3>'
            '<a href="/practice/q/cn-2020-01">题目索引</a>'
            '<h2 id="下一节">下一节</h2></main>'
        )
        url = "https://example.test/cn-blog/fixture"
        parsed = parse_article(raw, url)
        content_hash = hashlib.sha256(
            json.dumps(parsed["blocks"], ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        coverage = {"sections": [{
            "sourceId": "cn", "sourceName": "计算机网络", "articleTitle": "离线夹具",
            "articleUrl": url, "sectionIndex": 1, "sectionHeading": "父标题",
            "sectionHeadingPath": "父标题", "sectionAnchor": "父标题",
            "sourceBlockCount": 0, "status": "needs-human-source-review",
        }]}
        manifest = {"articles": [{
            "sourceId": "cn", "title": "离线夹具", "url": url,
            "cache": ".cache/html/cn/fixture.html", "contentHash": content_hash,
        }]}
        with tempfile.TemporaryDirectory() as tmp:
            cache_root = Path(tmp) / "html"
            cache_file = cache_root / "cn" / "fixture.html"
            cache_file.parent.mkdir(parents=True)
            cache_file.write_text(raw, encoding="utf-8")
            report = build_report(coverage, manifest, cache_root)

        self.assertEqual(report["diagnosticScope"]["recordCount"], 1)
        self.assertEqual(report["diagnosticScope"]["cacheHashVerifiedRecordCount"], 1)
        self.assertEqual(report["diagnosticScope"]["locatorVerifiedRecordCount"], 1)
        record = report["records"][0]
        self.assertEqual(record["triageClass"], "empty_parent_with_descendant_practice_links")
        self.assertEqual(record["directBodyBlockCount"], 0)
        self.assertEqual(record["subtreePracticeQuestionLinkCount"], 1)
        self.assertTrue(record["practiceQuestionLinks"]["subtree"][0]["href"].endswith("cn-2020-01"))
        self.assertEqual(record["resolutionStatus"], "unresolved")
        self.assertFalse(record["autoCloseAllowed"])

    def test_all_classified_records_remain_unresolved_by_contract(self):
        record = self._base_record()
        record["subtreePracticeQuestionLinkCount"] = 1
        record["resolutionStatus"] = "unresolved"
        record["autoCloseAllowed"] = False
        self.assertEqual(_category_for(record, None, []), "empty_parent_with_descendant_practice_links")
        self.assertEqual(record["resolutionStatus"], "unresolved")
        self.assertFalse(record["autoCloseAllowed"])


if __name__ == "__main__":
    unittest.main()
