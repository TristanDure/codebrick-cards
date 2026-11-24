"""Read-only, exact-hash accounting of non-author AI card review batches.

This validates review records and scope, not reviewer identity or semantic truth.
It never imports human approvals or modifies cards, ledgers or study progress.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

try:
    from . import import_curated_articles as curated
    from .build_disposition_ledger import inside, read, unique
except ImportError:
    import import_curated_articles as curated
    from build_disposition_ledger import inside, read, unique

ROOT = Path(__file__).resolve().parents[1]
GENERATOR_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
DECISIONS = {'PASS', 'FAIL', 'UNPROVEN'}
CHECKS = {'accuracy', 'atomicity', 'assumptions', 'sourceMapping'}


def text_sha(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def reject_declared_self_review(author: dict, reviewer: dict) -> None:
    """Reject explicit identity collisions, without authenticating any identity.

    Historical candidates may lack identity metadata, and generic labels such as
    Codex are not unique people/agents. Absence of a collision proves nothing.
    """
    if not isinstance(author, dict):
        return
    def values(record: dict, fields: tuple[str, ...]) -> set[str]:
        return {record[key].strip().casefold() for key in fields
                if isinstance(record.get(key), str) and record[key].strip()}
    ids = ('agentId', 'threadId')
    if values(author, ids) & values(reviewer, ids):
        raise ValueError('declared author/reviewer identity collision; self-review is not independent')
    generic = {'ai', 'codex', 'openai', 'assistant', 'unknown'}
    labels = ('agent', 'name')
    author_labels = values(author, labels) - generic
    reviewer_labels = values(reviewer, labels) - generic
    if author_labels & reviewer_labels:
        raise ValueError('declared author/reviewer identity collision; self-review is not independent')
    for author_label in author_labels:
        for reviewer_label in reviewer_labels:
            if reviewer_label.startswith(author_label + '-'):
                raise ValueError('declared author/reviewer identity collision; self-review is not independent')


def audit(root: Path, batch_path: Path) -> dict:
    root = root.resolve()
    batch_path = inside(root, str(batch_path))
    batch, batch_sha = read(batch_path)
    if batch.get('schema') != 'codebrick-content-review-batch' or batch.get('version') != 1:
        raise ValueError('unsupported batch schema')
    if not isinstance(batch.get('batchId'), str) or not batch['batchId'].strip():
        raise ValueError('batchId is required')
    if type(batch.get('targetYear')) is not int or not 2009 <= batch['targetYear'] <= 2100:
        raise ValueError('targetYear is required; it is not proof of official scope')
    entries = batch.get('entries')
    if not isinstance(entries, list) or not entries:
        raise ValueError('batch entries must be a nonempty list')
    unique(entries, lambda x: inside(root, x['candidatePath']), 'resolved batch candidate path')
    articles_doc, manifest_sha = read(root / 'data/articles.json')
    source_doc, source_sha = read(root / 'data/knowledge-units.json')
    cards_doc, cards_sha = read(root / 'data/cards/cards.json')
    articles = curated._article_by_url(articles_doc)
    units = curated._units_by_id(source_doc)
    formal_ids = {card['id'] for card in cards_doc['cards']}
    rows = []
    seen_versions = set()
    bindings = {'batch': {'path': batch_path.relative_to(root).as_posix(), 'sha256': batch_sha},
                'articleManifest': {'path': 'data/articles.json', 'sha256': manifest_sha},
                'sourceLedger': {'path': 'data/knowledge-units.json', 'sha256': source_sha},
                'cards': {'path': 'data/cards/cards.json', 'sha256': cards_sha}}
    snapshot_hashes = {inside(root, value['path']): value['sha256'] for value in bindings.values()}
    def pin(key: str, value: dict) -> None:
        resolved = inside(root, value['path'])
        if resolved in snapshot_hashes and snapshot_hashes[resolved] != value['sha256']:
            raise ValueError('conflicting input snapshots for shared path: ' + value['path'])
        if key in bindings and bindings[key] != value:
            raise ValueError('conflicting input binding key: ' + key)
        snapshot_hashes[resolved] = value['sha256']
        bindings[key] = value

    for entry in entries:
        rel = entry['candidatePath']
        path = inside(root, rel)
        proposal, candidate_sha = read(path)
        if entry.get('candidateSha256') != candidate_sha:
            raise ValueError('stale candidate binding: ' + rel)
        structural = curated._validate_proposal(proposal, root=root, candidate_path=path,
                    articles=articles, ledger_by_id=units, formal_card_ids=formal_ids)
        normalized, errors = curated._normalise_proposal(proposal, articles)
        if not structural['ok'] or errors:
            raise ValueError('candidate structure invalid: ' + rel)
        article = normalized['article']
        url = article['url']
        cache_path = articles[url]['cache']
        raw = inside(root, cache_path).read_bytes()
        raw_sha = hashlib.sha256(raw).hexdigest()
        pin('candidate:' + rel, {'path': rel, 'sha256': candidate_sha})
        pin('cache:' + url, {'path': cache_path, 'sha256': raw_sha})
        candidate_cards = normalized['cards']
        ids = [card['cardId'] for card in candidate_cards]
        parsed = curated.sync_sources.parse_article(raw.decode('utf-8'), url)
        if curated._hash_parsed_article(parsed) != article['contentHash']:
            raise ValueError('source content drift after structural validation')
        version_key = (url, candidate_sha)
        if version_key in seen_versions:
            raise ValueError('duplicate article candidate bytes')
        seen_versions.add(version_key)
        section_indices = {section['sectionIndex'] for section in curated.sync_sources.sections(parsed)}
        source_ids = {uid for uid, unit in units.items()
                      if unit.get('articleUrl') == url and unit.get('presentInCurrentSource', True)}
        mapped_ids = {uid for card in candidate_cards for uid in card['knowledgeUnitIds']}
        dispositions = normalized['sourceUnits']
        unresolved = {row['knowledgeUnitId'] for row in dispositions
                      if row.get('disposition') in ('unresolved', 'conflict')}
        review_rel = entry.get('reviewPath')
        decisions = []
        reported_missing = None
        if review_rel:
            review, review_sha = read(inside(root, review_rel))
            if entry.get('reviewSha256') != review_sha:
                raise ValueError('stale review binding: ' + review_rel)
            pin('review:' + review_rel, {'path': review_rel, 'sha256': review_sha})
            if review.get('schema') != 'codebrick-batch-card-review' or review.get('version') != 1:
                raise ValueError('unsupported card review schema')
            reviewer = review.get('reviewer', {})
            if (not isinstance(reviewer, dict) or reviewer.get('kind') != 'ai' or reviewer.get('humanApproval') is not False
                    or reviewer.get('independentOfAuthor') is not True
                    or reviewer.get('role') != 'independent-non-author-reviewer'
                    or not isinstance(reviewer.get('name'), str) or not reviewer['name'].strip()):
                raise ValueError('review must declare non-author AI identity; not human approval')
            reject_declared_self_review(proposal.get('author', {}), reviewer)
            for flag in ('humanApproval', 'contentApproved', 'fullArticleApproved',
                         'overall408Acceptance', 'full408Acceptance'):
                if flag in review and review[flag] is not False:
                    raise ValueError('AI card review cannot claim approval: ' + flag)
            if not isinstance(review.get('reviewedAt'), str):
                raise ValueError('reviewedAt must be an ISO timestamp with timezone')
            date = datetime.fromisoformat(review['reviewedAt'].replace('Z', '+00:00'))
            if date.tzinfo is None:
                raise ValueError('reviewedAt must include timezone')
            if review.get('candidate') != {'path': rel, 'sha256': candidate_sha}:
                raise ValueError('review belongs to another candidate snapshot')
            expected_source = {'articleUrl': url, 'articleContentHash': article['contentHash'],
                               'cachePath': cache_path, 'rawHtmlSha256': raw_sha}
            if review.get('source') != expected_source:
                raise ValueError('review source binding mismatch')
            review_cards = review.get('cards', [])
            if [row.get('id') for row in review_cards] != ids:
                raise ValueError('review must cover every card exactly once in order')
            for card, result in zip(candidate_cards, review_cards):
                if not isinstance(result, dict) or result.get('id') != card['cardId']:
                    raise ValueError('review card order/id mismatch')
                if (result.get('questionSha256') != text_sha(card['front'])
                        or result.get('answerSha256') != text_sha(card['back'])
                        or result.get('unitIds') != card['knowledgeUnitIds']):
                    raise ValueError('card text or source mapping changed: ' + card['cardId'])
                decision = result.get('decision')
                checks = result.get('checks', {})
                if (decision not in DECISIONS or set(checks) != CHECKS
                        or any(value not in DECISIONS for value in checks.values())):
                    raise ValueError('invalid card decision/checks: ' + card['cardId'])
                if decision == 'PASS' and any(value != 'PASS' for value in checks.values()):
                    raise ValueError('PASS conflicts with failed/unproven checks')
                expected = ('FAIL' if 'FAIL' in checks.values() else
                            'UNPROVEN' if 'UNPROVEN' in checks.values() else 'PASS')
                if decision != expected:
                    raise ValueError('card decision conflicts with dimension checks')
                if not result.get('reason', '').strip() or not result.get('counterexampleOrBoundary', '').strip():
                    raise ValueError('each card needs specific evidence and a boundary/counterexample')
                decisions.append({'id': card['cardId'], 'decision': decision,
                                  'checks': checks, 'reason': result['reason']})
            if review.get('fullArticleApproved') is not False or review.get('overall408Acceptance') is not False:
                raise ValueError('batch text review cannot approve full article or 408')
            reported_missing = review.get('missingCoverage', {})
            missing_ids = reported_missing.get('unitIds')
            if not isinstance(missing_ids, list) or len(set(missing_ids)) != len(missing_ids):
                raise ValueError('missing coverage must list unique source unit IDs')
            failed_units = {uid for card, result in zip(candidate_cards, review_cards)
                            if result['decision'] != 'PASS' for uid in card['knowledgeUnitIds']}
            open_issue_units = {uid for issue in proposal.get('issues', [])
                                if issue.get('status') == 'open'
                                for key in ('unitIds', 'knowledgeUnitIds')
                                for uid in issue.get(key, [])}
            required_missing = unresolved | failed_units | open_issue_units
            if not set(missing_ids) <= source_ids or not required_missing <= set(missing_ids):
                raise ValueError('missing coverage omits unresolved/failed/open-issue units or includes unknown units')
            missing_sections = reported_missing.get('sectionIndices')
            if (not isinstance(missing_sections, list)
                    or any(type(index) is not int for index in missing_sections)
                    or len(set(missing_sections)) != len(missing_sections)
                    or not set(missing_sections) <= section_indices):
                raise ValueError('missing coverage needs unique valid section indices')
            if not {units[uid]['sectionIndex'] for uid in missing_ids} <= set(missing_sections):
                raise ValueError('missing source units must appear in missing section scope')
            issues = reported_missing.get('issues')
            if not isinstance(issues, list) or not issues:
                raise ValueError('review must report section scope and remaining evidence issues')
        else:
            decisions = [{'id': card_id, 'decision': 'UNREVIEWED'} for card_id in ids]
        counts = dict(Counter(row['decision'] for row in decisions))
        rows.append({'sourceId': article['sourceId'], 'articleUrl': url, 'candidatePath': rel,
                     'candidateSha256': candidate_sha, 'reviewPath': review_rel,
                     'cardCounts': counts, 'cards': decisions,
                     'exactHashIndependentReviewClaim': bool(review_rel),
                     'allCardTextPassClaim': bool(review_rel) and counts == {'PASS': len(ids)},
                     'sourceUnitCount': len(source_ids), 'cardMappedUnitIds': sorted(mapped_ids),
                     'sourceUnitIdsWithoutCardMapping': sorted(source_ids - mapped_ids),
                     'declaredDispositionCounts': dict(Counter(row['disposition'] for row in dispositions)),
                     'unresolvedOrConflictUnitIds': sorted(unresolved), 'reviewMissingCoverage': reported_missing,
                     'candidateIssues': proposal.get('issues', []),
                     'articleApproved': False, 'humanApproval': False})
    for binding in bindings.values():
        if hashlib.sha256(inside(root, binding['path']).read_bytes()).hexdigest() != binding['sha256']:
            raise ValueError('input snapshot drift during batch audit: ' + binding['path'])
    included = {row['articleUrl'] for row in rows}
    remaining = [{'sourceId': article['sourceId'], 'url': article['url'], 'title': article['title']}
                 for article in articles_doc['articles'] if article['url'] not in included]
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != GENERATOR_SHA256:
        raise ValueError('generator source drift since module load')
    return {'schema': 'codebrick-content-batch-audit', 'version': 1,
            'batchId': batch['batchId'], 'targetYear': batch['targetYear'],
            'generatedAt': datetime.now(timezone.utc).isoformat(), 'inputs': bindings,
            'generator': {'script': 'scripts/audit_content_batch.py',
                          'sha256': GENERATOR_SHA256},
            'articles': rows, 'remainingArticlesOutsideBatch': remaining,
            'summary': {'batchArticles': len(included), 'batchCandidateVersions': len(rows),
                        'corpusArticles': len(articles), 'outsideBatchArticles': len(remaining),
                        'cardDecisions': dict(Counter(card['decision'] for row in rows for card in row['cards']))},
            'humanApprovalsGenerated': 0, 'full408Acceptance': False,
            'limits': ['Identity/independence are explicit reviewer claims, not cryptographic authentication.',
                       'Exact hash and per-card records are accounting checks, not semantic certification.',
                       'No annual official scope or past-paper evidence is established by this audit.',
                       'Unmapped source units include non-card dispositions; mapping is not content coverage.']}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--batch', required=True, type=Path)
    parser.add_argument('--output', type=Path, help='New file inside project; existing files refused')
    args = parser.parse_args(argv)
    try:
        result = audit(args.root, args.batch)
        output = inside(args.root.resolve(), str(args.output)) if args.output else None
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open('x', encoding='utf-8', newline='\n') as stream:
                json.dump(result, stream, ensure_ascii=False, indent=2)
                stream.write('\n')
        print(json.dumps(result['summary'] if output else result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(json.dumps({'verified': False, 'error': str(exc)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
