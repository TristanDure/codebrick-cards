import copy
import hashlib
import json
import unittest
from unittest.mock import patch
from pathlib import Path

from scripts.audit_content_batch import audit, main, text_sha
from scripts import audit_content_batch as batch_tool
from tests import test_import_curated_articles as fixtures


class ContentBatchTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.CuratedArticleAuditTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.root = self.fixture.root.resolve()
        self.rel = 'data/curated/fixture.json'
        proposal = self.fixture.proposal
        primary = proposal['cards'][0]
        self.review = {'schema': 'codebrick-batch-card-review', 'version': 1,
            'reviewer': {'kind': 'ai', 'name': 'independent-test-reviewer',
                         'role': 'independent-non-author-reviewer',
                         'independentOfAuthor': True, 'humanApproval': False},
            'reviewedAt': '2026-11-23T01:00:00+08:00',
            'candidate': {'path': self.rel, 'sha256': self.sha(self.rel)},
            'source': {'articleUrl': self.fixture.url,
                       'articleContentHash': self.fixture.content_hash,
                       'cachePath': self.fixture.cache_relative,
                       'rawHtmlSha256': self.sha(self.fixture.cache_relative)},
            'cards': [{'id': primary['cardId'], 'questionSha256': text_sha(primary['front']),
                       'answerSha256': text_sha(primary['back']), 'unitIds': primary['knowledgeUnitIds'],
                       'decision': 'PASS', 'checks': {key: 'PASS' for key in
                           ['accuracy', 'atomicity', 'assumptions', 'sourceMapping']},
                       'reason': 'Fixture evidence only, not a semantic approval.',
                       'counterexampleOrBoundary': 'Limited to synthetic facts.'}],
            'missingCoverage': {'unitIds': [], 'sectionIndices': [],
                                'issues': ['Official annual syllabus and real exams not evidenced.']},
            'fullArticleApproved': False, 'overall408Acceptance': False}
        self.review_rel = 'data/_reviews/review.json'
        self.write(self.review_rel, self.review)
        self.batch = {'schema': 'codebrick-content-review-batch', 'version': 1,
                      'batchId': 'fixture-batch', 'targetYear': 2027,
                      'entries': [{'candidatePath': self.rel, 'candidateSha256': self.sha(self.rel),
                                   'reviewPath': self.review_rel, 'reviewSha256': self.sha(self.review_rel)}]}
        self.batch_rel = Path('data/_reviews/batch.json')
        self.save()

    def sha(self, rel):
        return hashlib.sha256((self.root / rel).read_bytes()).hexdigest()

    def write(self, rel, value):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')

    def save(self):
        self.write(self.review_rel, self.review)
        self.batch['entries'][0]['reviewSha256'] = self.sha(self.review_rel)
        self.write(self.batch_rel, self.batch)

    def test_exact_review_is_read_only_and_never_human_approval(self):
        before = {path: path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        result = audit(self.root, self.batch_rel)
        self.assertEqual(result['summary']['cardDecisions'], {'PASS': 1})
        self.assertEqual(result['humanApprovalsGenerated'], 0)
        self.assertFalse(result['full408Acceptance'])
        self.assertFalse(result['articles'][0]['articleApproved'])
        self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_changed_candidate_bytes_and_review_binding_fail(self):
        self.batch['entries'][0]['candidateSha256'] = 'f' * 64
        self.save()
        with self.assertRaisesRegex(ValueError, 'stale candidate binding'):
            audit(self.root, self.batch_rel)
        self.batch['entries'][0]['candidateSha256'] = self.sha(self.rel)
        self.batch['entries'][0]['reviewSha256'] = 'f' * 64
        self.write(self.batch_rel, self.batch)
        with self.assertRaisesRegex(ValueError, 'stale review binding'):
            audit(self.root, self.batch_rel)

    def test_missing_or_duplicate_cards_and_wrong_text_hash_fail(self):
        original = copy.deepcopy(self.review)
        for values in [[], original['cards'] * 2]:
            self.review = {**copy.deepcopy(original), 'cards': values}
            self.save()
            with self.assertRaisesRegex(ValueError, 'every card exactly once'):
                audit(self.root, self.batch_rel)
        self.review = copy.deepcopy(original)
        self.review['cards'][0]['answerSha256'] = 'f' * 64
        self.save()
        with self.assertRaisesRegex(ValueError, 'card text or source mapping changed'):
            audit(self.root, self.batch_rel)

    def test_forged_human_approval_and_inconsistent_pass_fail(self):
        self.review['reviewer']['kind'] = 'human'
        self.save()
        with self.assertRaisesRegex(ValueError, 'non-author AI identity'):
            audit(self.root, self.batch_rel)
        self.review['reviewer']['kind'] = 'ai'
        self.review['cards'][0]['checks']['accuracy'] = 'FAIL'
        self.save()
        with self.assertRaisesRegex(ValueError, 'PASS conflicts'):
            audit(self.root, self.batch_rel)

    def test_missing_coverage_cannot_use_unknown_ids(self):
        self.review['missingCoverage']['unitIds'] = ['does-not-exist']
        self.save()
        with self.assertRaisesRegex(ValueError, 'unknown units'):
            audit(self.root, self.batch_rel)

    def test_pending_batch_is_not_a_pass(self):
        self.batch['entries'][0].pop('reviewPath')
        self.batch['entries'][0].pop('reviewSha256')
        self.write(self.batch_rel, self.batch)
        result = audit(self.root, self.batch_rel)
        self.assertEqual(result['summary']['cardDecisions'], {'UNREVIEWED': 1})
        self.assertFalse(result['articles'][0]['allCardTextPassClaim'])

    def test_cli_refuses_to_overwrite_and_rejects_outside_paths(self):
        result_path = self.root / 'data/_reviews/result.json'
        result_path.write_text('keep', encoding='utf-8')
        self.assertEqual(main(['--root', str(self.root), '--batch', str(self.batch_rel),
                               '--output', 'data/_reviews/result.json']), 1)
        self.assertEqual(result_path.read_text(encoding='utf-8'), 'keep')
        with self.assertRaisesRegex(ValueError, 'outside project'):
            audit(self.root, Path('../outside.json'))

    def test_dimension_fail_cannot_be_hidden_in_unproven_or_fail_with_all_pass(self):
        self.review['cards'][0]['checks']['accuracy'] = 'FAIL'
        self.review['cards'][0]['decision'] = 'UNPROVEN'
        self.save()
        with self.assertRaisesRegex(ValueError, 'decision conflicts'):
            audit(self.root, self.batch_rel)
        self.review['cards'][0]['checks']['accuracy'] = 'PASS'
        self.review['cards'][0]['decision'] = 'FAIL'
        self.save()
        with self.assertRaisesRegex(ValueError, 'decision conflicts'):
            audit(self.root, self.batch_rel)

    def test_missing_section_scope_cannot_use_duplicate_or_unknown_indices(self):
        section = self.fixture.units[0]['sectionIndex']
        for values in [[True], [section, section], [999999]]:
            self.review['missingCoverage']['sectionIndices'] = values
            self.save()
            with self.assertRaisesRegex(ValueError, 'valid section indices'):
                audit(self.root, self.batch_rel)
        self.review['missingCoverage']['sectionIndices'] = []
        self.review['missingCoverage']['unitIds'] = [self.fixture.units[0]['knowledgeUnitId']]
        self.save()
        with self.assertRaisesRegex(ValueError, 'missing section scope'):
            audit(self.root, self.batch_rel)

    def test_resolved_alias_and_duplicate_version_bytes_are_not_double_counted(self):
        self.batch['entries'].append({**self.batch['entries'][0],
                                     'candidatePath': 'data/curated/./fixture.json'})
        self.save()
        with self.assertRaisesRegex(ValueError, 'resolved batch candidate path'):
            audit(self.root, self.batch_rel)
        self.write('data/curated/copy.json', self.fixture.proposal)
        self.batch['entries'][-1]['candidatePath'] = 'data/curated/copy.json'
        self.batch['entries'][-1]['candidateSha256'] = self.sha('data/curated/copy.json')
        self.save()
        with self.assertRaisesRegex(ValueError, 'duplicate article candidate bytes'):
            audit(self.root, self.batch_rel)

    def test_failed_cards_cannot_report_zero_unit_and_section_gaps(self):
        self.review['cards'][0]['decision'] = 'FAIL'
        self.review['cards'][0]['checks']['accuracy'] = 'FAIL'
        self.save()
        with self.assertRaisesRegex(ValueError, 'failed/open-issue units'):
            audit(self.root, self.batch_rel)
        self.review['missingCoverage']['unitIds'] = list(self.review['cards'][0]['unitIds'])
        self.review['missingCoverage']['sectionIndices'] = [self.fixture.units[0]['sectionIndex']]
        self.save()
        self.assertEqual(audit(self.root, self.batch_rel)['summary']['cardDecisions'], {'FAIL': 1})

    def test_open_issue_knowledge_unit_alias_cannot_hide_missing_coverage(self):
        proposal = self.fixture.authored_proposal()
        uid = self.fixture.units[1]['knowledgeUnitId']
        proposal['issues'] = [{'id': 'fixture-open-issue', 'status': 'open',
                              'knowledgeUnitIds': [uid]}]
        self.write(self.rel, proposal)
        primary = proposal['cards'][0]
        self.review['candidate']['sha256'] = self.sha(self.rel)
        self.batch['entries'][0]['candidateSha256'] = self.sha(self.rel)
        self.review['cards'][0].update(id=primary['id'],
            questionSha256=text_sha(primary['question']),
            answerSha256=text_sha(primary['answer']), unitIds=primary['unitIds'])
        self.save()
        with self.assertRaisesRegex(ValueError, 'open-issue units'):
            audit(self.root, self.batch_rel)
        self.review['missingCoverage']['unitIds'] = [uid]
        self.review['missingCoverage']['sectionIndices'] = [self.fixture.units[1]['sectionIndex']]
        self.save()
        self.assertEqual(audit(self.root, self.batch_rel)['summary']['cardDecisions'], {'PASS': 1})

    def test_real_validation_followed_by_cache_mutation_is_rejected(self):
        cache = self.root / self.fixture.cache_relative
        original = batch_tool.curated._validate_proposal
        def mutate(*args, **kwargs):
            result = original(*args, **kwargs)
            self.assertTrue(result['ok'])
            raw = cache.read_bytes()
            cache.write_bytes(raw.replace(b'reliable concept', b'MUTATED concept'))
            return result
        with patch.object(batch_tool.curated, '_validate_proposal', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'source content drift'):
                audit(self.root, self.batch_rel)

    def test_manifest_changes_after_initial_read_are_detected_before_return(self):
        original = batch_tool.curated._validate_proposal
        def mutate(*args, **kwargs):
            result = original(*args, **kwargs)
            path = self.root / self.batch_rel
            path.write_bytes(path.read_bytes() + b' ')
            return result
        with patch.object(batch_tool.curated, '_validate_proposal', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'input snapshot drift'):
                audit(self.root, self.batch_rel)

    def test_shared_cache_binding_cannot_be_overwritten_by_later_revision(self):
        cache = self.root / self.fixture.cache_relative
        new_raw = cache.read_bytes() + b'<!-- capture mutation -->'
        rel = 'data/curated/revision.json'
        (self.root / rel).write_bytes((self.root / self.rel).read_bytes() + b' ')
        review = copy.deepcopy(self.review)
        review['candidate'] = {'path': rel, 'sha256': self.sha(rel)}
        review['source']['rawHtmlSha256'] = hashlib.sha256(new_raw).hexdigest()
        self.write('data/_reviews/revision-review.json', review)
        self.batch['entries'].append({'candidatePath': rel, 'candidateSha256': self.sha(rel),
            'reviewPath': 'data/_reviews/revision-review.json',
            'reviewSha256': self.sha('data/_reviews/revision-review.json')})
        self.save()
        real = batch_tool.curated._validate_proposal
        calls = 0
        def timing(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                cache.write_bytes(new_raw)
            result = real(*args, **kwargs)
            self.assertTrue(result['ok'])
            return result
        with patch.object(batch_tool.curated, '_validate_proposal', side_effect=timing):
            with self.assertRaisesRegex(ValueError, 'conflicting input snapshots'):
                audit(self.root, self.batch_rel)

    def test_reviewer_name_must_be_nonblank_string(self):
        for name in [' ', ['reviewer'], {'name': 'reviewer'}]:
            self.review['reviewer']['name'] = name
            self.save()
            with self.assertRaisesRegex(ValueError, 'non-author AI identity'):
                audit(self.root, self.batch_rel)

    def test_any_explicit_approval_flag_must_be_false(self):
        for flag in ('humanApproval', 'contentApproved', 'fullArticleApproved',
                     'overall408Acceptance', 'full408Acceptance'):
            for value in (True, 1, None, 'false'):
                with self.subTest(flag=flag, value=value):
                    self.review[flag] = value
                    self.save()
                    with self.assertRaisesRegex(ValueError, 'cannot claim approval'):
                        audit(self.root, self.batch_rel)
            self.review[flag] = False
        self.save()
        self.assertEqual(audit(self.root, self.batch_rel)['humanApprovalsGenerated'], 0)

    def test_declared_self_review_is_rejected_even_with_independence_claim(self):
        # Both supported candidate formats are exercised elsewhere; use the
        # authored fixture here because legacy format has no author metadata.
        proposal = self.fixture.authored_proposal()
        # This candidate has different fixture IDs; update the exact bindings.
        self.write(self.rel, proposal)
        primary = proposal['cards'][0]
        self.review['candidate']['sha256'] = self.sha(self.rel)
        self.batch['entries'][0]['candidateSha256'] = self.sha(self.rel)
        self.review['cards'][0].update(id=primary['id'],
            questionSha256=text_sha(primary['question']),
            answerSha256=text_sha(primary['answer']), unitIds=primary['unitIds'])
        self.review['reviewer']['name'] = proposal['author']['agent']
        self.save()
        with self.assertRaisesRegex(ValueError, 'identity collision'):
            audit(self.root, self.batch_rel)

    def test_distinct_authored_review_still_passes(self):
        proposal = self.fixture.authored_proposal()
        self.write(self.rel, proposal)
        primary = proposal['cards'][0]
        self.review['candidate']['sha256'] = self.sha(self.rel)
        self.batch['entries'][0]['candidateSha256'] = self.sha(self.rel)
        self.review['cards'][0].update(id=primary['id'],
            questionSha256=text_sha(primary['question']),
            answerSha256=text_sha(primary['answer']), unitIds=primary['unitIds'])
        self.save()
        self.assertEqual(audit(self.root, self.batch_rel)['summary']['cardDecisions'], {'PASS': 1})

    def test_known_nested_approval_flag_must_be_exact_false(self):
        for value in (True, 1, None, 'false'):
            self.review['reviewer']['full408Acceptance'] = value
            self.save()
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'cannot claim approval'):
                audit(self.root, self.batch_rel)
        self.review['reviewer']['full408Acceptance'] = False
        self.save()
        self.assertEqual(audit(self.root, self.batch_rel)['humanApprovalsGenerated'], 0)

    def test_reviewer_approval_fields_cannot_contradict_top_level(self):
        for flag in ('contentApproved', 'fullArticleApproved',
                     'overall408Acceptance', 'full408Acceptance'):
            self.review['reviewer'][flag] = True
            self.save()
            with self.subTest(flag=flag), self.assertRaisesRegex(ValueError, 'cannot claim approval'):
                audit(self.root, self.batch_rel)
            self.review['reviewer'][flag] = False

    def test_nonclosed_issue_statuses_require_both_source_aliases(self):
        original = self.fixture.authored_proposal()
        uid = self.fixture.units[1]['knowledgeUnitId']
        primary = original['cards'][0]
        self.review['cards'][0].update(id=primary['id'],
            questionSha256=text_sha(primary['question']),
            answerSha256=text_sha(primary['answer']), unitIds=primary['unitIds'])
        for status in ('OPEN', 'unresolved', 'open-source-conflict', 'awaiting-evidence'):
            proposal = copy.deepcopy(original)
            proposal['issues'] = [{'status': status, 'unitIds': [], 'knowledgeUnitIds': [uid]}]
            self.write(self.rel, proposal)
            self.review['candidate']['sha256'] = self.sha(self.rel)
            self.batch['entries'][0]['candidateSha256'] = self.sha(self.rel)
            self.review['missingCoverage']['unitIds'] = []
            self.review['missingCoverage']['sectionIndices'] = []
            self.save()
            with self.subTest(status=status), self.assertRaisesRegex(ValueError, 'open-issue units'):
                audit(self.root, self.batch_rel)
            self.review['missingCoverage']['unitIds'] = [uid]
            self.review['missingCoverage']['sectionIndices'] = [self.fixture.units[1]['sectionIndex']]
            self.save()
            self.assertEqual(audit(self.root, self.batch_rel)['summary']['cardDecisions'], {'PASS': 1})

    def test_identity_aliases_and_generic_labels(self):
        check = batch_tool.reject_declared_self_review
        for author, reviewer in [({'agentId': 'agent-001'}, {'threadId': ' AGENT-001 '}),
                                 ({'name': 'Zeno'}, {'agent': ' zEnO '}),
                                 ({'agent': 'Raman'}, {'name': 'Raman-independent-reviewer'})]:
            with self.assertRaisesRegex(ValueError, 'identity collision'):
                check(author, reviewer)
        for author, reviewer in [({}, {'name': 'Zeno'}),
                                 ({'name': 'Codex'}, {'name': 'codex'}),
                                 ({'agentId': 'agent-001'}, {'agentId': 'agent-002'}),
                                 ({'agent': 'Codex'}, {'name': 'Reviewer-Codex'}),
                                 ({'name': 'Zeno'}, {'name': 'SeparateReviewer-Zeno'})]:
            check(author, reviewer)  # no collision is not authenticated independence

    def test_generator_hash_is_pinned_when_module_is_loaded(self):
        expected = batch_tool.GENERATOR_SHA256
        original = Path.read_bytes
        def changed_source(path):
            if path.resolve() == Path(batch_tool.__file__).resolve():
                return b'changed generator source'
            return original(path)
        with patch.object(Path, 'read_bytes', changed_source):
            with self.assertRaisesRegex(ValueError, 'generator source drift'):
                audit(self.root, self.batch_rel)
        self.assertEqual(batch_tool.GENERATOR_SHA256, expected)
        self.assertEqual(audit(self.root, self.batch_rel)['generator']['sha256'], expected)


if __name__ == '__main__':
    unittest.main()
