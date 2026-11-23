"""Validate local annual-syllabus and past-paper evidence chains, not authenticity.

Catalogues, web labels and secondary reproductions never satisfy full-text gates.
Unknown official requirement counts remain null, not zero or 100% coverage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

try:
    from .build_disposition_ledger import inside, read, unique
    from . import import_curated_articles as curated
except ImportError:
    from build_disposition_ledger import inside, read, unique
    import import_curated_articles as curated

ROOT = Path(__file__).resolve().parents[1]
GENERATOR_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
SUBJECTS = {'os', 'co', 'cn', 'ds'}
LEVELS = {'catalog-only', 'full-text', 'partial-text', 'secondary-reference'}
KINDS = {'annual-syllabus', 'annual-regulation', 'past-paper', 'answer-key',
         'paper-collection-catalog', 'reference-framework', 'technical-reference'}


def requirement_sha(requirement: dict, source: dict) -> str:
    """Bind the exact clause AND its declared source, not just a reusable ID."""
    payload = json.dumps({'requirement': requirement, 'source': source},
                         ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def question_evidence_sha(item: dict, source: dict) -> str:
    payload = json.dumps({'itemEvidence': item, 'source': source},
                         ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def full_item_evidence(root: Path, item: dict, source: dict, identity: dict) -> None:
    if (not isinstance(item, dict) or item.get('identity') != identity
            or item.get('completeness') != 'full-item'):
        raise ValueError('full item evidence must bind the same question identity')
    text, label = item.get('itemText'), item.get('labelText')
    if (not isinstance(text, str) or not isinstance(label, str) or not label.strip()
            or not text.startswith(label) or re.findall(r'\d+', label) != [str(identity['questionNumber'])]
            or not text[len(label):].strip(' .．:：、')):
        raise ValueError('item needs its question label and actual body, not a catalog marker')
    if text[len(label):len(label)+1].isdigit():
        raise ValueError('question label boundary does not match the complete item label')
    locator = item.get('textLocator', {})
    if locator.get('quote') != text:
        raise ValueError('full item locator must quote the entire declared item text')
    quoted_evidence(root, locator, source)


def quoted_evidence(root: Path, locator: dict, source: dict) -> dict:
    binding = {'path': locator.get('path'), 'sha256': locator.get('sha256')}
    if binding not in source['snapshots']:
        raise ValueError('locator is not bound to a captured source snapshot')
    raw = inside(root, locator['path']).read_bytes()
    if hashlib.sha256(raw).hexdigest() != locator['sha256']:
        raise ValueError('stale quoted evidence snapshot')
    quote = locator.get('quote')
    if not isinstance(quote, str) or not quote.strip():
        raise ValueError('locator needs verbatim quoted text')
    if quote not in raw.decode('utf-8'):
        raise ValueError('quoted evidence not present in captured UTF-8 text')
    if not isinstance(locator.get('location'), str) or not locator['location'].strip():
        raise ValueError('quote needs page/section/paragraph location')
    return binding


def audit(root: Path, evidence_path: Path) -> dict:
    root = root.resolve()
    evidence_path = inside(root, str(evidence_path))
    doc, digest = read(evidence_path)
    if doc.get('schema') != 'codebrick-exam-evidence-chain' or doc.get('version') != 1:
        raise ValueError('unsupported exam evidence schema')
    target = doc.get('targetYear')
    if type(target) is not int or not 2009 <= target <= 2100:
        raise ValueError('targetYear must be an explicit examination admission year')
    if not isinstance(doc.get('sources'), list) or not doc['sources']:
        raise ValueError('evidence sources must be a nonempty list')
    sources = unique(doc['sources'], lambda row: row['id'], 'evidence source')
    bindings = {'manifest': {'path': evidence_path.relative_to(root).as_posix(), 'sha256': digest}}
    snapshot_hashes = {inside(root, value['path']): value['sha256'] for value in bindings.values()}
    def pin(key: str, value: dict) -> None:
        resolved = inside(root, value['path'])
        if resolved in snapshot_hashes and snapshot_hashes[resolved] != value['sha256']:
            raise ValueError('conflicting input snapshots for shared path: ' + value['path'])
        if key in bindings and bindings[key] != value:
            raise ValueError('conflicting input binding key: ' + key)
        snapshot_hashes[resolved] = value['sha256']
        bindings[key] = value

    for sid, source in sources.items():
        if source.get('kind') not in KINDS or source.get('evidenceLevel') not in LEVELS:
            raise ValueError('unrecognized evidence kind/level: ' + sid)
        if not isinstance(source.get('publisher'), str) or not source['publisher'].strip():
            raise ValueError('source needs publisher attribution, not domain inference')
        if source.get('authority') not in ('official-authority', 'official-publisher', 'secondary'):
            raise ValueError('source authority classification is required')
        parsed = urlparse(source.get('url', ''))
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            raise ValueError('source needs an actual HTTP(S) URL')
        snapshots = source.get('snapshots')
        if not isinstance(snapshots, list) or not snapshots:
            raise ValueError('source needs captured, hash-bound evidence: ' + sid)
        for index, binding in enumerate(snapshots):
            if set(binding) != {'path', 'sha256'}:
                raise ValueError('snapshot binding fields must be path and sha256')
            raw = inside(root, binding['path']).read_bytes()
            if hashlib.sha256(raw).hexdigest() != binding['sha256']:
                raise ValueError('stale source snapshot: ' + sid)
            pin(f'source:{sid}:{index}', binding)
        if type(source.get('documentYear')) is not int or not 2009 <= source['documentYear'] <= 2100:
            raise ValueError('source needs an explicit document year')
        for field in ('proves', 'doesNotProve'):
            values = source.get(field)
            if (not isinstance(values, list) or not values
                    or any(not isinstance(value, str) or not value.strip() for value in values)):
                raise ValueError('source needs explicit claim and limitation boundaries')
    requirements = doc.get('officialRequirements')
    if requirements is not None and (not isinstance(requirements, list) or not requirements):
        raise ValueError('unknown requirements must be null, never an empty complete scope')
    complete = doc.get('officialRequirementInventoryComplete')
    if type(complete) is not bool or complete and requirements is None:
        raise ValueError('full requirement inventory cannot be complete without official text')
    requirement_map = unique(requirements or [], lambda row: row['id'], 'official requirement')
    for rid, requirement in requirement_map.items():
        source = sources[requirement['sourceId']]
        if (source['kind'] != 'annual-syllabus' or source['evidenceLevel'] != 'full-text'
                or source['authority'] not in ('official-authority', 'official-publisher')
                or source.get('documentYear') != target or requirement.get('year') != target
                or requirement.get('subjectId') not in SUBJECTS):
            raise ValueError('official target-year requirement cannot use catalog/old/secondary source: ' + rid)
        quoted_evidence(root, requirement['locator'], source)
    mappings = doc.get('requirementMappings', [])
    unique(mappings, lambda row: row['requirementId'], 'requirement mapping')
    reviewed_mappings = []
    seen_candidate_mappings = set()
    candidate_context = None
    for mapping in mappings:
        if not isinstance(mapping, dict) or mapping.get('requirementId') not in requirement_map:
            raise ValueError('mapping refers to absent official requirement')
        if set(mapping) - {'requirementId', 'candidatePath', 'candidateSha256', 'cardIds', 'status', 'independentReview'}:
            raise ValueError('mapping contains unsupported fields')
        candidate_path = inside(root, mapping['candidatePath'])
        candidate, candidate_sha = read(candidate_path)
        if candidate_sha != mapping['candidateSha256']:
            raise ValueError('mapping candidate binding drift')
        candidate_key = (candidate_path, candidate_sha, mapping.get('requirementId'))
        if candidate_key in seen_candidate_mappings:
            raise ValueError('duplicate candidate mapping entry')
        seen_candidate_mappings.add(candidate_key)
        if candidate_context is None:
            articles_doc, articles_sha = read(root / 'data/articles.json')
            units_doc, units_sha = read(root / 'data/knowledge-units.json')
            cards_doc, cards_sha = read(root / 'data/cards/cards.json')
            candidate_context = (curated._article_by_url(articles_doc), curated._units_by_id(units_doc),
                                 {card['id'] for card in cards_doc['cards']})
            for name, rel, digest in [('articleManifest', 'data/articles.json', articles_sha),
                                      ('sourceLedger', 'data/knowledge-units.json', units_sha),
                                      ('cards', 'data/cards/cards.json', cards_sha)]:
                pin(name, {'path': rel, 'sha256': digest})
        articles, units, formal_ids = candidate_context
        structure = curated._validate_proposal(candidate, root=root,
                    candidate_path=inside(root, mapping['candidatePath']), articles=articles,
                    ledger_by_id=units, formal_card_ids=formal_ids)
        normalized, errors = curated._normalise_proposal(candidate, articles)
        if not structure['ok'] or errors:
            raise ValueError('mapping candidate structure invalid')
        article = normalized['article']
        if article['sourceId'] != requirement_map[mapping['requirementId']]['subjectId']:
            raise ValueError('mapping subject does not match candidate subject')
        cache_rel = articles[article['url']]['cache']
        raw = inside(root, cache_rel).read_bytes()
        parsed = curated.sync_sources.parse_article(raw.decode('utf-8'), article['url'])
        if curated._hash_parsed_article(parsed) != article['contentHash']:
            raise ValueError('mapping candidate source drift after structural validation')
        pin('candidateCache:' + cache_rel, {'path': cache_rel,
                                           'sha256': hashlib.sha256(raw).hexdigest()})
        ids = {card['cardId'] for card in normalized['cards']}
        if (not isinstance(mapping.get('cardIds'), list) or not mapping['cardIds']
                or any(not isinstance(cid, str) or not cid.strip() for cid in mapping['cardIds'])
                or len(set(mapping['cardIds'])) != len(mapping['cardIds'])
                or not set(mapping['cardIds']) <= ids):
            raise ValueError('requirement mapping lacks actual card IDs')
        if mapping.get('status') not in ('proposed-ai-mapping', 'independently-reviewed-ai-mapping'):
            raise ValueError('mapping status must not imply human approval')
        if mapping['status'] == 'independently-reviewed-ai-mapping':
            review_binding = mapping.get('independentReview')
            if not isinstance(review_binding, dict):
                raise ValueError('reviewed mapping needs a pinned independent review')
            review, review_sha = read(inside(root, review_binding['path']))
            if review_sha != review_binding['sha256']:
                raise ValueError('stale independent mapping review')
            if (review.get('schema') != 'codebrick-exam-mapping-review' or review.get('version') != 1
                    or review.get('requirementId') != mapping['requirementId']
                    or review.get('requirementSha256') != requirement_sha(
                        requirement_map[mapping['requirementId']],
                        sources[requirement_map[mapping['requirementId']]['sourceId']])
                    or review.get('candidatePath') != mapping['candidatePath']
                    or review.get('candidateSha256') != candidate_sha
                    or review.get('cardIds') != mapping['cardIds'] or review.get('decision') != 'PASS'
                    or review.get('humanApproval') is not False
                    or review.get('reviewer', {}).get('kind') != 'ai'
                    or review.get('reviewer', {}).get('independentOfAuthor') is not True
                    or review.get('reviewer', {}).get('role') != 'independent-non-author-reviewer'
                    or not isinstance(review.get('reviewer', {}).get('name'), str)
                    or not review.get('reviewer', {}).get('name', '').strip()
                    or not isinstance(review.get('reason'), str) or not review['reason'].strip()):
                raise ValueError('independent mapping review is inconsistent or unproven')
            pin('mappingReview:' + mapping['requirementId'], review_binding)
            reviewed_mappings.append(mapping['requirementId'])
        pin('candidate:' + mapping['candidatePath'], {
            'path': mapping['candidatePath'], 'sha256': candidate_sha})
    papers = doc.get('pastPaperQuestions', [])
    if not isinstance(papers, list):
        raise ValueError('pastPaperQuestions must be a list')
    unique(papers, lambda row: row['id'], 'past-paper question')
    if type(doc.get('pastPaperInventoryComplete')) is not bool:
        raise ValueError('pastPaperInventoryComplete must be an explicit boolean')
    if doc['pastPaperInventoryComplete'] and (
            not papers or any(row.get('identityStatus') != 'official-full-text-verified' for row in papers)):
        raise ValueError('complete past-paper inventory requires actual official question/answer evidence')
    official_questions = []
    seen_question_identities = set()
    question_rows = []
    for question in papers:
        if not isinstance(question, dict) or not isinstance(question.get('id'), str):
            raise ValueError('past-paper item needs a stable ID')
        source = sources[question['sourceId']]
        identity = question.get('identityStatus')
        if not isinstance(question, dict) or question.get('identityStatus') not in (
                'official-full-text-verified', 'secondary-unverified', 'catalog-only'):
            raise ValueError('invalid question provenance status')
        if (question.get('subjectId') not in SUBJECTS or type(question.get('examYear')) is not int
                or not 2009 <= question['examYear'] <= 2100):
            raise ValueError('question needs subject and examination year')
        if identity == 'official-full-text-verified':
            if (source['kind'] != 'past-paper' or source['evidenceLevel'] != 'full-text'
                    or source['authority'] not in ('official-authority', 'official-publisher')
                    or source.get('documentYear') != question['examYear']):
                raise ValueError('official question cannot use catalog or secondary evidence')
            number = question.get('questionNumber')
            if type(number) is not int or number < 1:
                raise ValueError('official item needs an explicit question number')
            identity_key = {'examYear': question['examYear'], 'subjectId': question['subjectId'],
                            'questionNumber': number}
            canonical = (question['examYear'], question['subjectId'], number)
            if canonical in seen_question_identities:
                raise ValueError('duplicate canonical question identity')
            seen_question_identities.add(canonical)
            stem = question.get('stemEvidence')
            full_item_evidence(root, stem, source, identity_key)
            question_type = question.get('questionType')
            options = question.get('options')
            if question_type not in ('constructed-response', 'multiple-choice'):
                raise ValueError('official question needs a question type and option scope')
            if question_type == 'multiple-choice' and (
                    not isinstance(options, list) or len(options) < 2
                    or any(not isinstance(option, str) or not option.strip()
                           or option not in stem['itemText'] for option in options)
                    or len(set(options)) != len(options)):
                raise ValueError('full multiple-choice item must include all declared options')
            if question_type == 'constructed-response' and options != []:
                raise ValueError('constructed-response item options must be explicitly empty')
            answer = sources[question['answerSourceId']]
            if (answer['kind'] != 'answer-key' or answer['evidenceLevel'] != 'full-text'
                    or answer['authority'] == 'secondary' or answer.get('documentYear') != question['examYear']):
                raise ValueError('official answer evidence missing or secondary')
            answer_item = question.get('answerEvidence')
            full_item_evidence(root, answer_item, answer, identity_key)
            pair_binding = question.get('independentPairReview')
            if not isinstance(pair_binding, dict):
                raise ValueError('full-item identity and completeness need a pinned independent pair review')
            pair, pair_sha = read(inside(root, pair_binding['path']))
            reviewer = pair.get('reviewer', {})
            if (pair_sha != pair_binding.get('sha256')
                    or pair.get('schema') != 'codebrick-past-paper-pair-review' or pair.get('version') != 1
                    or pair.get('identity') != identity_key
                    or pair.get('stemEvidenceSha256') != question_evidence_sha(stem, source)
                    or pair.get('answerEvidenceSha256') != question_evidence_sha(answer_item, answer)
                    or pair.get('questionType') != question_type or pair.get('options') != options
                    or pair.get('decision') != 'PASS' or pair.get('humanApproval') is not False
                    or not isinstance(reviewer, dict) or reviewer.get('kind') != 'ai' or reviewer.get('independentOfAuthor') is not True
                    or reviewer.get('role') != 'independent-evidence-reviewer'
                    or not isinstance(reviewer.get('name'), str) or not reviewer['name'].strip()
                    or pair.get('checks') != {'identityPairing': 'PASS', 'stemCompleteness': 'PASS',
                                              'answerCompleteness': 'PASS'}
                    or not isinstance(pair.get('reason'), str) or not pair['reason'].strip()):
                raise ValueError('independent full-item pair review is stale, inconsistent, or unproven')
            pin('questionPairReview:' + question['id'], pair_binding)
            official_questions.append(question['id'])
        question_rows.append({'id': question['id'], 'identityStatus': identity,
                              'examYear': question['examYear'], 'subjectId': question['subjectId'],
                              'questionNumber': question.get('questionNumber'),
                              'officialFullItemEvidenceAccounted': identity == 'official-full-text-verified'})
    for binding in bindings.values():
        if hashlib.sha256(inside(root, binding['path']).read_bytes()).hexdigest() != binding['sha256']:
            raise ValueError('input snapshot drift during exam evidence audit: ' + binding['path'])
    syllabus_ready = bool(complete and requirements and len(reviewed_mappings) == len(requirement_map))
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != GENERATOR_SHA256:
        raise ValueError('generator source drift since module load')
    return {'schema': 'codebrick-exam-evidence-audit', 'version': 1, 'targetYear': target,
            'generatedAt': datetime.now(timezone.utc).isoformat(), 'inputs': bindings,
            'generator': {'script': 'scripts/audit_exam_evidence.py',
                          'sha256': GENERATOR_SHA256},
            'sourceCounts': dict(Counter(source['evidenceLevel'] for source in sources.values())),
            'officialRequirementCount': len(requirement_map) if requirements is not None else None,
            'officialRequirementInventoryComplete': complete,
            'mappedRequirementCount': len(mappings) if requirements is not None else None,
            'independentlyReviewedMappingCount': len(reviewed_mappings) if requirements is not None else None,
            'candidateMappingCoverage': len(mappings) / len(requirement_map) if complete and requirement_map else None,
            'officialMappingCoverage': len(reviewed_mappings) / len(requirement_map) if complete and requirement_map else None,
            'targetAnnualEvidenceAccounted': syllabus_ready,
            'questions': question_rows, 'officialQuestionEvidenceCount': len(official_questions),
            'pastPaperInventoryComplete': doc.get('pastPaperInventoryComplete') is True,
            'full408Acceptance': False, 'humanApprovalsGenerated': 0,
            'evidenceAssessment': 'declared-provenance-with-exact-local-bindings',
            'limits': ['This checks captured local evidence bindings and declared provenance, not digital authenticity.',
                       'Book metadata and contents pages do not establish clause text or complete paper questions.',
                       'Mapping and official question identity are separate from independently solving each question.',
                       'Missing official annual text leaves requirement counts and coverage null.']}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    try:
        result = audit(args.root, args.evidence)
        if args.output:
            output = inside(args.root.resolve(), str(args.output))
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open('x', encoding='utf-8', newline='\n') as stream:
                json.dump(result, stream, ensure_ascii=False, indent=2)
                stream.write('\n')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(json.dumps({'verified': False, 'error': str(exc)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
