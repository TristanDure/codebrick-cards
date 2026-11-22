import unittest

from scripts.co_pipeline_corrections import ARTICLE_URL, known_conflict, repair_summary_text


class PipelineCorrectionTests(unittest.TestCase):
    def test_hash_bound_source_conflicts_are_quarantined(self):
        unit = {
            "id": "a8df8e0d899f3836",
            "text": '🔴 判冒险要精确到"哪两条指令的哪两段落在同一个周期"，不能只看寄存器名相同。名字相同但时间上已经错开的，根本不构成冒险——这是这类题最主要的误判来源。',
        }
        self.assertTrue(known_conflict(ARTICLE_URL, unit))
        self.assertFalse(known_conflict(ARTICLE_URL + "?changed=1", unit))
        self.assertFalse(known_conflict(ARTICLE_URL.replace("pipeline-hazard", "other"), unit))
        self.assertFalse(known_conflict(ARTICLE_URL, {**unit, "text": unit["text"] + " changed"}))

    def test_summary_rewrite_is_scoped_and_removes_known_false_claims(self):
        raw = '名字相同但时间上已经错开的，根本不构成冒险。相隔 3 条以上的指令通常已经安全。2 位预测器更准是因为它连错两次才翻转方向。'
        fixed = repair_summary_text(ARTICLE_URL, raw)
        self.assertNotIn("相隔 3 条以上", fixed)
        self.assertNotIn("名字相同但时间上已经错开", fixed)
        self.assertIn("弱态", fixed)
        self.assertNotIn("用哪两段落在同一周期", fixed)
        self.assertEqual(repair_summary_text("https://example.test/article", raw), raw)

    def test_pipeline_branch_penalty_states_all_assumptions(self):
        raw = '控制冒险代价 [SVG公式/图示：img][公式：=] 判定所在段编号 [SVG公式/图示：img][公式：−1]，'
        fixed = repair_summary_text(ARTICLE_URL, raw)
        self.assertNotIn("[SVG公式", fixed)
        self.assertIn("每段1拍", fixed)
        self.assertIn("第d段末判定", fixed)
        self.assertIn("d−1拍", fixed)

    def test_quick_reference_same_cycle_only_claim_is_rewritten(self):
        raw = '把两条指令的时空图画出来，用哪两段落在同一周期来答。'
        fixed = repair_summary_text(ARTICLE_URL, raw)
        self.assertNotIn("用哪两段落在同一周期来答", fixed)
        self.assertIn("不能仅凭两段是否同周期", fixed)


if __name__ == "__main__":
    unittest.main()
