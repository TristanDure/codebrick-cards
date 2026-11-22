import copy
import hashlib
import unittest
from pathlib import Path

from scripts.build_disposition_ledger import EVIDENCE_ACTIONS, assemble, explain_empty, unique, unit_followups


class DispositionLedgerTests(unittest.TestCase):
    def fixture(self):
        url = 'https://example.test/article'
        unit = {'knowledgeUnitId': '0123456789abcdef', 'sourceId': 'os', 'articleUrl': url,
                'sectionIndex': 1, 'sectionHeadingPath': 'Body', 'sectionAnchor': 'body',
                'blockIndex': 2, 'unitIndex': 1, 'tag': 'p', 'text': 'Example source text',
                'reviewSourceSha256': 'b' * 64, 'presentInCurrentSource': True, 'cardIds': [],
                'reviewerDecision': 'pending'}
        unit['bodySha256'] = hashlib.sha256(unit['text'].encode()).hexdigest()
        articles = {'articles': [{'sourceId': 'os', 'url': url, 'title': 'Fixture',
                                  'contentHash': 'a' * 64, 'cache': '.cache/html/os.html'}]}
        source = {'units': [copy.deepcopy(unit)]}
        coverage = {'knowledgeUnits': [unit], 'sections': [{'articleUrl': url, 'sectionIndex': 1,
            'sectionHeadingPath': 'Body', 'sectionAnchor': 'body', 'sourceBlockCount': 1,
            'knowledgeUnitIds': [unit['knowledgeUnitId']]}], 'sourceParseFailures': []}
        atomic = {'unitAudit': [{'unitId': unit['knowledgeUnitId'], 'status': 'backlog',
                  'reason': 'no-safe-atomic-recall-pattern'}], 'candidates': [], 'articleErrors': []}
        return articles, source, coverage, atomic, {'records': []}, [], {}

    def test_exact_item_coverage_and_no_generated_human_approval(self):
        args = self.fixture()
        untouched = copy.deepcopy(args)
        report = assemble(Path('.'), *args)
        self.assertEqual(args, untouched)
        self.assertEqual(report['scope'], {'articleCount': 1, 'sectionCount': 1,
                                          'sourceUnitCount': 1, 'emptySectionCount': 0})
        self.assertEqual(report['sourceUnits'][0]['disposition'], 'needs-evidence-or-authoring')
        self.assertFalse(report['sourceUnits'][0]['humanApprovalGenerated'])
        self.assertFalse(report['full408Acceptance'])
        task = report['sourceUnits'][0]['evidenceTasks'][0]
        self.assertEqual(task['targetKnowledgeUnitId'], args[2]['knowledgeUnits'][0]['knowledgeUnitId'])
        self.assertEqual(task['responsibleRole'], 'article-card-author')
        self.assertEqual(task['action'], 'author-complete-atomic-question')
        self.assertTrue(task['missingEvidence'])

    def test_duplicate_source_ids_missing_audit_and_wrong_hash_are_errors(self):
        args = list(self.fixture())
        args[2]['knowledgeUnits'].append(copy.deepcopy(args[2]['knowledgeUnits'][0]))
        with self.assertRaisesRegex(ValueError, 'duplicate source unit'):
            assemble(Path('.'), *args)
        args = list(self.fixture())
        args[3]['unitAudit'] = []
        with self.assertRaisesRegex(ValueError, 'no current atomic disposition'):
            assemble(Path('.'), *args)
        args = list(self.fixture())
        args[2]['knowledgeUnits'][0]['bodySha256'] = 'c' * 64
        with self.assertRaisesRegex(ValueError, 'Source text hash mismatch'):
            assemble(Path('.'), *args)

    def test_all_atomic_candidates_are_retained_per_source_unit(self):
        args = list(self.fixture())
        uid = args[2]['knowledgeUnits'][0]['knowledgeUnitId']
        args[3]['candidates'] = [{'id': 'first', 'sourceUnitId': uid}, {'id': 'second', 'sourceUnitId': uid}]
        args[3]['unitAudit'] = [{'unitId': uid, 'status': 'candidate-generated', 'reason': 'definition'}]
        report = assemble(Path('.'), *args)
        self.assertEqual(report['sourceUnits'][0]['atomicCandidateIds'], ['first', 'second'])
        self.assertEqual(report['sourceUnits'][0]['disposition'], 'candidate-awaits-review')

    def test_context_headers_and_known_source_conflicts_do_not_become_cards(self):
        for reason, expected in [('table-column-headers', 'context-awaits-linkage'),
                                 ('known-source-factual-conflict', 'conflict')]:
            args = list(self.fixture())
            args[3]['unitAudit'][0]['reason'] = reason
            report = assemble(Path('.'), *args)
            self.assertEqual(report['sourceUnits'][0]['disposition'], expected)

    def test_empty_static_absence_is_explained_not_closed(self):
        record = {'cache': {'contentHashMatches': True}, 'parserSectionLocatorMatches': True,
                  'directBodyBlockCount': 0, 'subtreeBodyBlockCount': 0}
        status, action, reason = explain_empty(record)
        self.assertEqual(status, 'explained-static-absence-only')
        self.assertIn('static absence only', reason)
        self.assertEqual(action, 'verify-source-omission-or-lazy-loading')
        record['cache']['contentHashMatches'] = False
        self.assertEqual(explain_empty(record)[0], 'needs-evidence')

    def test_sibling_links_remain_sibling_evidence(self):
        record = {'cache': {'contentHashMatches': True}, 'parserSectionLocatorMatches': True,
                  'directBodyBlockCount': 0, 'subtreeBodyBlockCount': 0,
                  'sameLevelFollowingPracticeQuestionLinkCount': 2}
        status, action, reason = explain_empty(record)
        self.assertEqual(status, 'explained-sibling-index-component')
        self.assertIn('not reassigned', reason)

    def test_duplicate_article_and_section_locators_are_rejected(self):
        with self.assertRaises(ValueError):
            unique([{'id': 1}, {'id': 1}], lambda x: x['id'], 'fixture')

    def test_candidate_followups_have_reason_specific_review_contracts(self):
        unit = self.fixture()[2]['knowledgeUnits'][0]
        reasons = ['table-row-with-column-context', 'label-explanation', 'is-definition',
                   'formula-context-cloze', 'code-with-adjacent-prose-context', 'properties',
                   'definition', 'classification', 'causal-relation', 'mechanism', 'composition']
        tasks = unit_followups(unit, reasons, True)
        self.assertEqual(len(tasks), len(reasons))
        for task in tasks:
            self.assertIn(task['reason'], EVIDENCE_ACTIONS)
            self.assertNotEqual(task['action'], 'review-generated-card')
            self.assertEqual(task['targetKnowledgeUnitId'], unit['knowledgeUnitId'])
            self.assertEqual(task['sourceTextSha256'], unit['bodySha256'])
            self.assertTrue(task['missingEvidence'])


if __name__ == '__main__':
    unittest.main()
