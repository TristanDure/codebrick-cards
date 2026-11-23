import json
import unittest
from unittest.mock import patch

from scripts import build_content_scope_snapshot as scope
from tests import test_content_batch as fixtures


class ContentScopeSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.ContentBatchTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.root = self.f.root

    def build(self):
        return scope.build(self.root, self.f.batch_rel)

    def test_read_only_exact_version_scope_never_approves(self):
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        d = self.build()
        self.assertEqual(d['corpus']['cardDecisions'], {'PASS': 1})
        self.assertEqual(d['corpus']['reviewedVersionArticles'], 1)
        self.assertTrue(d['articleScopes'][0]['reviewedVersionOnly'])
        self.assertFalse(d['articleScopes'][0]['fullArticleApproved'])
        self.assertFalse(d['full408Acceptance'])
        self.assertEqual(d['humanApprovalsGenerated'], 0)
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_pending_version_is_not_reviewed_or_pass(self):
        e = self.f.batch['entries'][0]
        e.pop('reviewPath'); e.pop('reviewSha256')
        self.f.write(self.f.batch_rel, self.f.batch)
        d = self.build()
        self.assertEqual(d['corpus']['cardDecisions'], {'UNREVIEWED': 1})
        self.assertEqual(d['corpus']['reviewedVersionArticles'], 0)
        self.assertIsNone(d['articleScopes'][0]['reviewMissingCoverage'])

    def test_unproven_and_missing_units_survive(self):
        c = self.f.review['cards'][0]
        c['checks']['sourceMapping'] = 'UNPROVEN'; c['decision'] = 'UNPROVEN'
        self.f.review['missingCoverage']['unitIds'] = c['unitIds'][:]
        self.f.review['missingCoverage']['sectionIndices'] = [self.f.fixture.units[0]['sectionIndex']]
        self.f.save()
        d = self.build()
        self.assertEqual(d['corpus']['cardDecisions'], {'UNPROVEN': 1})
        self.assertEqual(d['articleScopes'][0]['reviewMissingCoverage']['unitIds'], c['unitIds'])
        self.assertFalse(d['articleScopes'][0]['allCardTextPassClaim'])

    def test_fresh_audit_rejects_stale_candidate(self):
        (self.root/self.f.rel).write_text('{}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'stale candidate'):
            self.build()

    def test_new_authored_revision_does_not_transfer_pass(self):
        self.f.write('data/curated/unreviewed-latest.json', {'unreviewed': True})
        d = self.build()
        self.assertEqual(d['articleScopes'][0]['reviewedCandidatePath'], self.f.rel)
        self.assertTrue(any('not the latest authored' in x for x in d['limits']))

    def test_post_audit_input_drift_rejected(self):
        original = scope.audit
        def drift(*args):
            result = original(*args)
            (self.root/self.f.rel).write_text('{}', encoding='utf-8')
            return result
        with patch.object(scope, 'audit', side_effect=drift):
            with self.assertRaisesRegex(ValueError, 'input drift'):
                self.build()

    def test_duplicate_article_versions_are_not_double_counted(self):
        original = scope.audit
        def duplicate(*args):
            result = original(*args)
            result['articles'].append(result['articles'][0].copy())
            return result
        with patch.object(scope, 'audit', side_effect=duplicate):
            with self.assertRaisesRegex(ValueError, 'one reviewed candidate version'):
                self.build()

    def test_generator_drift_rejected(self):
        with patch.object(scope, 'GENERATOR_SHA256', '0'*64):
            with self.assertRaisesRegex(ValueError, 'generator source drift'):
                self.build()

    def test_cli_new_output_only_and_outside_rejected(self):
        args = ['--root', str(self.root), '--batch', str(self.f.batch_rel),
                '--output', 'data/_reviews/scope.json']
        self.assertEqual(scope.main(args), 0)
        p = self.root/'data/_reviews/scope.json'
        before = p.read_bytes()
        self.assertEqual(scope.main(args), 1)
        self.assertEqual(p.read_bytes(), before)
        self.assertEqual(scope.main(args[:-1] + ['../outside.json']), 1)
        self.assertEqual(json.loads(before)['humanApprovalsGenerated'], 0)


if __name__ == '__main__':
    unittest.main()
