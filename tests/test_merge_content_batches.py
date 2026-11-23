import copy
import json
import unittest
from pathlib import Path

from scripts import merge_content_batches as merger
from tests import test_content_batch as fixtures


class MergeContentBatchesTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.ContentBatchTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.root = self.f.root
        self.base = self.f.batch_rel
        self.add = Path('data/_reviews/add.json')
        self.candidate2 = 'data/curated/revision.json'
        self.review2 = 'data/_reviews/revision-review.json'
        p = copy.deepcopy(self.f.fixture.proposal)
        p['cards'][0]['back'] += ' Revised wording.'
        self.f.write(self.candidate2, p)
        r = copy.deepcopy(self.f.review)
        r['candidate'] = {'path': self.candidate2, 'sha256': self.f.sha(self.candidate2)}
        from scripts.audit_content_batch import text_sha
        r['cards'][0]['answerSha256'] = text_sha(p['cards'][0]['back'])
        self.f.write(self.review2, r)
        self.add_doc = copy.deepcopy(self.f.batch)
        self.add_doc['entries'] = [{'candidatePath': self.candidate2,
            'candidateSha256': self.f.sha(self.candidate2),
            'reviewPath': self.review2, 'reviewSha256': self.f.sha(self.review2)}]
        self.f.write(self.add, self.add_doc)

    def merge(self):
        return merger.merge(self.root, self.base, self.add, 'merged')

    def test_replaces_by_article_url_without_counting_old_cards(self):
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result = self.merge()
        self.assertEqual(len(result['entries']), 1)
        self.assertEqual(result['entries'][0]['candidatePath'], self.candidate2)
        self.assertEqual(result['transitions'][0]['action'], 'replace')
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_rejects_duplicate_article_versions_in_base(self):
        d = copy.deepcopy(self.f.batch)
        d['entries'] += self.add_doc['entries']
        self.f.write(self.base, d)
        with self.assertRaisesRegex(ValueError, 'duplicate articleUrl'):
            self.merge()

    def test_rejects_duplicate_article_versions_in_additions(self):
        self.add_doc['entries'] += self.f.batch['entries']
        self.f.write(self.add, self.add_doc)
        with self.assertRaisesRegex(ValueError, 'duplicate articleUrl'):
            self.merge()

    def test_rejects_stale_binding(self):
        self.add_doc['entries'][0]['candidateSha256'] = '0' * 64
        self.f.write(self.add, self.add_doc)
        with self.assertRaisesRegex(ValueError, 'stale candidate'):
            self.merge()

    def test_rejects_year_mismatch(self):
        self.add_doc['targetYear'] = 2026
        self.f.write(self.add, self.add_doc)
        with self.assertRaisesRegex(ValueError, 'target years differ'):
            self.merge()

    def test_noop_rejected(self):
        with self.assertRaisesRegex(ValueError, 'no new review'):
            merger.merge(self.root, self.base, self.base, 'noop')

    def test_pending_update_rejected(self):
        e = self.add_doc['entries'][0]
        e.pop('reviewPath'); e.pop('reviewSha256')
        self.f.write(self.add, self.add_doc)
        with self.assertRaisesRegex(ValueError, 'unreviewed addition'):
            self.merge()

    def test_fail_is_recorded_not_laundered_into_pass(self):
        r = json.loads((self.root / self.review2).read_text('utf-8'))
        c = r['cards'][0]
        c['checks']['accuracy'] = 'FAIL'; c['decision'] = 'FAIL'
        r['missingCoverage']['unitIds'] = list(c['unitIds'])
        r['missingCoverage']['sectionIndices'] = [self.f.fixture.units[0]['sectionIndex']]
        self.f.write(self.review2, r)
        self.add_doc['entries'][0]['reviewSha256'] = self.f.sha(self.review2)
        self.f.write(self.add, self.add_doc)
        result = self.merge()
        self.f.write('data/_reviews/merged.json', result)
        a = merger.audit(self.root, Path('data/_reviews/merged.json'))
        self.assertEqual(a['summary']['cardDecisions'], {'FAIL': 1})
        self.assertFalse(a['full408Acceptance'])
        self.assertEqual(a['humanApprovalsGenerated'], 0)

    def args(self):
        return ['--root', str(self.root), '--base', str(self.base), '--add', str(self.add),
                '--output', 'data/_reviews/new.json', '--audit-output', 'data/_reviews/new-audit.json']

    def test_cli_writes_audited_unique_snapshot_and_refuses_overwrite(self):
        self.assertEqual(merger.main(self.args()), 0)
        a = json.loads((self.root/'data/_reviews/new-audit.json').read_text('utf-8'))
        self.assertEqual(a['summary']['batchCandidateVersions'], 1)
        before = (self.root/'data/_reviews/new.json').read_bytes()
        self.assertEqual(merger.main(self.args()), 1)
        self.assertEqual((self.root/'data/_reviews/new.json').read_bytes(), before)

    def test_cli_rejects_identical_output_paths_and_outside_root(self):
        args = self.args(); args[-1] = args[-3]
        self.assertEqual(merger.main(args), 1)
        args = self.args(); args[-3] = '../outside.json'
        self.assertEqual(merger.main(args), 1)
        self.assertFalse((self.root/'data/_reviews/new-audit.json').exists())


    def test_unproven_decision_survives_merge_without_approval(self):
        unit_id = self.f.fixture.units[0]['knowledgeUnitId']
        review = json.loads((self.root / self.review2).read_text(encoding='utf-8'))
        review['cards'][0]['decision'] = 'UNPROVEN'
        review['cards'][0]['checks']['sourceMapping'] = 'UNPROVEN'
        review['cards'][0]['reason'] = 'Evidence mapping remains unproven in this synthetic fixture.'
        review['missingCoverage']['unitIds'] = [unit_id]
        review['missingCoverage']['sectionIndices'] = [self.f.fixture.units[0]['sectionIndex']]
        self.f.write(self.review2, review)
        self.add_doc['entries'][0]['reviewSha256'] = self.f.sha(self.review2)
        self.f.write(self.add, self.add_doc)
        result = self.merge()
        self.f.write('data/_reviews/merged-unproven.json', result)
        audited = merger.audit(self.root, Path('data/_reviews/merged-unproven.json'))
        self.assertEqual(audited['summary']['cardDecisions'], {'UNPROVEN': 1})
        self.assertFalse(audited['humanApprovalsGenerated'])
        self.assertFalse(audited['full408Acceptance'])


if __name__ == '__main__':
    unittest.main()
