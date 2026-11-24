"""Offline regression tests for workbench candidate labels and approval boundaries."""
from pathlib import Path
import json
import re
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "web" / "workbench.js").read_text(encoding="utf-8")


class WorkbenchLabelTests(unittest.TestCase):
    def card_kind_expression(self):
        match = re.search(
            r'byId\("cardKind"\)\.textContent\s*=\s*(.*?);', SOURCE
        )
        self.assertIsNotNone(match, "renderCard must set the cardKind label")
        return re.sub(r"\s+", " ", match.group(1)).strip()

    def test_curated_label_is_neutral_and_does_not_claim_review_failure(self):
        expression = self.card_kind_expression()
        self.assertIn("精编候选 · 未获内容批准", expression)
        self.assertNotIn("独立评审未通过", expression)
        self.assertNotIn("AI PASS", expression)
        self.assertNotIn("正式批准", expression)

    def test_machine_candidates_remain_pending_semantic_review(self):
        expression = self.card_kind_expression()
        self.assertIn('card.pool === "curated"', expression)
        self.assertIn("机器候选 · 待语义核验", expression)

    def test_empty_filtered_deck_is_not_mislabeled_as_a_machine_candidate(self):
        expression = self.card_kind_expression()
        self.assertRegex(expression, r"!card \? \"当前筛选无候选\"")
        self.assertIn("card?.question || \"本筛选条件暂无候选卡片\"", SOURCE)
        self.assertIn('byId("flip").disabled = !card;', SOURCE)

    def test_frontend_label_does_not_infer_approval_from_content(self):
        expression = self.card_kind_expression()
        # The label depends only on whether a card exists and its pool, never its
        # question/answer, filename, review metadata, or approval-like fields.
        self.assertEqual(expression.count("card"), 2)
        for forbidden in ("question", "answer", "file", "review", "Approved", "PASS", "approved"):
            self.assertNotIn(forbidden, expression)
        self.assertIn('data.contentApproved !== false', SOURCE)
        self.assertIn('value.contentApproved !== false', SOURCE)


@unittest.skipUnless(shutil.which("node"), "Node.js is required to exercise the actual renderer")
class WorkbenchRenderTests(unittest.TestCase):
    def test_actual_render_labels_empty_state_and_untrusted_approval_hints(self):
        # Execute the exact renderCard body in a minimal offline DOM, without
        # loading the app, network, localStorage, or third-party packages.
        start = SOURCE.index("  function renderCard() {")
        end = SOURCE.index("  function reveal()", start)
        renderer = SOURCE[start:end]
        harness = r"""
const renderSource = JSON.parse(process.argv[1]);
const elements = new Map();
const byId = id => {
  if (!elements.has(id)) elements.set(id, {textContent: "", hidden: false, disabled: false});
  return elements.get(id);
};
const article = {sections: [{index: 1, headingPath: "test section"}]};
let deck = [], at = 0;
const renderContent = (el, value) => {el.textContent = value;};
const review = () => null;
const renderSources = () => {};
eval(renderSource);
const card = pool => ({pool, question: "AI PASS", answer: "正式批准", sections: [1],
  assumptions: [], sourceNotes: [], draft: "all-pass-approved.json",
  contentApproved: true, humanApproval: true, decision: "PASS"});
function snapshot(value) {
  deck = value ? [value] : []; at = 0; renderCard();
  return Object.fromEntries([...elements].map(([key, el]) => [key, {...el}]));
}
const curated = snapshot(card("curated"));
const atomic = snapshot(card("atomic"));
// Test transitions, not just a fresh DOM: stale card labels must be cleared.
const emptyAfterAtomic = snapshot(null);
snapshot(card("curated"));
const emptyAfterCurated = snapshot(null);
console.log(JSON.stringify({curated, atomic, emptyAfterAtomic, emptyAfterCurated}));
"""
        completed = subprocess.run(
            [shutil.which("node"), "-e", harness, json.dumps(renderer)],
            text=True, encoding="utf-8", capture_output=True, check=True, timeout=15,
        )
        output = json.loads(completed.stdout)
        self.assertEqual(output["curated"]["cardKind"]["textContent"], "精编候选 · 未获内容批准")
        self.assertEqual(output["atomic"]["cardKind"]["textContent"], "机器候选 · 待语义核验")
        for key in ("emptyAfterAtomic", "emptyAfterCurated"):
            with self.subTest(transition=key):
                state = output[key]
                self.assertEqual(state["cardKind"]["textContent"], "当前筛选无候选")
                self.assertEqual(state["position"]["textContent"], "0 / 0")
                self.assertEqual(state["cardQuestion"]["textContent"], "本筛选条件暂无候选卡片")
                self.assertEqual(state["cardAnswer"]["textContent"], "")
                self.assertEqual(state["sourceNotes"]["textContent"], "")
                self.assertEqual(state["dueStatus"]["textContent"], "")
                self.assertTrue(state["answerBox"]["hidden"])
                for control in ("flip", "previous", "next"):
                    self.assertTrue(state[control]["disabled"])


if __name__ == "__main__":
    unittest.main()
