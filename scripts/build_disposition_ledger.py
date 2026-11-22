"""Offline item-level disposition and evidence accounting, never human approval.

Writes a new snapshot directory only. Original cards, review ledgers, source
caches and earlier snapshots are never overwritten. Empty evidence explanations
remain distinct from closing missing content or passing full 408 acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

try:
    from . import audit_coverage as coverage_tool, build_atomic_candidates as atomic_tool
    from . import diagnose_empty_sections as empty_tool, import_curated_articles as curated_tool
except ImportError:
    import audit_coverage as coverage_tool
    import build_atomic_candidates as atomic_tool
    import diagnose_empty_sections as empty_tool
    import import_curated_articles as curated_tool

ROOT = Path(__file__).resolve().parents[1]

EVIDENCE_ACTIONS = {
    'no-safe-atomic-recall-pattern': ('article-card-author', 'author-complete-atomic-question', 'A complete question naming the subject and assumptions, its answer, and a per-unit card/context/navigation/duplicate decision.'),
    'visual-or-formula-placeholder-needs-review': ('rich-content-reviewer', 'recover-source-visual-or-formula', 'Rendered source region or readable formula tied to this heading and source hash; verify variables, units and meaning.'),
    'table-row-unresolved-visual-content': ('table-and-diagram-reviewer', 'recover-table-row-cells', 'Complete row cells and column headers with rendered formula/diagram content before authoring a row card.'),
    'table-header-missing-or-insufficient': ('table-reviewer', 'recover-table-column-context', 'Correct table headers and row ownership; do not guess the missing column meanings.'),
    'table-row-column-count-mismatch-or-empty-cell': ('table-reviewer', 'resolve-row-column-alignment', 'An exact row/column alignment and explanations for genuinely empty cells or merged cells.'),
    'table-row-no-recallable-value': ('article-card-author', 'decide-table-row-context-or-card', 'A justified context/non-card disposition or a substantive value suitable for a question.'),
    'svg-diagram-or-formula-needs-review': ('rich-content-reviewer', 'read-rendered-svg', 'Rendered SVG and label/relationship transcription bound to the cached article region.'),
    'image-needs-visual-review': ('rich-content-reviewer', 'read-referenced-image', 'Readable image at recorded src with visual labels and its relationship to the article proposition.'),
    'link-target-needs-review': ('source-evidence-reviewer', 'verify-link-target-purpose', 'The recorded href target or evidence that this is navigation only; a practice index is not question content.'),
    'component-semantics-uncertain': ('interactive-content-reviewer', 'inspect-component-runtime', 'Rendered component states and payload showing this unit meaning and required interaction, not just skeleton text.'),
    'formula-format-unrecognized': ('formula-reviewer', 'recover-formula-syntax', 'Readable formula syntax with symbols, domain restrictions and units; no inferred missing operators.'),
    'preformatted-noncode-needs-review': ('code-or-diagram-reviewer', 'classify-preformatted-source', 'Evidence whether the block is an ASCII diagram, execution trace, formula or actual code plus a specific disposition.'),
    'code-context-missing': ('algorithm-card-author', 'supply-code-operation-contract', 'Operation purpose, inputs, outputs, preconditions and edge cases for the preserved literal code.'),
    'code-context-too-broad': ('algorithm-card-author', 'write-complete-local-code-prompt', 'A complete local coding task and preconditions without truncating long source prose.'),
    'known-source-factual-conflict': ('independent-fact-reviewer', 'bind-reviewed-erratum', 'Exact revised card hash with a non-author review addressing the known counterexample and model assumptions.'),
    'table-column-headers': ('table-reviewer', 'link-header-context-to-row-cards', 'Explicit linkage between this header and every row card using it, preserving column meanings.'),
    'table-row-with-column-context': ('independent-table-card-reviewer', 'review-row-against-complete-table', 'Compare each candidate answer to its exact row and all column headers; verify merged/empty cells, units and scope rather than accepting row text in isolation.'),
    'label-explanation': ('independent-card-reviewer', 'review-label-and-explanation-pair', 'Verify the question names the correct subject, the answer explains that label completely, and adjacent labels or clauses were not incorrectly joined.'),
    'is-definition': ('independent-card-reviewer', 'review-definition-subject-and-boundaries', 'Verify the defined subject, necessary qualifiers, distinguishing conditions and exceptions against this source unit; reject circular or truncated definitions.'),
    'definition': ('independent-card-reviewer', 'review-definition-subject-and-boundaries', 'Verify the defined subject, necessary qualifiers, distinguishing conditions and exceptions against this source unit; reject circular or truncated definitions.'),
    'formula-context-cloze': ('independent-formula-reviewer', 'review-formula-and-applicability', 'Compare the complete formula including operators, subscripts and denominators; verify variable definitions, units, domain and model assumptions in the candidate question and answer.'),
    'code-with-adjacent-prose-context': ('independent-algorithm-reviewer', 'review-code-against-operation-contract', 'Verify literal code and adjacent explanation implement the named operation under explicit inputs, outputs and preconditions; trace boundary cases and check stated time/space complexity.'),
    'properties': ('independent-card-reviewer', 'review-properties-and-qualifiers', 'Check that all claimed properties belong to the named object and retain their applicability conditions, exceptions and ordering if meaningful.'),
    'classification': ('independent-card-reviewer', 'review-classification-criterion-and-members', 'Check the classification criterion, complete category set and category boundaries; do not mix levels or treat examples as exhaustive classes.'),
    'causal-relation': ('independent-card-reviewer', 'review-cause-direction-and-conditions', 'Check cause/effect direction and necessary model conditions; distinguish implication from equivalence and correlation from mechanism.'),
    'mechanism': ('independent-card-reviewer', 'review-mechanism-sequence-and-boundaries', 'Verify the named mechanism, ordered state transitions, triggers, termination and exceptional paths rather than accepting a keyword-only explanation.'),
    'composition': ('independent-card-reviewer', 'review-composition-and-component-roles', 'Verify the whole being decomposed, the complete component set at this abstraction level and each component role; do not confuse composition with classification.'),
}


def unit_followups(unit: dict, reasons: list[str], has_candidates: bool) -> list[dict]:
    tasks = []
    for reason in reasons:
        if reason in EVIDENCE_ACTIONS:
            role, action, evidence = EVIDENCE_ACTIONS[reason]
        elif has_candidates:
            role, action, evidence = ('independent-card-reviewer', 'review-generated-card', 'A non-author review of the listed candidate question, answer, assumptions and source mapping; this is not an existing approval.')
        else:
            role, action, evidence = ('source-evidence-reviewer', 'resolve-specific-extraction-reason', 'Explicit unit disposition with evidence addressing reason ' + reason)
        tasks.append({'reason': reason, 'responsibleRole': role, 'action': action,
                      'missingEvidence': evidence, 'targetKnowledgeUnitId': unit['knowledgeUnitId'],
                      'targetArticleUrl': unit['articleUrl'], 'targetSectionIndex': unit['sectionIndex'],
                      'sourceTextSha256': unit['bodySha256'], 'href': unit.get('href', ''), 'src': unit.get('src', '')})
    return tasks


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read(path: Path):
    raw = path.read_bytes()
    return json.loads(raw.decode('utf-8')), sha(raw)


def inside(root: Path, value: str) -> Path:
    path = (root / value).resolve()
    if path == root or root not in path.parents:
        raise ValueError('path outside project: ' + str(value))
    return path


def unique(rows: list, key, label: str) -> dict:
    result = {}
    for row in rows:
        k = key(row)
        if k in result:
            raise ValueError('duplicate ' + label + ': ' + str(k))
        result[k] = row
    return result


def explain_empty(row: dict) -> tuple[str, str, str]:
    verified = row['cache']['contentHashMatches'] and row['parserSectionLocatorMatches']
    if not verified or row.get('directBodyBlockCount') != 0:
        return ('needs-evidence', 'cache-or-locator-recheck',
                'Cache, heading locator or zero-body claim is unverified; no absence conclusion is allowed.')
    direct_links = row.get('directPracticeQuestionLinkCount', 0)
    sub_links = row.get('subtreePracticeQuestionLinkCount', 0)
    siblings = row.get('sameLevelFollowingPracticeQuestionLinkCount', 0)
    markers = row.get('dynamicMarkerCount', 0) + row.get('dynamicSkeletonCount', 0) + row.get('iframeCount', 0)
    if markers:
        return ('explained-static-extraction-gap', 'capture-rendered-diagram-or-component',
                'Hash-verified heading interval contains dynamic/diagram markers (including Mermaid/iframe when present) instead of parser-captured semantic blocks. Static extraction omits runtime payload; rendered content and semantics remain unverified.')
    if sub_links or direct_links:
        return ('explained-heading-container', 'review-linked-question-body',
                f'Direct heading body has zero semantic blocks; descendant subtree has {sub_links} practice link(s) and direct interval has {direct_links}. The cached parent is an index container, not extracted question text. Child locators and link targets remain separately reviewable; no exam content approval is claimed.')
    if siblings:
        return ('explained-sibling-index-component', 'verify-sibling-component-and-question-body',
                f'Direct and descendant body are empty; next same-level related-question component has {siblings} practice link(s). Evidence explains the static heading boundary, but sibling links are not reassigned as this section content.')
    if row.get('subtreeBodyBlockCount', 0):
        return ('explained-heading-container', 'review-descendant-section-ownership',
                f'Direct body is empty while its descendant subtree contains {row["subtreeBodyBlockCount"]} semantic blocks. Parser uses direct heading ownership and assigns descendants to child sections; parent needs no invented units, and descendant content must still be reviewed.')
    return ('explained-static-absence-only', 'verify-source-omission-or-lazy-loading',
            'The hash-verified cached heading interval and subtree have zero semantic blocks and no identified component or practice link. This proves static absence only, not intentional emptiness, absence of an exam requirement, or successful content extraction; remote/source-author evidence is still required.')


def assemble(root: Path, articles_doc: dict, original_units: dict, coverage: dict,
             atomic: dict, empty: dict, candidate_documents: list, inputs: dict) -> dict:
    articles = unique(articles_doc['articles'], lambda a: a['url'], 'article URL')
    chapters = unique(coverage['sections'], lambda s: (s['articleUrl'], s['sectionIndex']), 'chapter locator')
    units = unique(coverage['knowledgeUnits'], lambda u: u['knowledgeUnitId'], 'source unit ID')
    original = unique(original_units['units'], lambda u: u['knowledgeUnitId'], 'original source unit ID')
    current_original = {k: u for k, u in original.items() if u.get('presentInCurrentSource') is True}
    if set(units) != set(current_original):
        raise ValueError('Current source-unit ID set differs from preserved source ledger; reconcile before producing M2 snapshot')
    if coverage.get('sourceParseFailures') or atomic.get('articleErrors'):
        raise ValueError('Source parse failures prevent full accounting')
    audit_by_unit = defaultdict(list)
    for entry in atomic['unitAudit']:
        audit_by_unit[entry['unitId']].append(entry)
    atomic_cards = defaultdict(list)
    for card in atomic['candidates']:
        atomic_cards[card['sourceUnitId']].append(card['id'])
    authored = defaultdict(list)
    authored_by_article = defaultdict(list)
    candidate_scoped_ids = set()
    for document in candidate_documents:
        authored_by_article[document['articleUrl']].append({k: document[k] for k in ('file', 'sha256', 'structuralOk', 'cardCount')})
        for decision in document['unitDispositions']:
            if document['structuralOk']:
                candidate_scoped_ids.add(decision['knowledgeUnitId'])
            authored[decision['knowledgeUnitId']].append({
                'file': document['file'], 'candidateSha256': document['sha256'],
                'structuralOk': document['structuralOk'], 'authorKind': document['authorKind'],
                'action': decision['action'], 'reason': decision['reason'], 'cardIds': decision['cardIds'],
                'semanticApproval': False,
            })
    unit_records = []
    for uid, u in units.items():
        if sha(u['text'].encode('utf-8')) != u['bodySha256'] or original[uid]['bodySha256'] != u['bodySha256']:
            raise ValueError('Source text hash mismatch: ' + uid)
        if {field: u.get(field) for field in coverage_tool.HUMAN_REVIEW_FIELDS} != {field: original[uid].get(field) for field in coverage_tool.HUMAN_REVIEW_FIELDS}:
            raise ValueError('Preserved human review state mismatch: ' + uid)
        key = (u['articleUrl'], u['sectionIndex'])
        if key not in chapters or u['articleUrl'] not in articles or uid not in chapters[key]['knowledgeUnitIds']:
            raise ValueError('Source unit lacks exact article/chapter membership: ' + uid)
        audits = audit_by_unit[uid]
        if not audits:
            raise ValueError('Source unit has no current atomic disposition: ' + uid)
        statuses = {a['status'] for a in audits}
        reasons = sorted({a['reason'] for a in audits})
        if 'known-source-factual-conflict' in reasons:
            action, next_action = 'conflict', 'Use scoped independently reviewed correction; do not learn the unqualified source assertion.'
        elif atomic_cards[uid] and 'backlog' in statuses:
            action, next_action = 'partial-candidate-needs-evidence', 'Review the candidate and separately resolve all listed backlog reasons.'
        elif atomic_cards[uid]:
            action, next_action = 'candidate-awaits-review', 'Review candidate question, answer, assumptions and 408 relevance; mapping alone is not approval.'
        elif 'table-column-headers' in reasons:
            action, next_action = 'context-awaits-linkage', 'Preserve column headers as table context; verify linkage to row cards, not a standalone knowledge card.'
        else:
            action, next_action = 'needs-evidence-or-authoring', 'Resolve listed extraction/atomicity reasons and choose card, context, duplicate, navigation or conflict with evidence.'
        claims = authored[uid]
        structurally_validated = any(claim['structuralOk'] for claim in claims)
        unit_records.append({
            'knowledgeUnitId': uid, 'sourceId': u['sourceId'], 'articleUrl': u['articleUrl'],
            'sectionIndex': u['sectionIndex'], 'headingPath': u['sectionHeadingPath'], 'anchor': u['sectionAnchor'],
            'blockIndex': u['blockIndex'], 'unitIndex': u['unitIndex'], 'tag': u['tag'],
            'sourceTextSha256': u['bodySha256'], 'reviewSourceSha256': u['reviewSourceSha256'],
            'sourcePreview': u['text'][:180], 'href': u.get('href', ''), 'src': u.get('src', ''),
            'disposition': action, 'reasons': reasons, 'nextAction': next_action,
            'explicitMachineDecision': 'needs-more-evidence' if not atomic_cards[uid] or 'backlog' in statuses else 'candidate-needs-independent-review',
            'evidenceTasks': unit_followups(u, reasons, bool(atomic_cards[uid])),
            'atomicCandidateIds': sorted(set(atomic_cards[uid])), 'legacyCandidateIds': u.get('cardIds', []),
            'authoredDispositionClaims': claims,
            'structurallyValidatedArticleCandidateDisposition': structurally_validated,
            'humanReview': {k: u[k] for k in coverage_tool.HUMAN_REVIEW_FIELDS if k in u},
            'humanApprovalGenerated': False, 'decisionOrigin': 'machine-evidence-accounting',
        })
    unit_records_by_id = {u['knowledgeUnitId']: u for u in unit_records}
    empty_map = unique(empty['records'], lambda e: (e['articleUrl'], e['sectionIndex']), 'empty chapter evidence')
    expected_empty = {k for k, s in chapters.items() if s['sourceBlockCount'] == 0}
    if expected_empty != set(empty_map):
        raise ValueError('Empty chapter evidence does not exactly cover current zero-extraction chapters')
    empty_records = []
    for key, e in empty_map.items():
        status, action, reason = explain_empty(e)
        role = 'source-evidence-reviewer'
        missing = 'Source-author or rendered live evidence establishing whether content is intentionally omitted or lazy-loaded; static absence is not proof of no required content.'
        if action == 'capture-rendered-diagram-or-component':
            role = 'interactive-content-reviewer'
            missing = 'Rendered diagram/component payload with readable labels and interactions, bound to this exact heading; static skeleton proves only omitted extraction.'
        elif action in ('review-linked-question-body', 'verify-sibling-component-and-question-body'):
            role = 'exam-evidence-reviewer'
            missing = 'Read the recorded question links or sibling component and preserve question/answer identity, provenance and scope; directory labels are not official exam content.'
        elif action == 'review-descendant-section-ownership':
            role = 'article-coverage-reviewer'
            missing = 'Confirm child section locators account for the descendant blocks and whether the parent is only a container; do not invent independent parent knowledge.'
        empty_records.append({
            'articleUrl': key[0], 'sectionIndex': key[1], 'headingPath': e['sectionLocator']['headingPath'],
            'anchor': e['sectionLocator']['anchor'], 'explanationStatus': status,
            'disposition': action, 'reason': reason,
            'evidenceSha256': sha(json.dumps(e, ensure_ascii=False, sort_keys=True).encode('utf-8')),
            'cacheRawHtmlSha256': e['cache']['rawHtmlSha256'],
            'cacheParsedContentSha256': e['cache']['parsedContentHash'],
            'cacheHashVerified': bool(e['cache']['contentHashMatches']),
            'sectionLocatorVerified': bool(e['parserSectionLocatorMatches']),
            'domEvidence': e['domEvidence'], 'practiceLinks': e['practiceQuestionLinks'],
            'sameLevelFollowingPracticeLinkCount': e.get('sameLevelFollowingPracticeQuestionLinkCount', 0),
            'staticExtractionExplained': status.startswith('explained-'),
            'responsibleRole': role, 'requiredEvidence': missing,
            'explicitMachineDecision': 'needs-more-evidence', 'contentResolutionStatus': 'unresolved',
            'contentGapClosed': False, 'contentApproved': False, 'humanApprovalGenerated': False,
        })
    empty_records_by_key = {(e['articleUrl'], e['sectionIndex']): e for e in empty_records}
    section_records = []
    for key, s in chapters.items():
        ids = s['knowledgeUnitIds']
        if len(ids) != len(set(ids)) or set(ids) != {u['knowledgeUnitId'] for u in units.values() if (u['articleUrl'], u['sectionIndex']) == key}:
            raise ValueError('Chapter unit membership mismatch: ' + str(key))
        counts = dict(Counter(unit_records_by_id[i]['disposition'] for i in ids))
        if s['sourceBlockCount'] == 0:
            if key in empty_records_by_key:
                decision = empty_records_by_key[key]['disposition']
                reason = empty_records_by_key[key]['reason']
            else:
                decision = 'empty-section-evidence-missing'
                reason = 'No zero-extraction DOM evidence record exists for this current chapter.'
        elif ids and all(unit_records_by_id[i]['structurallyValidatedArticleCandidateDisposition'] for i in ids):
            decision = 'curated-unit-dispositions-structurally-validated-review-pending'
            reason = f'All {len(ids)} source units have an explicit disposition in a structurally valid article candidate; this is not content approval.'
        else:
            decision = 'candidate-unit-dispositions-missing-or-invalid'
            reason = f'{sum(not unit_records_by_id[i]["structurallyValidatedArticleCandidateDisposition"] for i in ids)} of {len(ids)} source units lack an explicit disposition in a structurally valid article candidate.'
        section_records.append({
            'articleUrl': key[0], 'sectionIndex': key[1], 'headingPath': s['sectionHeadingPath'],
            'anchor': s['sectionAnchor'], 'sourceBlockCount': s['sourceBlockCount'],
            'knowledgeUnitIds': ids, 'unitDispositionCounts': counts, 'disposition': decision,
            'reason': reason, 'contentApproved': False, 'humanApprovalGenerated': False,
        })
    section_by_article = defaultdict(list)
    for s in section_records:
        section_by_article[s['articleUrl']].append(s)
    article_records = []
    for url, a in articles.items():
        ss = section_by_article[url]
        if not ss:
            raise ValueError('Article has no chapter disposition: ' + url)
        article_records.append({
            'sourceId': a['sourceId'], 'articleUrl': url, 'title': a['title'],
            'parsedContentSha256': a['contentHash'], 'cachePath': a['cache'],
            'sectionIndices': [s['sectionIndex'] for s in ss],
            'sourceUnitCount': sum(len(s['knowledgeUnitIds']) for s in ss),
            'emptySectionCount': sum(s['sourceBlockCount'] == 0 for s in ss),
            'candidateVersions': authored_by_article[url],
            'disposition': 'article-disposition-accounted-content-review-pending',
            'reason': f'{len(ss)} chapters and all their source units accounted individually; candidate claims and empty extraction explanations remain distinct from content approval.',
            'contentApproved': False, 'humanApprovalGenerated': False,
        })
    return {
        'schema': 'codebrick-corpus-disposition-ledger', 'schemaVersion': 2,
        'generatedAt': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'author': {'kind': 'machine', 'name': 'offline item-level evidence accountant'},
        'scope': {'articleCount': len(article_records), 'sectionCount': len(section_records),
                  'sourceUnitCount': len(unit_records), 'emptySectionCount': len(empty_records)},
        'inputs': inputs, 'approvalBoundary': 'Traceability and static-extraction explanations only. AI/candidate claims are not human approval, source semantic correctness, or full 408 acceptance.',
        'traceabilityComplete': True, 'full408Acceptance': False,
        'counts': {'unitDispositions': dict(Counter(u['disposition'] for u in unit_records)),
                   'unitReasons': dict(Counter(r for u in unit_records for r in u['reasons'])),
                   'emptyDispositions': dict(Counter(e['disposition'] for e in empty_records)),
                   'structurallyValidCuratedUnitDispositionCount': len(candidate_scoped_ids),
                   'unitsWithoutStructurallyValidCuratedDisposition': len(set(units) - candidate_scoped_ids),
                   'invalidCandidateArticleCount': sum(not c['structuralOk'] for c in candidate_documents),
                   'unexplainedEmptySections': sum(not e['staticExtractionExplained'] for e in empty_records),
                   'closedEmptyContentGaps': 0, 'humanApprovalsGenerated': 0},
        'articles': article_records, 'sections': section_records, 'sourceUnits': unit_records,
        'emptySections': empty_records, 'candidateAudits': candidate_documents,
    }


def build_ledger(root: Path) -> tuple[dict, dict, dict, dict]:
    root = root.resolve()
    stable_files = [root / 'data/articles.json', root / 'data/knowledge-units.json', root / 'data/cards/cards.json']
    stable_files.extend(sorted((root / 'data/curated').glob('*.json')))
    stable_files.extend(sorted((root / 'scripts').glob('*.py')))
    stable_files.extend(sorted((root / '.cache/html').rglob('*.html')))
    start_hashes = {p: sha(p.read_bytes()) for p in stable_files}
    articles_doc, ah = read(root / 'data/articles.json')
    units_doc, uh = read(root / 'data/knowledge-units.json')
    cards_doc, ch = read(root / 'data/cards/cards.json')
    original_root = coverage_tool.ROOT
    try:
        coverage_tool.ROOT = root
        coverage = coverage_tool.build_report()
    finally:
        coverage_tool.ROOT = original_root
    atomic = atomic_tool.build_candidate_set(root)
    empty = empty_tool.build_report(coverage, articles_doc, root / '.cache/html')
    empty['inputFiles'] = {'coverage': {'path': 'current in-memory coverage built from source cache', 'sha256': sha(json.dumps(coverage, ensure_ascii=False, indent=2).encode('utf-8'))},
                           'articleManifest': {'path': 'data/articles.json', 'sha256': ah}}
    articles = curated_tool._article_by_url(articles_doc)
    units = curated_tool._units_by_id(units_doc)
    formal_ids = {c['id'] for c in cards_doc['cards']}
    candidates = []
    for p in sorted((root / 'data/curated').glob('*.json')):
        proposal, digest = read(p)
        audit = curated_tool._validate_proposal(proposal, root=root, candidate_path=p,
            articles=articles, ledger_by_id=units, formal_card_ids=formal_ids)
        normalized, errors = curated_tool._normalise_proposal(proposal, articles)
        claims = []
        for row in normalized.get('sourceUnits', []):
            claims.append({'knowledgeUnitId': row.get('knowledgeUnitId'),
                           'action': row.get('disposition'), 'reason': row.get('reason', 'candidate card linkage claim; not semantic approval'),
                           'cardIds': row.get('cardIds', [])})
        candidates.append({'file': p.relative_to(root).as_posix(), 'sha256': digest,
            'articleUrl': normalized.get('article', {}).get('url'),
            'structuralOk': bool(audit['ok'] and not errors), 'errors': audit['errors'] + errors,
            'authorKind': proposal.get('author', {}).get('kind', 'unknown'),
            'cardCount': len(normalized.get('cards', [])), 'unitDispositions': claims})
    for url, a in articles.items():
        raw = inside(root, a['cache']).read_bytes()
        parsed = coverage_tool.parse_article(raw.decode('utf-8'), url)
        if sha(json.dumps(parsed['blocks'], ensure_ascii=False).encode('utf-8')) != a['contentHash']:
            raise ValueError('Manifest cache content hash mismatch: ' + url)
    inputs = {'articleManifest': {'path': 'data/articles.json', 'sha256': ah},
              'preservedSourceLedger': {'path': 'data/knowledge-units.json', 'sha256': uh},
              'cards': {'path': 'data/cards/cards.json', 'sha256': ch}}
    for name in ('build_disposition_ledger.py', 'audit_coverage.py', 'build_atomic_candidates.py',
                 'diagnose_empty_sections.py', 'import_curated_articles.py', 'sync_sources.py',
                 'co_pipeline_corrections.py', 'verify_disposition_ledger.py'):
        rel = 'scripts/' + name
        inputs['tool:' + name] = {'path': rel, 'sha256': sha((root / rel).read_bytes())}
    for url, a in articles.items():
        rel = a['cache']
        inputs['cache:' + url] = {'path': rel, 'sha256': sha(inside(root, rel).read_bytes())}
    for candidate in candidates:
        inputs['candidate:' + candidate['file']] = {'path': candidate['file'], 'sha256': candidate['sha256']}
    ledger = assemble(root, articles_doc, units_doc, coverage, atomic, empty, candidates, inputs)
    empty['inputFiles']['dispositionLedgerInputs'] = {'cards': ch, 'knowledgeUnits': uh, 'articleManifest': ah}
    if empty['inputFiles']['coverage']['sha256'] != sha(json.dumps(coverage, ensure_ascii=False, indent=2).encode('utf-8')):
        raise ValueError('Empty evidence report is not bound to the current coverage snapshot')
    if read(root / 'data/articles.json')[1] != ah or read(root / 'data/knowledge-units.json')[1] != uh or read(root / 'data/cards/cards.json')[1] != ch:
        raise ValueError('Inputs changed during build; retry against a stable snapshot')
    for path, digest in start_hashes.items():
        if sha(path.read_bytes()) != digest:
            raise ValueError('Source, candidate or tool changed during build: ' + str(path))
    return ledger, coverage, atomic, empty


def render_markdown(ledger: dict) -> str:
    lines = ['# M2 item-level disposition accounting', '', ledger['approvalBoundary'], '',
             'Scope: ' + json.dumps(ledger['scope']), '', '## Empty extraction explanations', '',
             '| Article / section | Static explanation | Follow-up | Reason |', '|---|---|---|---|']
    for row in ledger['emptySections']:
        clean = lambda value: str(value).replace('|', '\\|').replace('\n', ' ')
        lines.append('| ' + ' | '.join(clean(v) for v in [row['articleUrl'] + '#' + row['anchor'] + ' [' + str(row['sectionIndex']) + ']', row['explanationStatus'], row['disposition'], row['reason']]) + ' |')
    lines += ['', '## Unit counts', '', json.dumps(ledger['counts'], ensure_ascii=False, indent=2), '',
              'No source ledger, personal study data, human decision or historical card was deleted or approved.']
    return '\n'.join(lines) + '\n'


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--output-dir', required=True, type=Path, help='New directory inside project; existing directory is refused')
    args = parser.parse_args(argv)
    root = args.root.resolve()
    output = (root / args.output_dir).resolve() if not args.output_dir.is_absolute() else args.output_dir.resolve()
    if output == root or root not in output.parents or output.exists():
        parser.error('output must be a NEW directory inside project')
    ledger, coverage, atomic, empty = build_ledger(root)
    output.mkdir(parents=True, exist_ok=False)
    coverage_raw = (json.dumps(coverage, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    empty['inputFiles']['coverage'] = {'path': (output / 'coverage.json').relative_to(root).as_posix(), 'sha256': sha(coverage_raw)}
    empty['inputFiles']['articleManifest'] = ledger['inputs']['articleManifest']
    for name, doc in [('coverage.json', coverage), ('atomic-audit.json', atomic), ('empty-evidence.json', empty)]:
        raw = (json.dumps(doc, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        (output / name).write_bytes(raw)
        ledger['inputs'][name] = {'path': (output / name).relative_to(root).as_posix(), 'sha256': sha(raw)}
    raw = (json.dumps(ledger, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    (output / 'ledger.json').write_bytes(raw)
    (output / 'ledger.md').write_text(render_markdown(ledger), encoding='utf-8')
    print(json.dumps({'scope': ledger['scope'], 'counts': ledger['counts'], 'sha256': sha(raw), 'snapshot': str(output)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
