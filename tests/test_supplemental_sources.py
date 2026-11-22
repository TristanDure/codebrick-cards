from __future__ import annotations
import copy
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import supplemental_sources as sources


class SupplementalSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.snapshot = self.root / 'data/supplements/source.json'
        self.snapshot.parent.mkdir(parents=True)
        self.url = 'https://example.test/embedded'
        self.evidence = {'schema': sources.SNAPSHOT_SCHEMA, 'version': 1,
                         'url': self.url, 'capturedAt': '2026-11-20T09:00:00Z',
                         'captureMethod': 'browser DOM extraction', 'payloadType': 'dom-extract',
                         'payload': {'url': self.url, 'text': 'visible evidence',
                                     'tables': [[['name', 'value'], ['fact', '']]]}}
        self.source = {'id': 'embedded', 'parentSectionIndex': 2, 'url': self.url,
                       'snapshotPath': 'data/supplements/source.json',
                       'snapshotSha256': '', 'anchorUnitIds': ['u1'], 'items': [
                           {'id': 'one', 'locator': 'heading / row', 'text': 'fact',
                            'cardIds': ['c1'], 'evidencePointer': '/payload/text'}]}
        self.doc = {'cards': [{'id': 'c1', 'unitIds': ['u1']}],
                    'metadata': {'supplementalSources': [self.source]}}
        self.units = {'u1': {'tag': 'a', 'href': self.url, 'sectionIndex': 1},
                      'u2': {'tag': 'p', 'text': 'ordinary text', 'sectionIndex': 2}}
        self.write_snapshot()

    def write_snapshot(self):
        self.snapshot.write_text(json.dumps(self.evidence), encoding='utf-8')
        self.source['snapshotSha256'] = hashlib.sha256(self.snapshot.read_bytes()).hexdigest()

    def set_url(self, url):
        self.source['url'] = url
        self.evidence['url'] = url
        self.evidence['payload']['url'] = url
        self.write_snapshot()

    def validate(self):
        return sources.validate(self.doc, self.root, {1, 2}, self.units)

    def rejected(self, contains=None):
        _, errors = self.validate()
        self.assertTrue(errors)
        self.assertTrue(all(e['code'] == 'supplemental_source' for e in errors))
        if contains:
            self.assertTrue(any(contains in e['message'] for e in errors), errors)

    def test_legacy_candidate_has_no_new_requirement(self):
        self.assertEqual(sources.validate({'cards': []}, self.root, {1}, set()), ([], []))

    def test_valid_snapshot_is_bound_without_approving(self):
        result, errors = self.validate()
        self.assertEqual(errors, [])
        self.assertEqual(result, [self.source])
        self.assertNotIn('contentApproved', self.doc)
        # A link may appear in a later chapter than its pedagogical parent.
        self.assertNotEqual(self.units['u1']['sectionIndex'], self.source['parentSectionIndex'])

    def test_plain_paragraph_cannot_impersonate_anchor(self):
        self.units['u1'] = {'tag': 'p', 'href': self.url}
        self.rejected('static link')

    def test_unrelated_link_target_is_rejected(self):
        self.units['u1']['href'] = 'https://example.test/unrelated'
        self.rejected('target does not match')

    def test_anchor_metadata_is_required(self):
        self.units = {'u1', 'u2'}
        self.rejected('with metadata')

    def test_supported_embedded_resources(self):
        for tag in ('iframe', 'embed', 'img'):
            with self.subTest(tag=tag):
                self.units['u1'] = {'tag': tag, 'src': self.url}
                self.assertEqual(self.validate()[1], [])

    def test_explicit_codebrick_aliases_preserve_context(self):
        self.set_url('https://www.codebrick.tech/view?ctx=a%2Cb&embed=1')
        self.units['u1']['href'] = 'https://codebrick.tech:443/view?ctx=a,b'
        self.assertEqual(self.validate()[1], [])
        for bad in ('https://codebrick.tech/view', 'https://codebrick.tech/view?ctx=c',
                    'https://codebrick.tech/view?ctx=a,b&other=1',
                    'https://another.test/view?ctx=a,b',
                    'https://codebrick.tech/view?ctx=a,b#different'):
            with self.subTest(bad=bad):
                self.units['u1']['href'] = bad
                self.rejected('target does not match')

    def test_embed_query_on_other_host_is_not_dropped(self):
        self.units['u1']['href'] = self.url + '?embed=1'
        self.rejected('target does not match')

    def test_source_hash_drift_is_rejected(self):
        self.snapshot.write_text('{}', encoding='utf-8')
        self.rejected('SHA-256')

    def test_snapshot_url_must_match_declared_target(self):
        self.source['url'] = 'https://example.test/another'
        self.rejected('snapshot URL')

    def test_parent_section_must_exist_and_not_be_bool(self):
        for bad in (0, 3, True, '2'):
            with self.subTest(bad=bad):
                self.source['parentSectionIndex'] = bad
                self.rejected()

    def test_static_anchor_must_exist(self):
        self.source['anchorUnitIds'] = ['unknown']
        self.rejected()

    def test_card_must_also_cite_static_anchor(self):
        self.doc['cards'][0]['unitIds'] = ['u2']
        self.rejected()

    def test_unknown_card_reference_is_rejected(self):
        self.source['items'][0]['cardIds'] = ['unknown']
        self.rejected()

    def test_duplicate_source_and_item_ids_are_rejected(self):
        self.doc['metadata']['supplementalSources'].append(copy.deepcopy(self.source))
        self.rejected()
        self.doc['metadata']['supplementalSources'].pop()
        self.source['items'].append(copy.deepcopy(self.source['items'][0]))
        self.rejected()

    def test_path_escape_and_absolute_or_windows_path_are_rejected(self):
        for bad in ('../../secret.json', '/secret.json', 'C:/secret.json', 'data\\source.json'):
            with self.subTest(bad=bad):
                self.source['snapshotPath'] = bad
                self.rejected()

    def test_empty_locator_or_empty_card_refs_are_rejected(self):
        self.source['items'][0]['locator'] = ' '
        self.rejected()
        self.source['items'][0]['locator'] = 'row'
        self.source['items'][0]['cardIds'] = []
        self.rejected()

    def test_missing_snapshot_and_non_json_are_rejected(self):
        self.snapshot.unlink()
        self.rejected()
        self.snapshot.write_text('not json', encoding='utf-8')
        self.source['snapshotSha256'] = hashlib.sha256(self.snapshot.read_bytes()).hexdigest()
        self.rejected()

    def test_unsafe_url_and_extra_fields_are_rejected(self):
        for bad in ('javascript:alert(1)', 'https://user:password@example.test/a',
                    'https://example.test:bad/a', 'https://[bad/a', 5):
            with self.subTest(bad=bad):
                self.source['url'] = bad
                self.rejected()
        self.source['url'] = self.url
        self.source['approved'] = True
        self.rejected()

    def test_invalid_container_types_are_rejected(self):
        for bad in (None, {}, 'sources'):
            with self.subTest(bad=bad):
                self.doc['metadata']['supplementalSources'] = bad
                self.rejected()

    def test_url_only_snapshot_is_rejected(self):
        self.evidence = {'url': self.url}
        self.write_snapshot()
        self.rejected('envelope')

    def test_invalid_envelope_and_capture_metadata_are_rejected(self):
        valid = copy.deepcopy(self.evidence)
        cases = [('schema', 'unknown'), ('version', True), ('version', 2),
                 ('capturedAt', None), ('capturedAt', '2026-13-99'),
                 ('capturedAt', '2026-11-20T09:00:00'), ('captureMethod', ' '),
                 ('payloadType', 'invented')]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                self.evidence = copy.deepcopy(valid)
                self.evidence[key] = value
                self.write_snapshot()
                self.rejected()
        for key in ('capturedAt', 'captureMethod', 'payload'):
            with self.subTest(missing=key):
                self.evidence = copy.deepcopy(valid)
                del self.evidence[key]
                self.write_snapshot()
                self.rejected()

    def test_invalid_dom_payload_is_rejected(self):
        valid = copy.deepcopy(self.evidence['payload'])
        for bad in (None, {'url': self.url}, {'url': self.url, 'text': ' '},
                    {'url': 'https://other.test', 'text': 'text'},
                    {**valid, 'tables': [[['cell', 3]]]}, {**valid, 'tables': 'table'}):
            with self.subTest(bad=bad):
                self.evidence['payload'] = bad
                self.write_snapshot()
                self.rejected()

    def test_table_row_can_contain_blank_cells(self):
        self.source['items'][0]['evidencePointer'] = '/payload/tables/0/1'
        self.assertEqual(self.validate()[1], [])

    def test_pointer_must_resolve_to_real_nonempty_evidence(self):
        for bad in ('/url', '/payload/url', '/payload/tables/9', '/payload/tables/0/01',
                    '/payload/tables/0/1/1', '/payload/tables/0/~2', '/payload/text/nope', None):
            with self.subTest(bad=bad):
                self.source['items'][0]['evidencePointer'] = bad
                self.rejected()
        del self.source['items'][0]['evidencePointer']
        self.rejected()

    def test_question_snapshot_requires_captured_stem(self):
        self.evidence['payloadType'] = 'site-question'
        self.evidence['payload'] = {'url': self.url, 'evidence': {
            'url': self.url, 'stem': 'Captured question stem', 'options': ['A. first', 'B. second']}}
        self.source['items'][0]['evidencePointer'] = '/payload/evidence/stem'
        self.write_snapshot()
        self.assertEqual(self.validate()[1], [])
        self.source['items'][0]['evidencePointer'] = '/payload/evidence/options/1'
        self.assertEqual(self.validate()[1], [])
        self.evidence['payload']['evidence']['stem'] = ' '
        self.write_snapshot()
        self.rejected('captured stem')

    def test_structured_question_options_allow_text_only(self):
        self.evidence['payloadType'] = 'site-question'
        self.evidence['payload'] = {'url': self.url, 'evidence': {
            'url': self.url, 'stem': 'Captured question stem',
            'options': [{'key': 'A', 'text': 'Captured option', 'url': self.url}]}}
        self.source['items'][0]['evidencePointer'] = '/payload/evidence/options/0/text'
        self.write_snapshot()
        self.assertEqual(self.validate()[1], [])
        self.source['items'][0]['evidencePointer'] = '/payload/evidence/options/0/url'
        self.rejected('not metadata')
        self.evidence['payload']['evidence']['options'] = [{'url': self.url}]
        self.write_snapshot()
        self.rejected('option text')

    def test_snapshot_read_is_bounded_before_hash_or_parse(self):
        class ReadSpy(io.BytesIO):
            def read(inner, size=-1):
                self.assertEqual(size, 33)
                return super().read(size)
        with patch.object(sources, 'MAX_SNAPSHOT_BYTES', 32), patch.object(
                Path, 'open', return_value=ReadSpy(b'x' * 100)):
            self.rejected('size limit')


if __name__ == '__main__':
    unittest.main()
