"""Merge exact-hash review batches into a one-version-per-article snapshot.

Only bookkeeping: reviews can contain FAIL/UNPROVEN. No semantic or human
approval is issued. Inputs and previous snapshots are never overwritten.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

try:
    from .audit_content_batch import audit, ROOT
    from .build_disposition_ledger import inside, read
except ImportError:
    from audit_content_batch import audit, ROOT
    from build_disposition_ledger import inside, read


def _indexed(root: Path, path: Path):
    result = audit(root, path)
    document, digest = read(inside(root, str(path)))
    if digest != result['inputs']['batch']['sha256']:
        raise ValueError('batch drift after audit')
    rows = {row['candidatePath']: row for row in result['articles']}
    indexed = {}
    for entry in document['entries']:
        row = rows[entry['candidatePath']]
        url = row['articleUrl']
        if url in indexed:
            raise ValueError('duplicate articleUrl in current-version input: ' + url)
        indexed[url] = copy.deepcopy(entry)
    return document, result, indexed


def merge(root: Path, base: Path, additions: Path, batch_id: str):
    root = root.resolve()
    if not isinstance(batch_id, str) or not batch_id.strip():
        raise ValueError('batchId must be nonempty')
    base_doc, base_audit, current = _indexed(root, base)
    add_doc, add_audit, updates = _indexed(root, additions)
    if base_doc['targetYear'] != add_doc['targetYear']:
        raise ValueError('target years differ')
    transitions = []
    for url, entry in updates.items():
        if not entry.get('reviewPath'):
            raise ValueError('unreviewed addition cannot replace a reviewed snapshot: ' + url)
        previous = current.get(url)
        if previous == entry:
            continue
        transitions.append({'articleUrl': url, 'action': 'replace' if previous else 'add',
                            'previous': previous, 'current': copy.deepcopy(entry)})
        current[url] = entry
    if not transitions:
        raise ValueError('no new review bindings; refusing a no-op snapshot')
    # The two audits may share candidate/cache/manifest paths; detect drift both
    # across their execution and immediately before the caller writes anything.
    bindings = {}
    for result in (base_audit, add_audit):
        for binding in result['inputs'].values():
            path = inside(root, binding['path'])
            digest = binding['sha256']
            if path in bindings and bindings[path] != digest:
                raise ValueError('conflicting shared input hashes')
            bindings[path] = digest
    for path, digest in bindings.items():
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('input drift while merging: ' + str(path))
    return {'schema': 'codebrick-content-review-batch', 'version': 1,
            'batchId': batch_id, 'targetYear': base_doc['targetYear'],
            'entries': list(current.values()),
            'previousBatch': base_audit['inputs']['batch']['path'],
            'mergeInputs': {'base': base_audit['inputs']['batch'],
                            'additions': add_audit['inputs']['batch']},
            'transitions': transitions,
            'scopeNote': 'One current candidate/review per exact articleUrl. '
                         'Hash-bound AI review claims, not human approval, '
                         'full article coverage or official 408 acceptance.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--add', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--audit-output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve()
        output = inside(root, str(args.output))
        audit_output = inside(root, str(args.audit_output))
        if output == audit_output:
            raise ValueError('output paths must differ')
        for path in (output, audit_output):
            if path.exists():
                raise ValueError('refusing to overwrite: ' + str(path))
        merged = merge(root, args.base, args.add, output.stem)
        # Prevent an output pathname from aliasing any existing input.
        for path in (output, audit_output):
            path.parent.mkdir(parents=True, exist_ok=True)
        with output.open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(merged, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        result = audit(root, output)
        if result['summary']['batchArticles'] != result['summary']['batchCandidateVersions']:
            raise ValueError('merged snapshot has duplicate article versions')
        with audit_output.open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        print(json.dumps({'summary': result['summary'],
                          'changes': len(merged['transitions']),
                          'humanApproval': False, 'full408Acceptance': False}, indent=2))
        return 0
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(json.dumps({'verified': False, 'error': str(exc)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
