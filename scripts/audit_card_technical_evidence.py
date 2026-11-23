"""Read-only local binding checks for declared per-card technical evidence.

Hashes/quotes bind bytes, not publisher identity, semantic support or approval.
This is separate from annual official syllabus and past-paper acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

try:
    from .build_disposition_ledger import inside, read
except ImportError:
    from build_disposition_ledger import inside, read

ROOT = Path(__file__).resolve().parents[1]
GENERATOR_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def audit(root: Path, candidate_path: Path, review_path: Path | None = None) -> dict:
    root = root.resolve()
    candidate_path = inside(root, str(candidate_path))
    candidate, digest = read(candidate_path)
    if candidate.get('schema') != 'codebrick-curated-article' or candidate.get('version') != 1:
        raise ValueError('unsupported candidate schema')
    cards = candidate.get('cards')
    if not isinstance(cards, list) or not cards:
        raise ValueError('candidate needs cards')
    if any(not isinstance(card, dict) for card in cards):
        raise ValueError('candidate card rows must be objects')
    ids = [card.get('id') for card in cards]
    if any(not isinstance(cid, str) or not cid.strip() for cid in ids) or len(set(ids)) != len(ids):
        raise ValueError('candidate card IDs must be nonempty and unique')
    bindings = {}
    def pin(binding):
        if not isinstance(binding, dict) or set(binding) != {'path', 'sha256'}:
            raise ValueError('binding needs path and sha256 only')
        path = inside(root, binding['path'])
        if path in bindings and bindings[path] != binding['sha256']:
            raise ValueError('conflicting evidence bindings')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != binding['sha256']:
            raise ValueError('stale evidence binding: ' + binding['path'])
        bindings[path] = binding['sha256']
        return raw
    candidate_binding = {'path': candidate_path.relative_to(root).as_posix(), 'sha256': digest}
    pin(candidate_binding)
    metadata = candidate.get('metadata', {})
    if not isinstance(metadata, dict):
        raise ValueError('candidate metadata must be an object')
    evidence = metadata.get('externalCardEvidence', [])
    if not isinstance(evidence, list):
        raise ValueError('externalCardEvidence must be a list')
    seen = set()
    rows = []
    for item in evidence:
        if not isinstance(item, dict):
            raise ValueError('evidence rows must be objects')
        eid = item.get('id')
        if not isinstance(eid, str) or not eid.strip() or eid in seen:
            raise ValueError('evidence IDs must be nonempty and unique')
        seen.add(eid)
        url = urlparse(item.get('url', ''))
        if url.scheme not in ('http', 'https') or not url.hostname:
            raise ValueError('evidence needs actual HTTP(S) URL')
        for field in ('publisher', 'scope', 'kind'):
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise ValueError('evidence needs publisher, kind and scope')
        card_ids = item.get('cardIds')
        if (not isinstance(card_ids, list) or not card_ids
                or any(not isinstance(cid, str) or cid not in ids for cid in card_ids)
                or len(set(card_ids)) != len(card_ids)):
            raise ValueError('evidence must reference unique actual card IDs')
        snapshots = item.get('snapshots')
        if not isinstance(snapshots, list) or not snapshots:
            raise ValueError('evidence needs snapshots')
        paths = set()
        for binding in snapshots:
            pin(binding)
            path = inside(root, binding['path'])
            if path in paths:
                raise ValueError('duplicate evidence snapshot')
            paths.add(path)
        locator = item.get('locator', {})
        loc_binding = {'path': locator.get('path'), 'sha256': locator.get('sha256')}
        if loc_binding not in snapshots:
            raise ValueError('locator must bind a declared snapshot')
        quote, location = locator.get('quote'), locator.get('location')
        if (not isinstance(quote, str) or not quote.strip()
                or not isinstance(location, str) or not location.strip()):
            raise ValueError('locator needs quote and precise location')
        if quote not in pin(loc_binding).decode('utf-8'):
            raise ValueError('quote is absent from declared snapshot')
        rows.append({'id': eid, 'url': item['url'], 'cardIds': card_ids,
                     'quoteSha256': hashlib.sha256(quote.encode('utf-8')).hexdigest(),
                     'location': location, 'snapshotCount': len(snapshots)})
    review_binding = None
    if review_path is not None:
        review_path = inside(root, str(review_path))
        review, review_sha = read(review_path)
        review_binding = {'path': review_path.relative_to(root).as_posix(), 'sha256': review_sha}
        pin(review_binding)
        if review.get('candidate') != candidate_binding:
            raise ValueError('review candidate binding mismatch')
        reviewer = review.get('reviewer', {})
        if (review.get('schema') != 'codebrick-batch-card-review' or review.get('version') != 1
                or reviewer.get('kind') != 'ai' or reviewer.get('independentOfAuthor') is not True
                or reviewer.get('humanApproval') is not False
                or reviewer.get('role') != 'independent-non-author-reviewer'
                or not isinstance(reviewer.get('name'), str) or not reviewer['name'].strip()
                or review.get('humanApproval') is not False
                or review.get('fullArticleApproved') is not False
                or review.get('overall408Acceptance') is not False):
            raise ValueError('review must not imply human/full article/408 approval')
        review_evidence = review.get('externalEvidence', [])
        if not isinstance(review_evidence, list):
            raise ValueError('review external evidence must be a list')
        if any(not isinstance(item, dict) for item in review_evidence):
            raise ValueError('review evidence rows must be objects')
        if ([item.get('id') for item in review_evidence] != [item['id'] for item in evidence]):
            raise ValueError('review must account for each evidence item in order')
        for expected, observed in zip(evidence, review_evidence):
            if observed.get('url') != expected['url'] or observed.get('cardIds') != expected['cardIds']:
                raise ValueError('review evidence URL/card scope mismatch')
            observed_snapshots = observed.get('snapshots', [])
            if not isinstance(observed_snapshots, list):
                raise ValueError('review evidence needs snapshots')
            projected = [{'path': b.get('path'), 'sha256': b.get('sha256')} for b in observed_snapshots]
            if projected != expected['snapshots']:
                raise ValueError('review snapshot bindings mismatch')
            loc = observed.get('locator', {})
            source = expected['locator']
            if (loc.get('path') != source['path'] or loc.get('location') != source['location']
                    or loc.get('quote') != source['quote']
                    or loc.get('quoteSha256') != hashlib.sha256(source['quote'].encode('utf-8')).hexdigest()):
                raise ValueError('review quote binding mismatch')
    for path, expected_sha in bindings.items():
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha:
            raise ValueError('evidence drift during audit')
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != GENERATOR_SHA256:
        raise ValueError('generator source drift since load')
    return {'schema': 'codebrick-card-technical-evidence-audit', 'version': 1,
            'generatedAt': datetime.now(timezone.utc).isoformat(),
            'candidate': candidate_binding, 'review': review_binding,
            'generator': {'path': 'scripts/audit_card_technical_evidence.py', 'sha256': GENERATOR_SHA256},
            'inputs': [{'path': p.relative_to(root).as_posix(), 'sha256': s} for p, s in bindings.items()],
            'items': rows, 'evidenceItems': len(rows),
            'localBindingsConsistent': True, 'humanApprovalsGenerated': 0,
            'sourceAuthenticityVerified': False, 'semanticSupportVerified': False,
            'fullArticleApproved': False, 'full408Acceptance': False,
            'limits': ['Checks declared local bytes, quotes and card associations only.',
                       'Does not authenticate publisher, HTTP capture, identity or semantic sufficiency.',
                       'Does not establish annual official requirements or official exam questions.']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--review', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    try:
        result = audit(args.root, args.candidate, args.review)
        if args.output:
            output = inside(args.root.resolve(), str(args.output))
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open('x', encoding='utf-8', newline='\n') as stream:
                json.dump(result, stream, ensure_ascii=False, indent=2)
                stream.write('\n')
        print(json.dumps({key: result[key] for key in ['evidenceItems', 'localBindingsConsistent',
                          'humanApprovalsGenerated', 'semanticSupportVerified', 'full408Acceptance']}, indent=2))
        return 0
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(json.dumps({'localBindingsConsistent': False, 'error': str(exc)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
