"""Synthetic offline snapshots: reject tampering without reading user data."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_disposition_ledger import assemble, sha
from scripts.verify_disposition_ledger import verify
from tests import test_disposition_ledger as ledger_fixtures


class VerifyDispositionLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.args = list(ledger_fixtures.DispositionLedgerTests().fixture())
        self.inputs = {}
        for key, index, path in [('articleManifest', 0, 'data/articles.json'),
                           ('preservedSourceLedger', 1, 'data/knowledge-units.json'),
                           ('coverage.json', 2, 'snapshot/coverage.json'),
                           ('atomic-audit.json', 3, 'snapshot/atomic-audit.json')]:
            self.inputs[key] = self.write(path, self.args[index])
        self.inputs['cards'] = self.write('data/cards/cards.json', {'cards': []})
        cache = '<html>fixture</html>'
        cache_path = self.root / '.cache/html/os.html'
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(cache, encoding='utf-8')
        import hashlib
        self.args[0]['articles'][0]['contentHash'] = 'a' * 64
        self.args[0]['articles'][0]['cache'] = '.cache/html/os.html'
        self.inputs['cache:' + self.args[0]['articles'][0]['url']] = {
            'path': '.cache/html/os.html', 'sha256': hashlib.sha256(cache.encode()).hexdigest()}
        tool_names = ('build_disposition_ledger.py', 'audit_coverage.py', 'build_atomic_candidates.py',
                      'diagnose_empty_sections.py', 'import_curated_articles.py', 'sync_sources.py',
                      'co_pipeline_corrections.py', 'verify_disposition_ledger.py')
        for name in tool_names:
            self.inputs['tool:' + name] = self.write('scripts/' + name, {'fixture': name})
        self.args[4]['inputFiles'] = {
            'coverage': self.inputs['coverage.json'],
            'articleManifest': self.inputs['articleManifest'],
            'dispositionLedgerInputs': {'cards': self.inputs['cards']['sha256'],
                'knowledgeUnits': self.inputs['preservedSourceLedger']['sha256'],
                'articleManifest': self.inputs['articleManifest']['sha256']}}
        self.inputs['empty-evidence.json'] = self.write('snapshot/empty-evidence.json', self.args[4])
        self.args[-1] = self.inputs
        self.ledger = assemble(self.root, *self.args)
        self.ledger_path = self.root / 'snapshot/ledger.json'
        self.save()

    def write(self, path, document):
        raw = (json.dumps(document, ensure_ascii=False, indent=2) + '\n').encode()
        full = self.root / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(raw)
        return {'path': path, 'sha256': sha(raw)}

    def save(self):
        self.write('snapshot/ledger.json', self.ledger)

    def test_valid_snapshot_is_read_only_and_unapproved(self):
        before = {p: p.read_bytes() for p in self.root.rglob('*.json')}
        result = verify(self.root, self.ledger_path)
        self.assertTrue(result['verified'])
        self.assertFalse(result['full408Acceptance'])
        self.assertEqual(result['humanApprovalsGenerated'], 0)
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_item_disposition_tampering_is_rejected(self):
        self.ledger['sourceUnits'][0]['disposition'] = 'accepted'
        self.save()
        with self.assertRaisesRegex(ValueError, 'item-level mismatch: sourceUnits'):
            verify(self.root, self.ledger_path)

    def test_duplicate_or_missing_item_is_rejected(self):
        self.ledger['sections'].append(copy.deepcopy(self.ledger['sections'][0]))
        self.save()
        with self.assertRaisesRegex(ValueError, 'item-level mismatch: sections'):
            verify(self.root, self.ledger_path)
        self.ledger['sections'] = []
        self.save()
        with self.assertRaisesRegex(ValueError, 'item-level mismatch: sections'):
            verify(self.root, self.ledger_path)

    def test_counts_cannot_be_used_instead_of_items(self):
        self.ledger['scope']['sourceUnitCount'] = 99
        self.save()
        with self.assertRaisesRegex(ValueError, 'item-level mismatch: scope'):
            verify(self.root, self.ledger_path)

    def test_input_hash_drift_is_rejected(self):
        path = self.root / self.inputs['coverage.json']['path']
        path.write_bytes(path.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'mismatched input: coverage.json'):
            verify(self.root, self.ledger_path)

    def test_rebound_empty_evidence_cannot_reference_other_coverage(self):
        self.args[4]['inputFiles']['coverage'] = {'path': 'other.json', 'sha256': 'f' * 64}
        self.inputs['empty-evidence.json'] = self.write('snapshot/empty-evidence.json', self.args[4])
        self.save()
        with self.assertRaisesRegex(ValueError, 'not bound to this exact coverage'):
            verify(self.root, self.ledger_path)

    def test_project_escape_and_schema_change_are_rejected(self):
        self.ledger['inputs']['coverage.json']['path'] = '../outside.json'
        self.save()
        with self.assertRaisesRegex(ValueError, 'non-canonical input binding path'):
            verify(self.root, self.ledger_path)
        self.ledger['schemaVersion'] = 999
        self.save()
        with self.assertRaisesRegex(ValueError, 'unsupported ledger schema'):
            verify(self.root, self.ledger_path)

    def test_false_approval_boundary_is_rejected(self):
        self.ledger['full408Acceptance'] = True
        self.save()
        with self.assertRaisesRegex(ValueError, 'incorrect acceptance boundary'):
            verify(self.root, self.ledger_path)

    def test_missing_binding_is_rejected(self):
        del self.ledger['inputs']['cards']
        self.save()
        with self.assertRaisesRegex(ValueError, 'missing or unexpected required input'):
            verify(self.root, self.ledger_path)

    def test_embedded_candidate_audit_cannot_self_attest(self):
        self.ledger['candidateAudits'] = [{'file': 'data/curated/fake.json', 'sha256': 'f' * 64,
            'articleUrl': 'https://example.test/article', 'structuralOk': True, 'errors': [],
            'authorKind': 'human', 'cardCount': 99,
            'unitDispositions': [{'knowledgeUnitId': 'not-a-current-unit', 'action': '__APPROVED__',
                                  'reason': 'forged', 'cardIds': ['missing']}]}]
        self.ledger['inputs']['candidate:data/curated/fake.json'] = self.write(
            'data/curated/fake.json', {'not': 'a proposal'})
        self.save()
        with self.assertRaisesRegex(ValueError, 'candidate proposal hash mismatch'):
            verify(self.root, self.ledger_path)

    def test_forged_approval_text_author_and_unknown_fields_are_rejected(self):
        original = copy.deepcopy(self.ledger)
        for patch in [{'approvalBoundary': 'HUMAN APPROVED'},
                      {'author': {'kind': 'human', 'name': 'forged'}},
                      {'humanApprovals': [{'reviewer': 'forged', 'decision': 'accepted'}]},
                      {'unitDisposition': 'approve-all'}]:
            self.ledger = {**copy.deepcopy(original), **patch}
            self.save()
            with self.assertRaises(ValueError):
                verify(self.root, self.ledger_path)

    def test_candidate_audit_revalidation_rejects_same_hash_invented_claim(self):
        from scripts import import_curated_articles as curated
        rel = 'data/curated/invalid.json'
        proposal = {'schema': curated.SCHEMA, 'version': curated.VERSION,
                    'article': {'url': self.args[0]['articles'][0]['url'], 'sourceId': 'os',
                                'cache': '.cache/html/os.html', 'contentHash': 'a' * 64},
                    'cards': [], 'sourceUnits': []}
        bound = self.write(rel, proposal)
        self.inputs['candidate:' + rel] = bound
        article_map = curated._article_by_url(self.args[0])
        validation = curated._validate_proposal(proposal, root=self.root,
            candidate_path=self.root / rel, articles=article_map,
            ledger_by_id=curated._units_by_id(self.args[1]), formal_card_ids=set())
        self.assertFalse(validation['ok'])
        audit = {'file': rel, 'sha256': bound['sha256'], 'articleUrl': proposal['article']['url'],
                 'structuralOk': False, 'errors': validation['errors'], 'authorKind': 'unknown',
                 'cardCount': 0, 'unitDispositions': []}
        self.args[5] = [audit]
        self.ledger = assemble(self.root, *self.args)
        self.save()
        verified = verify(self.root, self.ledger_path)
        self.assertTrue(verified['verified'])
        self.assertEqual(verified['sha256'], sha(self.ledger_path.read_bytes()))
        self.assertNotEqual(verified['sha256'], bound['sha256'])
        audit['structuralOk'] = True
        audit['errors'] = []
        audit['unitDispositions'] = [{'knowledgeUnitId': self.args[2]['knowledgeUnits'][0]['knowledgeUnitId'],
                                      'action': 'card', 'reason': 'forged', 'cardIds': ['nonexistent']}]
        self.ledger = assemble(self.root, *self.args)
        self.save()
        with self.assertRaisesRegex(ValueError, 'item-level mismatch'):
            verify(self.root, self.ledger_path)

    def test_candidate_audits_must_cover_every_curated_file(self):
        fake = self.root / 'data/curated/fake.json'
        fake.parent.mkdir(parents=True, exist_ok=True)
        fake.write_text('{}', encoding='utf-8')
        self.save()
        with self.assertRaisesRegex(ValueError, 'do not exactly cover curated proposal files'):
            verify(self.root, self.ledger_path)

    def test_each_required_binding_is_mandatory(self):
        original = copy.deepcopy(self.ledger)
        for key in original['inputs']:
            with self.subTest(binding=key):
                self.ledger = copy.deepcopy(original)
                del self.ledger['inputs'][key]
                self.save()
                with self.assertRaises((ValueError, KeyError)):
                    verify(self.root, self.ledger_path)

    def test_human_review_rebinding_against_preserved_ledger_is_rejected(self):
        self.args[2]['knowledgeUnits'][0]['reviewerDecision'] = 'accepted'
        self.args[2]['knowledgeUnits'][0]['reviewer'] = 'forged'
        self.inputs['coverage.json'] = self.write('snapshot/coverage.json', self.args[2])
        self.args[4]['inputFiles']['coverage'] = self.inputs['coverage.json']
        self.inputs['empty-evidence.json'] = self.write('snapshot/empty-evidence.json', self.args[4])
        self.ledger['inputs'].update(self.inputs)
        self.save()
        with self.assertRaisesRegex(ValueError, 'Preserved human review state mismatch'):
            verify(self.root, self.ledger_path)


if __name__ == '__main__':
    unittest.main()
