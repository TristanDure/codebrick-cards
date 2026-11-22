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
        if shard['article']['id'] != article['id']:
            raise ValueError('shard identity mismatch')
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
