import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import audit_card_technical_evidence as tool


class TechnicalEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.path = Path('data/candidate.json')
        snapshot = self.root / '.cache/technical.txt'
        snapshot.parent.mkdir(parents=True)
        snapshot.write_text('Exact technical quote. Another statement.', encoding='utf-8')
        self.binding = {'path': '.cache/technical.txt', 'sha256': hashlib.sha256(snapshot.read_bytes()).hexdigest()}
        self.item = {'id': 'technical-1', 'kind': 'technical-document', 'publisher': 'Fixture author',
                     'scope': 'Technical support only; not official exam scope.', 'url': 'https://example.test/doc',
                     'cardIds': ['c1'], 'snapshots': [self.binding],
                     'locator': {**self.binding, 'quote': 'Exact technical quote.', 'location': 'paragraph 1'}}
        self.doc = {'schema': 'codebrick-curated-article', 'version': 1,
                    'cards': [{'id': 'c1'}], 'metadata': {'externalCardEvidence': [self.item]}}
        self.save()

    def save(self):
        path = self.root / self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.doc), encoding='utf-8')

    def run_audit(self):
        self.save()
        return tool.audit(self.root, self.path)

    def make_review(self):
        self.save()
        self.review_path = Path('data/review.json')
        observed = copy.deepcopy(self.item)
        observed['snapshots'][0]['bytes'] = (self.root / self.binding['path']).stat().st_size
        observed['locator']['quoteSha256'] = hashlib.sha256(self.item['locator']['quote'].encode()).hexdigest()
        self.review = {'schema': 'codebrick-batch-card-review', 'version': 1,
                       'candidate': {'path': self.path.as_posix(), 'sha256': hashlib.sha256((self.root / self.path).read_bytes()).hexdigest()},
                       'reviewer': {'kind': 'ai', 'name': 'Fixture Reviewer', 'role': 'independent-non-author-reviewer', 'independentOfAuthor': True, 'humanApproval': False},
                       'humanApproval': False, 'fullArticleApproved': False, 'overall408Acceptance': False,
                       'externalEvidence': [observed]}
        self.save_review()

    def save_review(self):
        (self.root / self.review_path).write_text(json.dumps(self.review), encoding='utf-8')

    def test_valid_bindings_never_grant_approval_or_authenticity(self):
        result = self.run_audit()
        self.assertEqual(result['evidenceItems'], 1)
        self.assertTrue(result['localBindingsConsistent'])
        for field in ['sourceAuthenticityVerified', 'semanticSupportVerified', 'fullArticleApproved', 'full408Acceptance']:
            self.assertFalse(result[field])
        self.assertEqual(result['humanApprovalsGenerated'], 0)

    def test_snapshot_tampering_rejected(self):
        (self.root / self.binding['path']).write_text('changed')
        with self.assertRaisesRegex(ValueError, 'stale'):
            self.run_audit()

    def test_quote_must_exist_and_be_nonempty(self):
        for quote in ['nonexistent quote', '']:
            self.item['locator']['quote'] = quote
            with self.assertRaises(ValueError):
                self.run_audit()

    def test_locator_requires_bound_snapshot_and_location(self):
        self.item['locator']['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'locator must bind'):
            self.run_audit()
        self.item['locator'] = {**self.binding, 'quote': 'Exact technical quote.', 'location': ''}
        with self.assertRaisesRegex(ValueError, 'precise location'):
            self.run_audit()

    def test_duplicate_ids_or_paths_rejected(self):
        self.doc['metadata']['externalCardEvidence'].append(copy.deepcopy(self.item))
        with self.assertRaisesRegex(ValueError, 'IDs'):
            self.run_audit()
        self.doc['metadata']['externalCardEvidence'].pop()
        self.item['snapshots'].append(copy.deepcopy(self.binding))
        with self.assertRaisesRegex(ValueError, 'duplicate evidence snapshot'):
            self.run_audit()

    def test_invalid_card_associations_rejected(self):
        for ids in [[], ['missing'], ['c1', 'c1']]:
            self.item['cardIds'] = ids
            with self.assertRaisesRegex(ValueError, 'card IDs'):
                self.run_audit()

    def test_outside_root_rejected(self):
        self.item['snapshots'] = [{'path': '../escape.txt', 'sha256': '0' * 64}]
        with self.assertRaisesRegex(ValueError, 'outside project'):
            self.run_audit()

    def test_metadata_and_url_required(self):
        self.item['url'] = 'file:///private'
        with self.assertRaisesRegex(ValueError, 'HTTP'):
            self.run_audit()
        self.item['url'] = 'https://example.test/doc'
        self.item['scope'] = ''
        with self.assertRaisesRegex(ValueError, 'scope'):
            self.run_audit()

    def test_empty_evidence_is_zero_not_semantic_approval(self):
        self.doc['metadata']['externalCardEvidence'] = []
        result = self.run_audit()
        self.assertEqual(result['evidenceItems'], 0)
        self.assertFalse(result['semanticSupportVerified'])

    def test_review_binding_and_extra_snapshot_metadata(self):
        self.make_review()
        result = tool.audit(self.root, self.path, self.review_path)
        self.assertIsNotNone(result['review'])
        self.assertFalse(result['semanticSupportVerified'])

    def test_stale_review_and_missing_evidence_rejected(self):
        self.make_review()
        self.review['candidate']['sha256'] = '0' * 64
        self.save_review()
        with self.assertRaisesRegex(ValueError, 'candidate binding'):
            tool.audit(self.root, self.path, self.review_path)
        self.make_review()
        self.review['externalEvidence'] = []
        self.save_review()
        with self.assertRaisesRegex(ValueError, 'each evidence'):
            tool.audit(self.root, self.path, self.review_path)

    def test_review_claim_cannot_reassociate_quote_or_card(self):
        for field, value in [('cardIds', ['other']), ('url', 'https://example.test/other')]:
            self.make_review()
            self.review['externalEvidence'][0][field] = value
            self.save_review()
            with self.assertRaisesRegex(ValueError, 'scope mismatch'):
                tool.audit(self.root, self.path, self.review_path)
        self.make_review()
        self.review['externalEvidence'][0]['locator']['quoteSha256'] = '0' * 64
        self.save_review()
        with self.assertRaisesRegex(ValueError, 'quote binding'):
            tool.audit(self.root, self.path, self.review_path)

    def test_review_cannot_claim_human_or_overall_approval(self):
        self.make_review()
        self.review['humanApproval'] = True
        self.save_review()
        with self.assertRaisesRegex(ValueError, 'approval'):
            tool.audit(self.root, self.path, self.review_path)

    def test_generator_mutation_rejected(self):
        with patch.object(tool, 'GENERATOR_SHA256', '0' * 64):
            with self.assertRaisesRegex(ValueError, 'generator source drift'):
                self.run_audit()

    def test_review_needs_explicit_identity_and_role(self):
        self.make_review()
        self.review['reviewer'].pop('name')
        self.save_review()
        with self.assertRaisesRegex(ValueError, 'approval'):
            tool.audit(self.root, self.path, self.review_path)

    def test_malformed_json_rows_fail_cleanly(self):
        self.doc['metadata']['externalCardEvidence'] = ['not an object']
        with self.assertRaisesRegex(ValueError, 'objects'):
            self.run_audit()

    def test_cli_refuses_overwrite_without_altering_existing_file(self):
        output = self.root / 'data/result.json'
        output.write_text('preserve', encoding='utf-8')
        result = tool.main(['--root', str(self.root), '--candidate', str(self.path), '--output', 'data/result.json'])
        self.assertEqual(result, 1)
        self.assertEqual(output.read_text('utf-8'), 'preserve')


if __name__ == '__main__':
    unittest.main()
