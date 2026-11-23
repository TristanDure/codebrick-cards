"""Build current review-version scope from a fresh exact-hash batch audit.

A reviewed version is not necessarily the latest authored candidate. This report
accounts decisions and uncovered units; it never approves articles or people.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

try:
    from .audit_content_batch import audit, ROOT
    from .build_disposition_ledger import inside
except ImportError:
    from audit_content_batch import audit, ROOT
    from build_disposition_ledger import inside

GENERATOR_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
SUBJECTS = ('os', 'co', 'cn', 'ds')


def build(root: Path, batch: Path) -> dict:
    root = root.resolve()
    result = audit(root, batch)  # Never trust a caller-provided old audit summary.
    manifest = result['inputs']['articleManifest']
    ledger = result['inputs']['sourceLedger']
    articles = json.loads(inside(root, manifest['path']).read_text(encoding='utf-8'))['articles']
    units = json.loads(inside(root, ledger['path']).read_text(encoding='utf-8'))['units']
    urls = [r['articleUrl'] for r in result['articles']]
    if len(urls) != len(set(urls)):
        raise ValueError('scope requires one reviewed candidate version per articleUrl')
    if any(a['sourceId'] not in SUBJECTS for a in articles):
        raise ValueError('unsupported article subject')
    active = [u for u in units if u.get('presentInCurrentSource', True)]
    if any(u['sourceId'] not in SUBJECTS for u in active):
        raise ValueError('unsupported active source-unit subject')
    article_counts = Counter(a['sourceId'] for a in articles)
    unit_counts = Counter(u['sourceId'] for u in active)
    subjects = {}
    scopes = []
    for subject in SUBJECTS:
        rows = [r for r in result['articles'] if r['sourceId'] == subject]
        decisions = Counter()
        for row in rows:
            decisions.update(row['cardCounts'])
        reviewed = sum(bool(r['exactHashIndependentReviewClaim']) for r in rows)
        subjects[subject] = {
            'articles': article_counts[subject], 'batchArticles': len(rows),
            'reviewedVersionArticles': reviewed,
            'outsideBatchArticles': article_counts[subject] - len(rows),
            'activeSourceUnits': unit_counts[subject],
            'cards': sum(decisions.values()),
            'decisions': {d: decisions[d] for d in ('PASS', 'UNPROVEN', 'FAIL', 'UNREVIEWED')},
        }
    for row in result['articles']:
        missing = row['reviewMissingCoverage']
        scopes.append({
            'sourceId': row['sourceId'], 'articleUrl': row['articleUrl'],
            'reviewedCandidatePath': row['candidatePath'],
            'candidateSha256': row['candidateSha256'], 'reviewPath': row['reviewPath'],
            'reviewedVersionOnly': True,
            'decisions': row['cardCounts'],
            'sourceUnitCount': row['sourceUnitCount'],
            'sourceUnitIdsWithoutCardMapping': row['sourceUnitIdsWithoutCardMapping'],
            'unresolvedOrConflictUnitIds': row['unresolvedOrConflictUnitIds'],
            'reviewMissingCoverage': missing,
            'allCardTextPassClaim': row['allCardTextPassClaim'],
            'fullArticleApproved': False,
        })
    # Read inputs again after inventory extraction to reject intervening changes.
    for value in result['inputs'].values():
        if hashlib.sha256(inside(root, value['path']).read_bytes()).hexdigest() != value['sha256']:
            raise ValueError('input drift while building scope: ' + value['path'])
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != GENERATOR_SHA256:
        raise ValueError('generator source drift since load')
    return {
        'schema': 'codebrick-content-scope-snapshot', 'version': 1,
        'generatedAt': datetime.now(timezone.utc).isoformat(),
        'targetYear': result['targetYear'], 'batchId': result['batchId'],
        'inputs': result['inputs'],
        'generator': {'path': 'scripts/build_content_scope_snapshot.py', 'sha256': GENERATOR_SHA256},
        'corpus': {**result['summary'], 'activeSourceUnits': len(active),
                   'reviewedVersionArticles': sum(bool(r['exactHashIndependentReviewClaim']) for r in result['articles'])},
        'subjects': subjects, 'articleScopes': scopes,
        'remainingArticlesOutsideBatch': result['remainingArticlesOutsideBatch'],
        'humanApprovalsGenerated': 0, 'full408Acceptance': False,
        'limits': [
            'Reviewed version means exact candidate/review bytes in this batch, not the latest authored revision.',
            'No latest-version policy is inferred from filenames, modification times or prior PASS.',
            'Unmapped units include justified non-card dispositions; mapped units are not semantic coverage.',
            'AI per-card decisions and machine binding checks are not human approval or whole-article acceptance.',
            'Annual official requirements and authentic past-paper identity need a separate evidence chain.',
        ],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--batch', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        output = inside(args.root.resolve(), str(args.output))
        if output.exists():
            raise ValueError('refusing to overwrite: ' + str(output))
        result = build(args.root, args.batch)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        print(json.dumps(result['corpus'], ensure_ascii=False, indent=2))
        return 0
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(json.dumps({'verified': False, 'error': str(exc)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
