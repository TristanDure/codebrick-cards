"""Build an isolated original demo without modifying the source workspace."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ('workbench.html', 'workbench.js', 'workbench.css', 'workbench-progress.js')


def build(root: Path, site: Path) -> int:
    root, site = root.resolve(), site.resolve()
    if site == root or root in site.parents or site in root.parents:
        raise ValueError('Static site destination must be outside the project directory')
    ignored_data = root / '.gitignore'
    if not ignored_data.is_file() or 'data/*' not in ignored_data.read_text(encoding='utf-8-sig'):
        raise ValueError('Refusing to build a demo in a root without the data/* local-data ignore rule')
    if site.exists() and (not site.is_dir() or any(site.iterdir())):
        raise ValueError(f'Site destination is not empty: {site}')
    for name in ASSETS:
        if not (root / 'web' / name).is_file():
            raise ValueError(f'Missing web asset: {name}')
    try:
        from scripts.prepare_workspace import prepare_demo
    except ModuleNotFoundError as exc:
        if exc.name != 'scripts':
            raise
        from prepare_workspace import prepare_demo
    with tempfile.TemporaryDirectory(prefix='codebrick-public-demo-') as tmp:
        staging = Path(tmp)
        code = prepare_demo(staging)
        if code:
            return code
        site.mkdir(parents=True, exist_ok=True)
        (site / 'web').mkdir()
        for name in ASSETS:
            shutil.copy2(root / 'web' / name, site / 'web' / name)
        shutil.copytree(staging / 'data/study', site / 'data/study')
        (site / 'index.html').write_text(
            '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta http-equiv="refresh" content="0;url=web/workbench.html">'
            '<title>CodeBrick Cards demo</title></head><body>'
            '<a href="web/workbench.html">打开四科原创演示工作台</a></body></html>', encoding='utf-8')
    print(f'Isolated static demo ready at {site}; four original, unapproved candidates.')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--site', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        return build(args.root, args.site)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'Site build failed: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
