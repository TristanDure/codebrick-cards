"""Prepare a self-contained static demo site without serving private project files."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]


def build(root: Path, site: Path) -> int:
    from prepare_workspace import main as prepare
    code = prepare(['--root', str(root), '--demo'])
    if code:
        return code
    if site.resolve() == root.resolve() or root.resolve() in site.resolve().parents:
        raise ValueError('Static site destination must be outside the project directory')
    if site.exists() and any(site.iterdir()):
        raise ValueError(f'Site destination is not empty: {site}')
    site.mkdir(parents=True, exist_ok=True)
    for name in ('index.html', 'web'):
        source = root / name
        target = site / name
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        else:
            shutil.copy2(source, target)
    target_data = site / 'data/study'
    target_data.mkdir(parents=True, exist_ok=True)
    index = json.loads((root / 'data/study/index.json').read_text(encoding='utf-8'))
    for article in index['articles']:
        relative = Path(article['file'])
        source = (root / 'data/study' / relative).resolve()
        if root.resolve() not in source.parents:
            raise ValueError('Unsafe demo shard path')
        target = target_data / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    shutil.copy2(root / 'data/study/index.json', target_data / 'index.json')
    print(f'Isolated static demo ready at {site}; only original demo data and web assets copied.')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--site', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        return build(args.root.resolve(), args.site.resolve())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'Site build failed: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
