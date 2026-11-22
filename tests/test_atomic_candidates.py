import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import build_atomic_candidates as builder


class AtomicCandidateTests(unittest.TestCase):
    def make_project(self, body: str, *, source_id: str = "os") -> tuple[tempfile.TemporaryDirectory, Path]:
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        cache = root / ".cache" / "html" / f"{source_id}.html"
        cache.parent.mkdir(parents=True)
        cache.write_text(f'<main class="vp-doc">{body}</main>', encoding="utf-8")
        articles = {"version": 1, "articles": [{
            "sourceId": source_id, "title": "Fixture article",
            "url": f"https://example.test/{source_id}/article",
            "cache": cache.relative_to(root).as_posix(), "contentHash": "parsed-fixture-hash",
        }]}
        (root / "data").mkdir()
        (root / "data" / "articles.json").write_text(json.dumps(articles), encoding="utf-8")
        return temp, root

    def test_rebuild_is_idempotent_and_provenance_is_bound_to_cache(self):
        temp, root = self.make_project(
            '<h1>Operating systems</h1><h2 id="tlb">TLB</h2>'
            '<p>TLB是用于缓存近期页表项的高速缓冲存储器。</p>'
            '<p>这段话没有明确的知识关系，需要人工判断。</p>')
        with temp:
            first = builder.build_candidate_set(root)
            second = builder.build_candidate_set(root)
            self.assertEqual(first["candidates"], second["candidates"])
            self.assertEqual(first["backlog"], second["backlog"])
            card = first["candidates"][0]
            cache_bytes = (root / ".cache" / "html" / "os.html").read_bytes()
            self.assertEqual(card["sourceHash"], builder._hash(cache_bytes))
            self.assertEqual(card["knowledgeUnitIds"], [card["sourceUnitId"]])
            self.assertIn("TLB", card["question"])
            self.assertEqual(card["evidence"], "TLB是用于缓存近期页表项的高速缓冲存储器。")
            self.assertEqual(card["status"], "needs-review")
            self.assertTrue(any(item["reason"] == "no-safe-atomic-recall-pattern" for item in first["backlog"]))

    def test_negative_or_clause_copula_is_not_misread_as_a_definition(self):
        self.assertIsNone(builder._semantic("代码题不是只判最终代码"))
        self.assertIsNone(builder._semantic("参数很多，但它们描述的是同一样东西"))
        result = builder._semantic("TLB是用于缓存近期页表项的高速缓冲存储器")
        self.assertIsNotNone(result)
        self.assertEqual(result[2], "is-definition")

    def test_mechanism_rejects_figure_trace_but_accepts_a_concept_definition(self):
        trace = "图 10.19 利用败者树进行 5 路平衡归并的过程：初始叶结点分别为 3、7、2、9、4。"
        self.assertIsNone(builder._semantic(trace))
        valid = builder._semantic("TLB通过缓存近期页表项实现加速地址转换")
        self.assertIsNotNone(valid)
        self.assertEqual(valid[2], "mechanism")
        self.assertIn("TLB", valid[0])

    def test_classification_requires_explicit_distinct_categories(self):
        self.assertIsNone(builder._semantic("树可分为多级，每一级都是一台机器"))
        valid = builder._semantic("内部排序分为插入排序、交换排序和选择排序")
        self.assertIsNotNone(valid)
        self.assertEqual(valid[2], "classification")

    def test_ascii_diagram_is_deferred_but_real_code_is_retained(self):
        temp, root = self.make_project(
            '<h2 id="diagram">Tree</h2>'
            '<pre>root\n |-- left\n |-- right</pre>'
            '<h2 id="code">Binary search</h2>'
            '<p>二分查找通过不断缩小有序区间来定位目标元素。</p>'
            '<pre><code>while (left &lt;= right) {\n    int mid = (left + right) / 2;\n    if (a[mid] == key) return mid;\n}</code></pre>')
        with temp:
            report = builder.build_candidate_set(root)
            self.assertTrue(any(item["reason"] == "preformatted-noncode-needs-review"
                                for item in report["backlog"]))
            self.assertEqual(sum(c["candidateKind"] == "code" for c in report["candidates"]), 1)

    def test_citation_and_fragment_leads_are_not_turned_into_knowledge_cards(self):
        unsafe = [
            '算法为"把 IP 数据报首部划分为许多 16 位字的序列，并把检验和字段置零。',
            '大纲写"组播"、谢希仁教材写"多播"，指的是同一件事（multicast）。',
            '它不只是"多查一位"，而是流程本身多了一条分支和一次重入。',
            '问哪个操作通过系统调用完成（2021-32）。答创建新进程。',
            'IPv6 过渡隧道是被考过的（cn-2023-40 的第 Ⅲ 条）。',
            '冗余链路导致帧在网络环路中兜圈子（图 3-26）。',
        ]
        for text in unsafe:
            with self.subTest(text=text):
                self.assertIsNone(builder._semantic(text))

    def test_classification_of_steps_uses_a_steps_question(self):
        result = builder._semantic("最简单的指令执行分为取指、解码、执行三步")
        self.assertIsNotNone(result)
        self.assertIn("哪些步骤", result[0])
        self.assertEqual(result[1], "取指、解码、执行三步")

    def test_multisentence_candidate_evidence_is_narrowly_bound(self):
        temp, root = self.make_project(
            '<h2 id="tlb">TLB</h2>'
            '<p>TLB是用于缓存近期页表项的高速缓冲存储器。它可以减少访存次数。</p>')
        with temp:
            report = builder.build_candidate_set(root)
            card = next(c for c in report["candidates"] if c["candidateStrategy"] == "is-definition")
            self.assertEqual(card["evidence"], "TLB是用于缓存近期页表项的高速缓冲存储器。")

    def test_timestamp_labels_and_oversized_definitions_are_deferred(self):
        long_definition = "TLB is " + "a cached translation entry " * 18 + "."
        temp, root = self.make_project(
            '<h2 id="trace">Trace</h2>'
            '<p>t=0: choose the highest-priority queue and run S1.</p>'
            f'<p>TLB is {long_definition}</p>')
        with temp:
            report = builder.build_candidate_set(root)
            self.assertEqual(report["candidates"], [])
            self.assertTrue(any(item["reason"] == "no-safe-atomic-recall-pattern"
                                for item in report["backlog"]))

    def test_table_rows_use_headers_row_key_and_section_context(self):
        temp, root = self.make_project(
            '<h2 id="cache">Cache write policies</h2><table>'
            '<thead><tr><th>策略</th><th>写命中行为</th></tr></thead>'
            '<tbody><tr><td>write-through</td><td>同时更新cache和主存</td></tr></tbody></table>')
        with temp:
            report = builder.build_candidate_set(root)
            card = next(c for c in report["candidates"] if c["candidateStrategy"].startswith("table-row"))
            self.assertIn("策略", card["question"])
            self.assertIn("write-through", card["question"])
            self.assertIn("写命中行为", card["question"])
            self.assertEqual(card["answer"], "同时更新cache和主存")
            self.assertIn("Cache write policies", card["question"])
            self.assertIn("write-through", card["evidence"])

    def test_table_row_with_one_oversized_cell_is_deferred_atomically(self):
        long_value = "extended explanation " * 16
        temp, root = self.make_project(
            '<h2 id="table">Comparison</h2><table>'
            '<thead><tr><th>Type</th><th>Short field</th><th>Long field</th></tr></thead>'
            f'<tbody><tr><td>A</td><td>ok</td><td>{long_value}</td></tr></tbody></table>')
        with temp:
            report = builder.build_candidate_set(root)
            self.assertFalse(any(c["candidateStrategy"] == "table-row-with-column-context"
                                 for c in report["candidates"]))
            self.assertTrue(any(item["reason"] == "table-recall-cell-too-long"
                                for item in report["backlog"]))

    def test_formula_context_inline_link_image_and_empty_section_are_explicit(self):
        temp, root = self.make_project(
            '<h2 id="latency">平均访问时间</h2>'
            '<p>平均访问时间：<math><mi>EAT</mi><mo>=</mo><mi>h</mi><mo>×</mo><mi>t</mi></math></p>'
            '<p>See <a href="https://example.test/spec">the specification</a> for details.</p>'
            '<img src="diagram.svg" alt="状态转换图">'
            '<h2 id="empty">尚待恢复原文</h2>')
        with temp:
            report = builder.build_candidate_set(root)
            formula = next(c for c in report["candidates"] if c["candidateKind"] == "cloze")
            self.assertIn("平均访问时间", formula["question"])
            self.assertIn("____", formula["question"])
            self.assertNotIn("{{c1::", formula["question"])
            self.assertIn("EAT", formula["answer"])
            reasons = {item["reason"] for item in report["backlog"]}
            self.assertIn("inline-link-needs-review", reasons)
            link = next(item for item in report["backlog"]
                        if item["reason"] == "inline-link-needs-review")
            self.assertEqual(link["section"], "平均访问时间")
            self.assertIn("https://example.test/spec", link["detail"])
            self.assertTrue(link["unitId"])
            self.assertIn("image-needs-visual-review", reasons)
            self.assertTrue(any(item["reason"] == "empty-section-no-extractable-source-units" for item in report["backlog"]))
            self.assertFalse(any("链接：" in c["question"] for c in report["candidates"]))

    def test_code_candidate_preserves_source_newlines_and_indentation(self):
        temp, root = self.make_project(
            '<h2 id="algorithm">二分查找</h2>'
            '<p>二分查找通过不断缩小有序区间来定位目标元素。</p>'
            '<pre><code>while (left &lt;= right) {\n    int mid = (left + right) / 2;\n    if (a[mid] == key) return mid;\n}</code></pre>')
        with temp:
            cache = root / ".cache" / "html" / "os.html"
            raw = cache.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            cache.write_bytes(raw)
            report = builder.build_candidate_set(root)
            card = next(c for c in report["candidates"] if c["candidateKind"] == "code")
            self.assertEqual(card["answer"], "while (left <= right) {\n    int mid = (left + right) / 2;\n    if (a[mid] == key) return mid;\n}")
            self.assertEqual(card["evidence"], card["answer"])
            self.assertGreaterEqual(card["answer"].count("\n"), 3)

    def test_unresolved_visual_formula_markup_is_never_promoted(self):
        temp, root = self.make_project(
            '<h2 id="formula">Formula</h2>'
            '<p>Average access time is [SVG公式/图示：img] and depends on hit rate.</p>')
        with temp:
            report = builder.build_candidate_set(root)
            self.assertEqual(report["candidates"], [])
            self.assertTrue(any(item["reason"] == "visual-or-formula-placeholder-needs-review"
                                for item in report["backlog"]))

    def test_long_code_context_is_deferred_not_copied_into_question(self):
        context = "This explanation is intentionally broad and repeats details. " * 8
        temp, root = self.make_project(
            '<h2 id="code">Code</h2>'
            f'<p>{context}</p>'
            '<pre><code>int main(void) { return 0; }</code></pre>')
        with temp:
            report = builder.build_candidate_set(root)
            self.assertFalse(any(c["candidateKind"] == "code" for c in report["candidates"]))
            self.assertTrue(any(item["reason"] == "code-context-too-broad"
                                for item in report["backlog"]))

    def test_dry_run_does_not_write_and_reconcile_preserves_manual_and_history_cards(self):
        temp, root = self.make_project('<h2 id="def">Definition</h2><p>TLB是用于缓存近期页表项的高速缓冲存储器。</p>')
        with temp:
            report = builder.build_candidate_set(root)
            (root / "data" / "cards").mkdir()
            manual = {"id": "manual", "origin": "manual", "question": "mine", "answer": "kept", "status": "approved", "note": "user note"}
            history = {"id": "history", "origin": "source-summary", "question": "old", "answer": "old answer", "status": "needs-review"}
            result = builder.reconcile_owned_cards([manual, history], report["candidates"])
            self.assertEqual(result["cards"][:2], [manual, history])
            self.assertEqual(result["cards"][0]["note"], "user note")
            self.assertEqual(result["inserted"], len(report["candidates"]))
            self.assertFalse((root / "data" / "reports").exists())
            self.assertFalse((root / "data" / "cards" / "cards.json").exists())


    def test_direct_cli_import_fallback_is_read_only(self):
        temp, root = self.make_project(
            '<h2 id="def">Definition</h2><p>TLB是用于缓存近期页表项的高速缓冲存储器。</p>')
        with temp:
            command = [sys.executable, "-I", str(builder.ROOT / "scripts" / "build_atomic_candidates.py"),
                       "--root", str(root)]
            result = subprocess.run(command, cwd=builder.ROOT, capture_output=True,
                                    text=True, check=False, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('"candidates": 1', result.stdout)
            self.assertIn("Dry-run: read-only", result.stdout)
            self.assertFalse((root / "data" / "reports").exists())
            self.assertFalse((root / "data" / "cards" / "cards.json").exists())

    def test_reviewed_or_edited_owned_candidate_is_preserved_as_conflict(self):
        temp, root = self.make_project('<h2 id="def">Definition</h2><p>TLB是用于缓存近期页表项的高速缓冲存储器。</p>')
        with temp:
            generated = builder.build_candidate_set(root)["candidates"][0]
            reviewed = {**generated, "status": "approved", "answer": "human-edited", "note": "preserve"}
            result = builder.reconcile_owned_cards([reviewed], [generated])
            self.assertEqual(result["cards"][0], reviewed)
            self.assertTrue(result["preservedConflicts"])


if __name__ == "__main__":
    unittest.main()
