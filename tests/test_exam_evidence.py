import copy
import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from scripts.audit_exam_evidence import audit, requirement_sha, question_evidence_sha
from tests import test_import_curated_articles as fixtures
from scripts import audit_exam_evidence as evidence_tool


class ExamEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.CuratedArticleAuditTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.root = self.fixture.root.resolve()
        self.card_id = self.fixture.proposal['cards'][0]['cardId']
        raw = b'Fixture contents: requirements and historical questions are not shown.'
        path = self.root / '.cache/evidence/catalog.txt'
        path.parent.mkdir(parents=True)
        path.write_bytes(raw)
        self.binding = {'path': '.cache/evidence/catalog.txt',
                        'sha256': hashlib.sha256(raw).hexdigest()}
        self.source = {'id': 'catalog', 'kind': 'annual-syllabus', 'documentYear': 2027,
                       'publisher': 'Synthetic official publisher fixture',
                       'url': 'https://example.test/catalog', 'authority': 'official-publisher',
                       'evidenceLevel': 'catalog-only', 'snapshots': [self.binding],
                       'proves': ['Publication metadata only'],
                       'doesNotProve': ['No requirement text or question bodies']}
        self.doc = {'schema': 'codebrick-exam-evidence-chain', 'version': 1,
                    'targetYear': 2027, 'sources': [self.source], 'officialRequirements': None,
                    'officialRequirementInventoryComplete': False, 'requirementMappings': [],
                    'pastPaperQuestions': [], 'pastPaperInventoryComplete': False}
        self.path = Path('data/exam/fixture-evidence.json')
        self.save()

    def save(self):
        full = self.root / self.path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(json.dumps(self.doc, indent=2), encoding='utf-8')

    def requirement(self):
        return {'id': 'os.1', 'sourceId': 'catalog', 'subjectId': 'os', 'year': 2027,
                'locator': {**self.binding, 'quote': 'requirements', 'location': 'fixture paragraph 1'}}

    def test_unknown_count_and_coverage_stay_null_not_zero_or_complete(self):
        result = audit(self.root, self.path)
        self.assertIsNone(result['officialRequirementCount'])
        self.assertIsNone(result['officialMappingCoverage'])
        self.assertIsNone(result['mappedRequirementCount'])
        self.assertFalse(result['targetAnnualEvidenceAccounted'])
        self.assertFalse(result['full408Acceptance'])

    def test_catalog_cannot_be_promoted_to_official_requirements(self):
        self.doc['officialRequirements'] = [self.requirement()]
        self.save()
        with self.assertRaisesRegex(ValueError, 'cannot use catalog/old/secondary'):
            audit(self.root, self.path)

    def test_missing_scope_cannot_be_marked_complete(self):
        self.doc['officialRequirementInventoryComplete'] = True
        self.save()
        with self.assertRaisesRegex(ValueError, 'without official text'):
            audit(self.root, self.path)
        self.doc['officialRequirements'] = []
        self.save()
        with self.assertRaisesRegex(ValueError, 'never an empty complete scope'):
            audit(self.root, self.path)

    def test_old_year_and_secondary_sources_fail_target_year_gate(self):
        self.doc['officialRequirements'] = [self.requirement()]
        self.source['evidenceLevel'] = 'full-text'
        self.source['documentYear'] = 2022
        self.save()
        with self.assertRaisesRegex(ValueError, 'catalog/old/secondary'):
            audit(self.root, self.path)
        self.source['documentYear'] = 2027
        self.source['authority'] = 'secondary'
        self.save()
        with self.assertRaisesRegex(ValueError, 'catalog/old/secondary'):
            audit(self.root, self.path)

    def test_quote_requires_exact_snapshot_and_verbatim_text(self):
        self.source['evidenceLevel'] = 'full-text'
        self.doc['officialRequirements'] = [self.requirement()]
        self.doc['officialRequirements'][0]['locator']['quote'] = 'Invented official clause'
        self.save()
        with self.assertRaisesRegex(ValueError, 'not present in captured'):
            audit(self.root, self.path)

    def test_source_snapshot_tampering_is_rejected(self):
        (self.root / self.binding['path']).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'stale source snapshot'):
            audit(self.root, self.path)

    def test_paper_catalog_and_secondary_labels_do_not_become_official_questions(self):
        self.source['kind'] = 'paper-collection-catalog'
        question = {'id': 'os-2021-23', 'sourceId': 'catalog', 'examYear': 2021,
                    'subjectId': 'os', 'identityStatus': 'catalog-only'}
        self.doc['pastPaperQuestions'] = [question]
        self.save()
        result = audit(self.root, self.path)
        self.assertEqual(result['officialQuestionEvidenceCount'], 0)
        question['identityStatus'] = 'official-full-text-verified'
        self.save()
        with self.assertRaisesRegex(ValueError, 'cannot use catalog or secondary'):
            audit(self.root, self.path)

    def test_source_path_escape_is_rejected(self):
        self.binding['path'] = '../outside.txt'
        self.save()
        with self.assertRaisesRegex(ValueError, 'outside project'):
            audit(self.root, self.path)

    def test_empty_paper_inventory_cannot_be_marked_complete(self):
        self.doc['pastPaperInventoryComplete'] = True
        self.save()
        with self.assertRaisesRegex(ValueError, 'actual official question/answer evidence'):
            audit(self.root, self.path)

    def test_proposed_mapping_is_not_independently_accepted(self):
        self.source['evidenceLevel'] = 'full-text'
        self.doc['officialRequirements'] = [self.requirement()]
        self.doc['officialRequirementInventoryComplete'] = True
        candidate_path = self.root / 'data/curated/fixture.json'
        self.assertTrue(candidate_path.exists())
        mapping = {'requirementId': 'os.1', 'candidatePath': 'data/curated/fixture.json',
                   'candidateSha256': hashlib.sha256(candidate_path.read_bytes()).hexdigest(),
                   'cardIds': [self.card_id], 'status': 'proposed-ai-mapping'}
        self.doc['requirementMappings'] = [mapping]
        self.save()
        result = audit(self.root, self.path)
        self.assertEqual(result['candidateMappingCoverage'], 1.0)
        self.assertEqual(result['officialMappingCoverage'], 0.0)
        self.assertEqual(result['independentlyReviewedMappingCount'], 0)
        self.assertFalse(result['targetAnnualEvidenceAccounted'])
        mapping['status'] = 'independently-reviewed-ai-mapping'
        self.save()
        with self.assertRaisesRegex(ValueError, 'pinned independent review'):
            audit(self.root, self.path)

    def test_independent_mapping_review_must_bind_real_candidate_and_identity(self):
        self.source['evidenceLevel'] = 'full-text'
        self.doc['officialRequirements'] = [self.requirement()]
        self.doc['officialRequirementInventoryComplete'] = True
        path = self.root / 'data/curated/fixture.json'
        self.assertTrue(path.exists())
        mapping = {'requirementId': 'os.1', 'candidatePath': 'data/curated/fixture.json',
                   'candidateSha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                   'cardIds': [self.card_id], 'status': 'independently-reviewed-ai-mapping'}
        review = {'schema': 'codebrick-exam-mapping-review', 'version': 1, 'requirementId': 'os.1',
                  'candidatePath': mapping['candidatePath'], 'candidateSha256': mapping['candidateSha256'],
                  'requirementSha256': requirement_sha(self.doc['officialRequirements'][0], self.source),
                  'cardIds': mapping['cardIds'], 'decision': 'PASS', 'humanApproval': False,
                  'reviewer': {'kind': 'ai', 'independentOfAuthor': True,
                               'name': 'synthetic-independent-reviewer',
                               'role': 'independent-non-author-reviewer'},
                  'reason': 'Synthetic independent mapping fixture, not official real content.'}
        review_path = self.root / 'data/_reviews/mapping.json'
        review_path.parent.mkdir(parents=True)
        review_path.write_text(json.dumps(review), encoding='utf-8')
        mapping['independentReview'] = {'path': 'data/_reviews/mapping.json',
            'sha256': hashlib.sha256(review_path.read_bytes()).hexdigest()}
        self.doc['requirementMappings'] = [mapping]
        self.save()
        result = audit(self.root, self.path)
        self.assertTrue(result['targetAnnualEvidenceAccounted'])
        self.assertFalse(result['full408Acceptance'])
        original_quote = self.doc['officialRequirements'][0]['locator']['quote']
        self.doc['officialRequirements'][0]['locator']['quote'] = 'historical questions'
        self.save()
        with self.assertRaisesRegex(ValueError, 'inconsistent or unproven'):
            audit(self.root, self.path)
        self.doc['officialRequirements'][0]['locator']['quote'] = original_quote
        review['humanApproval'] = True
        review_path.write_text(json.dumps(review), encoding='utf-8')
        mapping['independentReview']['sha256'] = hashlib.sha256(review_path.read_bytes()).hexdigest()
        self.save()
        with self.assertRaisesRegex(ValueError, 'inconsistent or unproven'):
            audit(self.root, self.path)

    def official_question_fixture(self):
        paper_text = '2021 OS synthetic paper\nQ1: Calculate 1+1.\nQ2: Calculate 2+2.\n'
        answer_text = '2021 OS synthetic answers\nQ1: 2\nQ2: 4\n'
        def snapshot(name, text):
            path = self.root / ('.cache/evidence/' + name)
            path.write_text(text, encoding='utf-8')
            return {'path': path.relative_to(self.root).as_posix(),
                    'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        paper_binding = snapshot('paper.txt', paper_text)
        answer_binding = snapshot('answers.txt', answer_text)
        self.source.update(kind='past-paper', documentYear=2021, evidenceLevel='full-text',
                           snapshots=[paper_binding])
        answer = copy.deepcopy(self.source)
        answer.update(id='answer', kind='answer-key', snapshots=[answer_binding])
        self.doc['sources'].append(answer)
        identity = {'examYear': 2021, 'subjectId': 'os', 'questionNumber': 1}
        def item(binding, text):
            return {'identity': copy.deepcopy(identity), 'completeness': 'full-item',
                    'itemText': text, 'labelText': 'Q1',
                    'textLocator': {**binding, 'quote': text, 'location': 'synthetic Q1 paragraph'}}
        stem = item(paper_binding, 'Q1: Calculate 1+1.')
        answer_item = item(answer_binding, 'Q1: 2')
        question = {'id': 'os-2021-fixture', 'sourceId': 'catalog', 'examYear': 2021,
                    'subjectId': 'os', 'identityStatus': 'official-full-text-verified',
                    'questionNumber': 1, 'questionType': 'constructed-response', 'options': [],
                    'stemEvidence': stem, 'answerSourceId': 'answer', 'answerEvidence': answer_item}
        pair = {'schema': 'codebrick-past-paper-pair-review', 'version': 1,
                'identity': identity, 'stemEvidenceSha256': question_evidence_sha(stem, self.source),
                'answerEvidenceSha256': question_evidence_sha(answer_item, answer),
                'questionType': 'constructed-response', 'options': [], 'decision': 'PASS',
                'humanApproval': False, 'reviewer': {'kind': 'ai', 'name': 'synthetic-pair-reviewer',
                    'role': 'independent-evidence-reviewer', 'independentOfAuthor': True},
                'checks': {'identityPairing': 'PASS', 'stemCompleteness': 'PASS',
                           'answerCompleteness': 'PASS'},
                'reason': 'Synthetic exact Q1 pairing and complete declared item body only.'}
        path = self.root / 'data/_reviews/pair.json'
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(pair), encoding='utf-8')
        question['independentPairReview'] = {'path': path.relative_to(self.root).as_posix(),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        self.doc['pastPaperQuestions'] = [question]
        self.doc['pastPaperInventoryComplete'] = True
        return question, answer

    def test_official_question_needs_same_year_full_text_answer_and_quote(self):
        question, answer = self.official_question_fixture()
        self.save()
        result = audit(self.root, self.path)
        self.assertEqual(result['officialQuestionEvidenceCount'], 1)
        self.assertFalse(result['full408Acceptance'])
        for change in [{'documentYear': 2020}, {'evidenceLevel': 'catalog-only'},
                       {'authority': 'secondary'}]:
            original = copy.deepcopy(answer)
            answer.update(change)
            self.save()
            with self.assertRaisesRegex(ValueError, 'answer evidence missing or secondary'):
                audit(self.root, self.path)
            answer.clear()
            answer.update(original)
        question['answerEvidence']['itemText'] = 'Q1: fabricated answer'
        question['answerEvidence']['textLocator']['quote'] = 'Q1: fabricated answer'
        self.save()
        with self.assertRaisesRegex(ValueError, 'not present in captured'):
            audit(self.root, self.path)

    def test_same_year_wrong_question_pair_and_marker_only_are_rejected(self):
        question, answer = self.official_question_fixture()
        original = copy.deepcopy(question['answerEvidence'])
        question['answerEvidence']['identity']['questionNumber'] = 2
        question['answerEvidence']['itemText'] = 'Q2: 4'
        question['answerEvidence']['labelText'] = 'Q2'
        question['answerEvidence']['textLocator']['quote'] = 'Q2: 4'
        self.save()
        with self.assertRaisesRegex(ValueError, 'same question identity'):
            audit(self.root, self.path)
        question['answerEvidence'] = copy.deepcopy(original)
        question['answerEvidence']['itemText'] = 'Q1'
        question['answerEvidence']['textLocator']['quote'] = 'Q1'
        self.save()
        with self.assertRaisesRegex(ValueError, 'actual body'):
            audit(self.root, self.path)
        question['answerEvidence'] = copy.deepcopy(original)
        question.pop('independentPairReview')
        self.save()
        with self.assertRaisesRegex(ValueError, 'pinned independent pair review'):
            audit(self.root, self.path)

    def test_pair_review_cannot_be_reused_for_changed_full_item(self):
        question, answer = self.official_question_fixture()
        question['stemEvidence']['labelText'] = 'Q1:'
        self.save()
        with self.assertRaisesRegex(ValueError, 'pair review is stale'):
            audit(self.root, self.path)

    def test_only_ids_and_wrong_schema_are_not_actual_mapping_candidates(self):
        self.source['evidenceLevel'] = 'full-text'
        self.doc['officialRequirements'] = [self.requirement()]
        self.doc['officialRequirementInventoryComplete'] = True
        path = self.root / 'data/curated/fixture.json'
        path.write_text(json.dumps({'schema': 'not-a-candidate', 'cards': [{'id': 'fake'}]}),
                        encoding='utf-8')
        self.doc['requirementMappings'] = [{'requirementId': 'os.1',
            'candidatePath': 'data/curated/fixture.json',
            'candidateSha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'cardIds': ['fake'], 'status': 'proposed-ai-mapping'}]
        self.save()
        with self.assertRaises(ValueError):
            audit(self.root, self.path)

    def test_years_claim_boundaries_and_inventory_types_are_not_truthy_flags(self):
        original = copy.deepcopy(self.doc)
        for key, value in [('documentYear', True), ('documentYear', '2027'),
                           ('proves', 'metadata'), ('doesNotProve', [123])]:
            self.doc = copy.deepcopy(original)
            self.doc['sources'][0][key] = value
            self.save()
            with self.assertRaises(ValueError):
                audit(self.root, self.path)
        self.doc = copy.deepcopy(original)
        self.doc['pastPaperInventoryComplete'] = 'false'
        self.save()
        with self.assertRaisesRegex(ValueError, 'explicit boolean'):
            audit(self.root, self.path)

    def test_requirement_digest_binds_clause_and_source_not_dictionary_order(self):
        req = self.requirement()
        original = requirement_sha(req, self.source)
        self.assertEqual(original, requirement_sha(dict(reversed(list(req.items()))), self.source))
        req['locator']['quote'] = 'historical questions'
        self.assertNotEqual(original, requirement_sha(req, self.source))
        req = self.requirement()
        source = copy.deepcopy(self.source)
        source['publisher'] = 'another publisher'
        self.assertNotEqual(original, requirement_sha(req, source))

    def test_shared_candidate_cache_cannot_replace_prior_binding(self):
        self.source['evidenceLevel'] = 'full-text'
        first = self.requirement()
        second = copy.deepcopy(first)
        second['id'] = 'os.2'
        self.doc['officialRequirements'] = [first, second]
        path = self.root / 'data/curated/fixture.json'
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self.doc['requirementMappings'] = [{'requirementId': req['id'],
            'candidatePath': 'data/curated/fixture.json', 'candidateSha256': digest,
            'cardIds': [self.card_id], 'status': 'proposed-ai-mapping'} for req in [first, second]]
        self.save()
        cache = self.root / self.fixture.cache_relative
        new_raw = cache.read_bytes() + b'<!-- new capture -->'
        real = evidence_tool.curated._validate_proposal
        calls = 0
        def timing(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                cache.write_bytes(new_raw)
            result = real(*args, **kwargs)
            self.assertTrue(result['ok'])
            return result
        with patch.object(evidence_tool.curated, '_validate_proposal', side_effect=timing):
            with self.assertRaisesRegex(ValueError, 'conflicting input snapshots'):
                audit(self.root, self.path)

    def test_q1_label_prefix_cannot_bind_q10_answer_even_with_fresh_pair_hash(self):
        question, answer = self.official_question_fixture()
        path = self.root / answer['snapshots'][0]['path']
        path.write_bytes(path.read_bytes() + b'\nQ10: 999')
        binding = {'path': path.relative_to(self.root).as_posix(),
                   'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        answer['snapshots'] = [binding]
        item = question['answerEvidence']
        item.update(itemText='Q10: 999', labelText='Q1')
        item['textLocator'] = {**binding, 'quote': 'Q10: 999', 'location': 'Q10'}
        pair_path = self.root / question['independentPairReview']['path']
        pair = json.loads(pair_path.read_bytes())
        pair['answerEvidenceSha256'] = question_evidence_sha(item, answer)
        pair_path.write_text(json.dumps(pair), encoding='utf-8')
        question['independentPairReview']['sha256'] = hashlib.sha256(pair_path.read_bytes()).hexdigest()
        self.save()
        with self.assertRaisesRegex(ValueError, 'label boundary'):
            audit(self.root, self.path)

    def test_same_canonical_question_is_not_counted_twice_under_an_alias_id(self):
        question, answer = self.official_question_fixture()
        alias = copy.deepcopy(question)
        alias['id'] = 'alias-for-the-same-Q1'
        self.doc['pastPaperQuestions'].append(alias)
        self.save()
        with self.assertRaisesRegex(ValueError, 'duplicate canonical question identity'):
            audit(self.root, self.path)

    def test_pair_reviewer_name_must_be_a_nonblank_string(self):
        question, answer = self.official_question_fixture()
        pair_path = self.root / question['independentPairReview']['path']
        pair = json.loads(pair_path.read_bytes())
        for name in [' ', ['reviewer']]:
            pair['reviewer']['name'] = name
            pair_path.write_text(json.dumps(pair), encoding='utf-8')
            question['independentPairReview']['sha256'] = hashlib.sha256(pair_path.read_bytes()).hexdigest()
            self.save()
            with self.assertRaisesRegex(ValueError, 'pair review is stale, inconsistent'):
                audit(self.root, self.path)

    def test_generator_hash_does_not_late_bind_changed_source(self):
        expected = evidence_tool.GENERATOR_SHA256
        original = Path.read_bytes
        def changed_source(path):
            if path.resolve() == Path(evidence_tool.__file__).resolve():
                return b'changed generator source'
            return original(path)
        with patch.object(Path, 'read_bytes', changed_source):
            with self.assertRaisesRegex(ValueError, 'generator source drift'):
                audit(self.root, self.path)
        self.assertEqual(evidence_tool.GENERATOR_SHA256, expected)
        self.assertEqual(audit(self.root, self.path)['generator']['sha256'], expected)


    def secondary_execution_fixture(self):
        """Synthetic attachment only: no copied private card or compiler run."""
        def blob(name, raw):
            path = self.root / ('.cache/evidence/execution-' + name)
            path.write_bytes(raw)
            return {'path': path.relative_to(self.root).as_posix(),
                    'sha256': hashlib.sha256(raw).hexdigest()}
        def document(name, value):
            return blob(name, json.dumps(value).encode())
        candidate = document('candidate.json', {'schema': 'codebrick-curated-article',
                             'version': 1, 'cards': []})
        runner = blob('runner.py', b'# Synthetic runner; not executed.\n')
        harness = blob('harness.c', b'/* Synthetic harness; not compiled. */\n')
        stdout = blob('stdout.txt', b'synthetic-output\n')
        basis = document('basis.json', {'schema': 'codebrick-secondary-item-transcription',
                         'version': 1, 'provenanceStatus': 'secondary-unverified',
                         'officialAuthorityVerified': False,
                         'transcription': 'Synthetic secondary question basis.'})
        execution = {'schema': 'codebrick-local-candidate-execution', 'version': 1,
                     'candidate': candidate, 'runner': runner, 'totalCases': 2,
                     'results': [{'cases': 2, 'harness': harness['path'],
                                  'harnessSha256': harness['sha256'],
                                  'stdout': stdout['path'], 'stdoutSha256': stdout['sha256']}],
                     'humanApproval': False, 'fullArticleApproved': False,
                     'overall408Acceptance': False}
        execution_binding = document('report.json', execution)
        review = {'schema': 'codebrick-q42-code-execution-independent-review', 'version': 2,
                  'candidate': copy.deepcopy(candidate), 'execution': copy.deepcopy(execution_binding),
                  'reviewer': {'kind': 'ai', 'name': 'synthetic-nonauthor',
                               'independentOfExecutionEvidenceAuthor': True,
                               'humanApproval': False},
                  'decision': 'PASS_WITH_LIMITATION_FINAL_STATE_ONLY',
                  'questionBasis': {**basis, 'status': 'secondary-unverified',
                                    'officialQuestionEvidenceCountAdded': 0,
                                    'officialAnswerEvidenceCountAdded': 0},
                  'inputs': [candidate, execution_binding, runner, harness, stdout, basis]}
        review_binding = document('review.json', review)
        self.doc['secondaryCandidateExecution'] = {
            'candidate': candidate, 'execution': execution_binding,
            'independentReview': review_binding, 'scope': 'Synthetic local byte check only',
            'officialQuestionEvidenceAdded': 0, 'officialAnswerEvidenceAdded': 0,
            'notOfficialAnswer': True, 'notWholeCardReview': True}
        self.save()
        return execution, review

    def save_secondary_reports(self, execution, review):
        attachment = self.doc['secondaryCandidateExecution']
        old = copy.deepcopy(attachment['execution'])
        path = self.root / old['path']
        path.write_text(json.dumps(execution), encoding='utf-8')
        attachment['execution']['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        review['inputs'] = [copy.deepcopy(attachment['execution']) if b == old else b
                            for b in review['inputs']]
        if review.get('execution') == old:
            review['execution'] = copy.deepcopy(attachment['execution'])
        path = self.root / attachment['independentReview']['path']
        path.write_text(json.dumps(review), encoding='utf-8')
        attachment['independentReview']['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.save()

    def test_secondary_attachment_optional_absent_and_present_is_not_approval(self):
        self.assertIsNone(audit(self.root, self.path)['secondaryCandidateExecution'])
        self.secondary_execution_fixture()
        result = audit(self.root, self.path)
        claim = result['secondaryCandidateExecution']
        self.assertTrue(claim['attachmentBindingsVerified'])
        self.assertEqual(claim['declaredCases'], 2)
        self.assertFalse(claim['executionRerun'])
        self.assertFalse(claim['semanticCorrectnessVerified'])
        self.assertFalse(claim['reviewerIdentityAuthenticated'])
        self.assertEqual(result['officialQuestionEvidenceCount'], 0)
        self.assertIsNone(result['officialMappingCoverage'])
        self.assertFalse(result['full408Acceptance'])
        self.assertTrue(any('secondaryExecution:' in k for k in result['inputs']))

    def test_secondary_attachment_report_and_candidate_tampering_rejected(self):
        for field in ('candidate', 'execution', 'independentReview'):
            with self.subTest(field=field):
                self.secondary_execution_fixture()
                target = self.root / self.doc['secondaryCandidateExecution'][field]['path']
                target.write_bytes(target.read_bytes() + b' ')
                with self.assertRaisesRegex(ValueError, 'stale secondary execution'):
                    audit(self.root, self.path)

    def test_secondary_attachment_artifact_tampering_rejected(self):
        for field in ('runner', 'harness', 'stdout', 'questionBasis'):
            with self.subTest(field=field):
                execution, review = self.secondary_execution_fixture()
                path = (execution['runner']['path'] if field == 'runner' else
                        review['questionBasis']['path'] if field == 'questionBasis' else
                        execution['results'][0][field])
                (self.root / path).write_bytes(b'tampered')
                with self.assertRaisesRegex(ValueError, 'stale secondary execution'):
                    audit(self.root, self.path)

    def test_secondary_attachment_nonofficial_fields_are_strict(self):
        for field, value in [('officialQuestionEvidenceAdded', 1),
                             ('officialAnswerEvidenceAdded', False),
                             ('notOfficialAnswer', 1), ('notWholeCardReview', False),
                             ('scope', ' ')]:
            with self.subTest(field=field, value=value):
                self.secondary_execution_fixture()
                self.doc['secondaryCandidateExecution'][field] = value
                self.save()
                with self.assertRaisesRegex(ValueError, 'non-official boundaries'):
                    audit(self.root, self.path)

    def test_secondary_attachment_unknown_null_or_incomplete_rejected(self):
        for value in (None, {}, [], {'unknown': True}):
            self.doc['secondaryCandidateExecution'] = value
            self.save()
            with self.assertRaisesRegex(ValueError, 'fields are incomplete or unknown'):
                audit(self.root, self.path)

    def test_secondary_attachment_report_must_bind_same_candidate(self):
        execution, review = self.secondary_execution_fixture()
        execution['candidate'] = copy.deepcopy(execution['runner'])
        self.save_secondary_reports(execution, review)
        with self.assertRaisesRegex(ValueError, 'schemas or candidate linkage'):
            audit(self.root, self.path)

    def test_secondary_attachment_review_must_bind_same_execution(self):
        execution, review = self.secondary_execution_fixture()
        review['inputs'] = [b for b in review['inputs'] if b != self.doc['secondaryCandidateExecution']['execution']]
        self.save_secondary_reports(execution, review)
        with self.assertRaisesRegex(ValueError, 'must bind the same candidate and execution'):
            audit(self.root, self.path)

    def test_secondary_attachment_cannot_grant_approval(self):
        for field in ('humanApproval', 'fullArticleApproved', 'overall408Acceptance'):
            execution, review = self.secondary_execution_fixture()
            execution[field] = True
            self.save_secondary_reports(execution, review)
            with self.assertRaisesRegex(ValueError, 'cannot grant approval'):
                audit(self.root, self.path)

    def test_secondary_attachment_reviewer_independence_is_explicit_declaration(self):
        for field, value in [('name', ' '), ('kind', 'human'),
                             ('independentOfExecutionEvidenceAuthor', 'true'),
                             ('humanApproval', True)]:
            execution, review = self.secondary_execution_fixture()
            review['reviewer'][field] = value
            self.save_secondary_reports(execution, review)
            with self.assertRaisesRegex(ValueError, 'reviewer declaration|cannot grant approval'):
                audit(self.root, self.path)

    def test_secondary_attachment_case_totals_must_be_integer_consistent(self):
        for cases, total in [(True, 1), (0, 0), (2, 3), (2, True)]:
            execution, review = self.secondary_execution_fixture()
            execution['results'][0]['cases'] = cases
            execution['totalCases'] = total
            self.save_secondary_reports(execution, review)
            with self.assertRaisesRegex(ValueError, 'case count'):
                audit(self.root, self.path)

    def test_secondary_attachment_basis_cannot_be_promoted_to_official(self):
        execution, review = self.secondary_execution_fixture()
        review['questionBasis']['status'] = 'official-full-text-verified'
        self.save_secondary_reports(execution, review)
        with self.assertRaisesRegex(ValueError, 'must remain secondary'):
            audit(self.root, self.path)

    def test_secondary_attachment_postread_artifact_drift_rejected(self):
        execution, review = self.secondary_execution_fixture()
        original = evidence_tool.audit_secondary_execution
        def changed_after_audit(root, attachment, pin):
            result = original(root, attachment, pin)
            (root / execution['results'][0]['stdout']).write_bytes(b'late drift')
            return result
        with patch.object(evidence_tool, 'audit_secondary_execution', side_effect=changed_after_audit):
            with self.assertRaisesRegex(ValueError, 'snapshot drift during exam evidence'):
                audit(self.root, self.path)

    def test_secondary_attachment_rejects_unknown_fields_and_outside_paths(self):
        self.secondary_execution_fixture()
        self.doc['secondaryCandidateExecution']['claimOfficial'] = True
        self.save()
        with self.assertRaisesRegex(ValueError, 'fields are incomplete or unknown'):
            audit(self.root, self.path)
        execution, review = self.secondary_execution_fixture()
        review['inputs'].append({'path': '../outside-private.txt', 'sha256': '0' * 64})
        self.save_secondary_reports(execution, review)
        with self.assertRaisesRegex(ValueError, 'path outside project'):
            audit(self.root, self.path)


    def test_secondary_review_targets_must_match_even_if_input_list_is_correct(self):
        for field in ('candidate', 'execution'):
            execution, review = self.secondary_execution_fixture()
            review[field] = copy.deepcopy(execution['runner'])
            self.save_secondary_reports(execution, review)
            with self.assertRaisesRegex(ValueError, 'declares a different target'):
                audit(self.root, self.path)
            execution, review = self.secondary_execution_fixture()
            review.pop(field)
            self.save_secondary_reports(execution, review)
            with self.assertRaisesRegex(ValueError, 'declares a different target'):
                audit(self.root, self.path)

    def test_secondary_review_v1_without_explicit_targets_is_not_implicitly_accepted(self):
        execution, review = self.secondary_execution_fixture()
        review['version'] = 1
        review.pop('candidate')
        review.pop('execution')
        self.save_secondary_reports(execution, review)
        with self.assertRaisesRegex(ValueError, 'schemas or candidate linkage'):
            audit(self.root, self.path)

    def test_secondary_question_basis_cannot_reuse_executable_or_report_artifact(self):
        for field in ('runner', 'execution', 'candidate'):
            execution, review = self.secondary_execution_fixture()
            binding = execution['runner'] if field == 'runner' else self.doc['secondaryCandidateExecution'][field]
            review['questionBasis'].update(copy.deepcopy(binding))
            self.save_secondary_reports(execution, review)
            with self.assertRaisesRegex(ValueError, 'distinct transcription'):
                audit(self.root, self.path)

    def test_secondary_question_basis_needs_review_input_and_transcription_schema(self):
        execution, review = self.secondary_execution_fixture()
        old = {k: review['questionBasis'][k] for k in ('path', 'sha256')}
        review['inputs'] = [b for b in review['inputs'] if b != old]
        self.save_secondary_reports(execution, review)
        with self.assertRaisesRegex(ValueError, 'must be bound by review inputs'):
            audit(self.root, self.path)
        execution, review = self.secondary_execution_fixture()
        old = {k: review['questionBasis'][k] for k in ('path', 'sha256')}
        path = self.root / old['path']
        path.write_text(json.dumps({'schema': 'not-a-question', 'transcription': 'unrelated'}), encoding='utf-8')
        updated = {**old, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        review['questionBasis'].update(updated)
        review['inputs'] = [updated if b == old else b for b in review['inputs']]
        self.save_secondary_reports(execution, review)
        with self.assertRaisesRegex(ValueError, 'needs a secondary transcription document'):
            audit(self.root, self.path)

    def test_secondary_reports_reject_conflicting_and_unknown_claims(self):
        for target, field, value in [('review', 'humanApproval', True),
                                      ('review', 'fullArticleApproved', True),
                                      ('review', 'overall408Acceptance', True),
                                      ('execution', 'officialQuestionEvidenceCountAdded', 99),
                                      ('execution', 'officialAnswerEvidenceCountAdded', True),
                                      ('execution', 'officialQuestionEvidenceAdded', 99),
                                      ('execution', 'notOfficialAnswer', False),
                                      ('execution', 'notWholeCardReview', False),
                                      ('review', 'unexpectedClaim', True)]:
            execution, review = self.secondary_execution_fixture()
            (review if target == 'review' else execution)[field] = value
            self.save_secondary_reports(execution, review)
            with self.assertRaisesRegex(ValueError, 'cannot grant approval|unknown fields'):
                audit(self.root, self.path)
        for target, field in [('reviewer', 'humanApproval'), ('author', 'overall408Acceptance')]:
            execution, review = self.secondary_execution_fixture()
            if target == 'reviewer': review['reviewer'][field] = True
            else: execution['author'] = {field: True}
            self.save_secondary_reports(execution, review)
            with self.assertRaisesRegex(ValueError, 'cannot grant approval'):
                audit(self.root, self.path)

    def test_secondary_deep_json_is_validation_error_and_cli_returns_structured_failure(self):
        import contextlib
        import io
        for field in ('candidate', 'execution', 'independentReview'):
            for depth in (70, 3000):
                self.secondary_execution_fixture()
                attachment = self.doc['secondaryCandidateExecution']
                binding = attachment[field]
                raw = b'[' * depth + b'0' + b']' * depth
                (self.root / binding['path']).write_bytes(raw)
                binding['sha256'] = hashlib.sha256(raw).hexdigest()
                self.save()
                with self.assertRaisesRegex(ValueError, 'JSON depth'):
                    audit(self.root, self.path)
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    status = evidence_tool.main(['--root', str(self.root), '--evidence', str(self.path)])
                self.assertEqual(status, 1)
                self.assertIs(json.loads(out.getvalue())['verified'], False)

    def test_secondary_artifact_size_limit_rejects_before_json_parsing(self):
        self.secondary_execution_fixture()
        binding = self.doc['secondaryCandidateExecution']['candidate']
        raw = b' ' * (16 * 1024 * 1024 + 1)
        (self.root / binding['path']).write_bytes(raw)
        binding['sha256'] = hashlib.sha256(raw).hexdigest()
        self.save()
        with self.assertRaisesRegex(ValueError, 'exceeds 16 MiB'):
            audit(self.root, self.path)


    def rewrite_secondary_fixture_json(self, field, original, replacement):
        """Mutate raw bytes and refresh all parent bindings without decoding them."""
        attachment = self.doc['secondaryCandidateExecution']
        execution_path = self.root / attachment['execution']['path']
        review_path = self.root / attachment['independentReview']['path']
        execution = json.loads(execution_path.read_bytes())
        review = json.loads(review_path.read_bytes())
        binding = (review['questionBasis'] if field == 'questionBasis'
                   else attachment[field])
        old = {key: binding[key] for key in ('path', 'sha256')}
        path = self.root / old['path']
        raw = path.read_bytes()
        changed = raw.replace(original, replacement, 1)
        self.assertNotEqual(changed, raw, 'raw JSON mutation anchor missing: ' + field)
        path.write_bytes(changed)
        new = {**old, 'sha256': hashlib.sha256(changed).hexdigest()}
        if field == 'independentReview':
            attachment[field] = new
        else:
            review['inputs'] = [new if item == old else item for item in review['inputs']]
            if field == 'candidate':
                attachment['candidate'] = new
                execution['candidate'] = new
                review['candidate'] = new
                self.save_secondary_reports(execution, review)
                return
            if field == 'execution':
                attachment['execution'] = new
                review['execution'] = new
            else:
                review['questionBasis'].update(new)
            review_path.write_text(json.dumps(review), encoding='utf-8')
            attachment['independentReview']['sha256'] = hashlib.sha256(review_path.read_bytes()).hexdigest()
        self.save()

    def test_secondary_json_duplicate_keys_rejected_in_all_report_documents(self):
        cases = [
            ('candidate', b'"schema": "codebrick-curated-article"',
             b'"schema":"wrong","schema":"codebrick-curated-article"'),
            ('execution', b'"humanApproval": false',
             b'"humanApproval":true,"humanApproval":false'),
            ('independentReview', b'"humanApproval": false',
             b'"humanApproval":true,"humanApproval":false'),
            ('independentReview', b'"humanApproval": false',
             b'"humanApproval":true,"human\\u0041pproval":false'),
            ('independentReview', b'"reviewer": {',
             b'"reviewer":{"nested":{"humanApproval":true,"humanApproval":false},'),
            ('questionBasis', b'"provenanceStatus": "secondary-unverified"',
             b'"provenanceStatus":"official","provenanceStatus":"secondary-unverified"'),
            ('questionBasis', b'"officialAuthorityVerified": false',
             b'"officialAuthorityVerified":true,"officialAuthorityVerified":false'),
        ]
        for field, original, replacement in cases:
            with self.subTest(field=field, replacement=replacement):
                self.secondary_execution_fixture()
                self.rewrite_secondary_fixture_json(field, original, replacement)
                with self.assertRaisesRegex(ValueError, 'duplicate secondary execution JSON key'):
                    audit(self.root, self.path)

    def test_secondary_json_nonstandard_numeric_constants_rejected(self):
        cases = [(value, 'non-standard secondary execution JSON constant')
                 for value in (b'NaN', b'Infinity', b'-Infinity')]
        cases += [(value, 'non-finite secondary execution JSON number')
                  for value in (b'1e999', b'-1e999')]
        for value, error in cases:
            with self.subTest(value=value):
                self.secondary_execution_fixture()
                self.rewrite_secondary_fixture_json(
                    'independentReview', b'"reviewer": {',
                    b'"metric":' + value + b',"reviewer":{')
                with self.assertRaisesRegex(ValueError, error):
                    audit(self.root, self.path)

    def test_secondary_attachment_raw_json_constant_and_duplicate_keys_fail_cli(self):
        import contextlib
        import io
        cases = [
            ('candidate', b'"schema": "codebrick-curated-article"',
             b'"schema":"wrong","schema":"codebrick-curated-article"'),
            ('execution', b'"humanApproval": false',
             b'"humanApproval":true,"humanApproval":false'),
            ('independentReview', b'"humanApproval": false',
             b'"humanApproval":true,"humanApproval":false'),
            ('questionBasis', b'"officialAuthorityVerified": false',
             b'"officialAuthorityVerified":true,"officialAuthorityVerified":false'),
            ('independentReview', b'"reviewer": {', b'"metric":NaN,"reviewer":{'),
            ('independentReview', b'"reviewer": {', b'"metric":1e999,"reviewer":{'),
        ]
        for field, original, replacement in cases:
            with self.subTest(field=field, replacement=replacement):
                self.secondary_execution_fixture()
                self.rewrite_secondary_fixture_json(field, original, replacement)
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    status = evidence_tool.main(['--root', str(self.root), '--evidence', str(self.path)])
                self.assertEqual(status, 1)
                self.assertIs(json.loads(output.getvalue())['verified'], False)


if __name__ == '__main__':
    unittest.main()
