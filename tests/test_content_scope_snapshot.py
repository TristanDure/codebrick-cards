import copy
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
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

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

    def test_four_subject_real_audit_keeps_mixed_decisions_and_outside_articles(self):
        # End-to-end through audit_content_batch, not mocked subject totals.
        from scripts import import_curated_articles as curated
        articles = [copy.deepcopy(self.f.fixture.article_record)]
        units = copy.deepcopy(self.f.fixture.units)
        for subject, decision in [('co', 'FAIL'), ('cn', 'UNPROVEN'), ('ds', 'UNREVIEWED')]:
            url = f'https://example.test/{subject}/article.html'
            cache = f'.cache/html/{subject}/article.html'
            raw = self.f.fixture.raw.replace('First source fact', subject + ' source fact')
            path = self.root/cache
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(raw, encoding='utf-8')
            parsed = curated.sync_sources.parse_article(raw, url)
            content_hash = curated._hash_parsed_article(parsed)
            article = {'sourceId': subject, 'title': parsed['title'], 'url': url,
                       'cache': cache, 'contentHash': content_hash}
            articles.append(article)
            new_units = []
            for section in curated.sync_sources.sections(parsed):
                for block in section['sourceUnits']:
                    for unit in block['units']:
                        row = copy.deepcopy(self.f.fixture.units[0])
                        row.update(knowledgeUnitId=unit['id'], sourceId=subject,
                                   articleUrl=url, sectionIndex=section['sectionIndex'],
                                   sectionHeadingPath=section['headingPath'],
                                   blockIndex=unit['blockIndex'], unitIndex=unit['unitIndex'],
                                   tag=unit['tag'], text=unit['text'])
                        new_units.append(row)
            units.extend(new_units)
            primary, context = new_units
            card_id = curated.stable_card_id(url, [primary['knowledgeUnitId']])
            proposal = copy.deepcopy(self.f.fixture.proposal)
            proposal['article'] = article
            proposal['sourceUnits'][0].update(knowledgeUnitId=primary['knowledgeUnitId'], cardId=card_id)
            proposal['sourceUnits'][1]['knowledgeUnitId'] = context['knowledgeUnitId']
            card = proposal['cards'][0]
            card.update(cardId=card_id, articleUrl=url,
                        knowledgeUnitIds=[primary['knowledgeUnitId']])
            rel = f'data/curated/{subject}.json'
            self.f.write(rel, proposal)
            entry = {'candidatePath': rel, 'candidateSha256': self.f.sha(rel)}
            if decision != 'UNREVIEWED':
                review = copy.deepcopy(self.f.review)
                review['candidate'] = {'path': rel, 'sha256': self.f.sha(rel)}
                review['source'] = {'articleUrl': url, 'articleContentHash': content_hash,
                                    'cachePath': cache, 'rawHtmlSha256': self.f.sha(cache)}
                row = review['cards'][0]
                row.update(id=card_id, unitIds=card['knowledgeUnitIds'], decision=decision)
                row['checks']['accuracy'] = decision
                review['missingCoverage'].update(unitIds=card['knowledgeUnitIds'],
                                                sectionIndices=[primary['sectionIndex']])
                review_rel = f'data/_reviews/{subject}.json'
                self.f.write(review_rel, review)
                entry.update(reviewPath=review_rel, reviewSha256=self.f.sha(review_rel))
            self.f.batch['entries'].append(entry)
        outside = copy.deepcopy(articles[-1])
        outside.update(url='https://example.test/ds/outside.html', title='Outside batch')
        articles.append(outside)
        inactive = copy.deepcopy(units[-1])
        inactive.update(knowledgeUnitId='inactive-only', articleUrl=outside['url'],
                        presentInCurrentSource=False)
        units.append(inactive)
        self.f.write('data/articles.json', {'version': 1, 'articles': articles})
        self.f.write('data/knowledge-units.json', {'version': 2, 'units': units})
        self.f.save()
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result = self.build()
        self.assertEqual(result['corpus']['batchArticles'], 4)
        self.assertEqual(result['corpus']['outsideBatchArticles'], 1)
        self.assertEqual(result['corpus']['activeSourceUnits'], 8)
        self.assertEqual(result['corpus']['reviewedVersionArticles'], 3)
        self.assertEqual(result['corpus']['cardDecisions'],
                         {'PASS': 1, 'FAIL': 1, 'UNPROVEN': 1, 'UNREVIEWED': 1})
        for subject, decision in [('os', 'PASS'), ('co', 'FAIL'),
                                  ('cn', 'UNPROVEN'), ('ds', 'UNREVIEWED')]:
            with self.subTest(subject=subject):
                expected = {key: int(key == decision)
                            for key in ('PASS', 'UNPROVEN', 'FAIL', 'UNREVIEWED')}
                subject_scope = result['subjects'][subject]
                self.assertEqual(subject_scope['decisions'], expected)
                self.assertEqual(subject_scope['cards'], 1)
                self.assertEqual(subject_scope['batchArticles'], 1)
                self.assertEqual(subject_scope['reviewedVersionArticles'], int(subject != 'ds'))
                self.assertEqual(subject_scope['activeSourceUnits'], 2)
                self.assertEqual(subject_scope['articles'], 2 if subject == 'ds' else 1)
                self.assertEqual(subject_scope['outsideBatchArticles'], int(subject == 'ds'))
                article_scope, = [row for row in result['articleScopes']
                                  if row['sourceId'] == subject]
                self.assertEqual(article_scope['decisions'], {decision: 1})
                expected_review = (None if subject == 'ds' else
                                   self.f.review_rel if subject == 'os' else
                                   f'data/_reviews/{subject}.json')
                self.assertEqual(article_scope['reviewPath'], expected_review)
                self.assertFalse(article_scope['fullArticleApproved'])
        self.assertEqual(result['subjects']['ds']['outsideBatchArticles'], 1)
        self.assertEqual(result['subjects']['ds']['reviewedVersionArticles'], 0)
        self.assertEqual(result['subjects']['ds']['activeSourceUnits'], 2)
        self.assertEqual(result['remainingArticlesOutsideBatch'][0]['url'], outside['url'])
        self.assertFalse(result['full408Acceptance'])
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

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
