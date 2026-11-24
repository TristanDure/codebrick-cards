"""Verify every recorded item and binding, not just the reported totals."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

try:
    from .build_disposition_ledger import ROOT, assemble, curated_proposal_files, curated_tool, inside, read
except ImportError:
    from build_disposition_ledger import ROOT, assemble, curated_proposal_files, curated_tool, inside, read


def verify(root: Path, ledger_path: Path) -> dict:
    root = root.resolve()
    ledger_path = ledger_path.resolve() if ledger_path.is_absolute() else inside(root, str(ledger_path))
    if root not in ledger_path.parents:
        raise ValueError('ledger path must be inside project')
    ledger, ledger_digest = read(ledger_path)
    if ledger.get('schemaVersion') != 2 or ledger.get('schema') != 'codebrick-corpus-disposition-ledger':
        raise ValueError('unsupported ledger schema')
    inputs = ledger['inputs']
    required_tools = ('build_disposition_ledger.py', 'audit_coverage.py', 'build_atomic_candidates.py',
                      'diagnose_empty_sections.py', 'import_curated_articles.py', 'sync_sources.py',
                      'co_pipeline_corrections.py', 'verify_disposition_ledger.py')
    expected_keys = {'articleManifest', 'preservedSourceLedger', 'cards', 'coverage.json',
                     'atomic-audit.json', 'empty-evidence.json'}
    expected_keys.update('tool:' + name for name in required_tools)
    manifest_doc = read(inside(root, inputs['articleManifest']['path']))[0]
    expected_keys.update('cache:' + article['url'] for article in manifest_doc['articles'])
    curated_files = curated_proposal_files(root)
    curated_rel = {path.relative_to(root).as_posix() for path in curated_files}
    audited_rel = {row.get('file') for row in ledger['candidateAudits']}
    if audited_rel != curated_rel or len(audited_rel) != len(ledger['candidateAudits']):
        raise ValueError('candidate audits do not exactly cover curated proposal files')
    expected_keys.update('candidate:' + path for path in curated_rel)
    if set(inputs) != expected_keys:
        raise ValueError('missing or unexpected required input bindings')
    canonical_paths = {'articleManifest': 'data/articles.json',
                       'preservedSourceLedger': 'data/knowledge-units.json',
                       'cards': 'data/cards/cards.json'}
    canonical_paths.update({name: (ledger_path.parent / name).relative_to(root).as_posix()
                            for name in ('coverage.json', 'atomic-audit.json', 'empty-evidence.json')})
    canonical_paths.update({'tool:' + name: 'scripts/' + name for name in required_tools})
    canonical_paths.update({'candidate:' + path: path for path in curated_rel})
    canonical_paths.update({'cache:' + article['url']: article['cache'] for article in manifest_doc['articles']})
    documents = {}
    for key, binding in inputs.items():
        if binding.get('path') != canonical_paths[key]:
            raise ValueError('non-canonical input binding path: ' + key)
        path = inside(root, binding['path'])
        if hashlib.sha256(path.read_bytes()).hexdigest() != binding['sha256']:
            raise ValueError('stale or mismatched input: ' + key)
        if key in ('articleManifest', 'preservedSourceLedger', 'coverage.json', 'atomic-audit.json', 'empty-evidence.json'):
            documents[key] = read(path)[0]
    empty_inputs = documents['empty-evidence.json']['inputFiles']
    if empty_inputs.get('coverage') != inputs.get('coverage.json'):
        raise ValueError('empty evidence is not bound to this exact coverage snapshot')
    if empty_inputs.get('articleManifest') != inputs.get('articleManifest'):
        raise ValueError('empty evidence article manifest binding mismatch')
    if empty_inputs.get('dispositionLedgerInputs') != {
            'cards': inputs['cards']['sha256'],
            'knowledgeUnits': inputs['preservedSourceLedger']['sha256'],
            'articleManifest': inputs['articleManifest']['sha256']}:
        raise ValueError('empty evidence source binding mismatch')
    articles = curated_tool
    article_map = articles._article_by_url(documents['articleManifest'])
    unit_map = articles._units_by_id(documents['preservedSourceLedger'])
    formal_ids = {card['id'] for card in read(inside(root, inputs['cards']['path']))[0]['cards']}
    candidate_documents = []
    for audit in ledger['candidateAudits']:
        rel = audit['file']
        bound = inputs.get('candidate:' + rel)
        if not bound or bound.get('path') != rel:
            raise ValueError('candidate audit lacks matching input binding: ' + rel)
        proposal, candidate_digest = read(inside(root, rel))
        if candidate_digest != bound['sha256'] or candidate_digest != audit.get('sha256'):
            raise ValueError('candidate proposal hash mismatch: ' + rel)
        validation = articles._validate_proposal(proposal, root=root, candidate_path=inside(root, rel),
            articles=article_map, ledger_by_id=unit_map, formal_card_ids=formal_ids)
        normalized, errors = articles._normalise_proposal(proposal, article_map)
        claims = [{'knowledgeUnitId': row.get('knowledgeUnitId'), 'action': row.get('disposition'),
                   'reason': row.get('reason', 'candidate card linkage claim; not semantic approval'),
                   'cardIds': row.get('cardIds', [])} for row in normalized.get('sourceUnits', [])]
        candidate_documents.append({'file': rel, 'sha256': candidate_digest,
            'articleUrl': normalized.get('article', {}).get('url'),
            'structuralOk': bool(validation['ok'] and not errors),
            'errors': validation['errors'] + errors,
            'authorKind': proposal.get('author', {}).get('kind', 'unknown'),
            'cardCount': len(normalized.get('cards', [])), 'unitDispositions': claims})
    # The assembly routine independently validates ID sets, memberships, text hashes,
    # per-unit audit records, exact empty-set coverage and non-approval boundaries.
    expected = assemble(root, documents['articleManifest'], documents['preservedSourceLedger'],
                        documents['coverage.json'], documents['atomic-audit.json'],
                        documents['empty-evidence.json'], candidate_documents, inputs)
    if set(ledger) != set(expected):
        raise ValueError('unknown or missing ledger fields')
    for key in ('scope', 'counts', 'articles', 'sections', 'sourceUnits', 'emptySections', 'candidateAudits'):
        if expected[key] != ledger[key]:
            raise ValueError('ledger item-level mismatch: ' + key)
    if (ledger.get('full408Acceptance') is not False or ledger.get('traceabilityComplete') is not True
            or ledger.get('approvalBoundary') != expected['approvalBoundary']
            or ledger.get('author') != expected['author'] or 'humanApprovals' in ledger):
        raise ValueError('incorrect acceptance boundary')
    if expected['counts']['unexplainedEmptySections']:
        raise ValueError('one or more empty chapters remain unexplained even on static extraction axis')
    return {'verified': True, 'sha256': ledger_digest, 'scope': expected['scope'],
            'humanApprovalsGenerated': 0, 'closedEmptyContentGaps': 0,
            'full408Acceptance': False}


def main(argv=None) -> int:
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--ledger', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(verify(args.root, args.ledger), indent=2))
        return 0
    except (ValueError, KeyError, OSError) as exc:
        print(json.dumps({'verified': False, 'error': str(exc)}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
