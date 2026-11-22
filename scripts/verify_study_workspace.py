"""Read-only integrity check for a published article workspace (no content approval)."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path


def verify(root: Path) -> int:
    base = (root / 'data/study').resolve()
    index = json.loads((base / 'index.json').read_text(encoding='utf-8-sig'))
    if index.get('schema') != 'codebrick-article-workspace':
        raise ValueError('unexpected workspace schema')
    if index.get('contentApproved') is not False:
        raise ValueError('workspace must not claim content approval')
    summary = index.get('summary')
    if not isinstance(summary, dict) or summary.get('approvedCards') != 0:
        raise ValueError('workspace must report zero approved cards')
    articles = index['articles']
    if not articles or len(articles) != index['summary']['articles']:
        raise ValueError('article count mismatch or empty workspace')
    seen = set()
    for article in articles:
        path = (base / article['file']).resolve()
        if base not in path.parents or path in seen:
            raise ValueError('unsafe or duplicate shard path')
        seen.add(path)
        raw = path.read_bytes()
        if len(raw) != article['bytes'] or hashlib.sha256(raw).hexdigest() != article['sha256']:
            raise ValueError('shard integrity mismatch: ' + article['id'])
        shard = json.loads(raw)
        if shard.get('contentApproved') is not False:
            raise ValueError('shard must not claim content approval')
        shard_article = shard.get('article')
        if not isinstance(shard_article, dict) or shard_article.get('id') != article['id']:
            raise ValueError('shard identity mismatch')
        article_summary = shard_article.get('summary')
        if not isinstance(article_summary, dict) or article_summary.get('approvedCards') != 0:
            raise ValueError('shard must report zero approved cards')
        candidate_groups = [shard.get('atomicCandidates', [])]
        candidate_groups.extend(draft.get('cards', []) for draft in shard.get('curated', []))
        if any(not isinstance(group, list) or any(not isinstance(card, dict) for card in group)
               for group in candidate_groups):
            raise ValueError('invalid candidate collection')
        if any(card.get('status') == 'approved' for group in candidate_groups for card in group):
            raise ValueError('candidate cards must not claim approved status')
    return len(articles)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    try:
        count = verify(args.root)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('Workspace verification failed: ' + str(exc))
        return 1
    print(f'Verified {count} article shards. Integrity check only; not content approval.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
