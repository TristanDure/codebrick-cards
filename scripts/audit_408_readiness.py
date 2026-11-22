"""Offline structural audit of 408-study data; this does not certify readiness."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
INPUTS = {
    "articles": Path("data/articles.json"),
    "cards": Path("data/cards/cards.json"),
    "coverage": Path("data/reports/coverage.json"),
    "knowledgeUnits": Path("data/knowledge-units.json"),
    "408Baseline": Path("data/exam/baseline-408.json"),
}
REPORT_JSON = Path("data/reports/408-readiness.json")
REPORT_MARKDOWN = Path("data/reports/408-readiness.md")
GENERIC_PROMPT = re.compile(
    r"^(?:"
    r"回忆「.+」的核心定义、机制与易错点。|"
    r"请解释「.+」本部分的关键概念、条件、过程与结论。"
    r")(?:（第\s*\d+\s*/\s*\d+\s*部分）)?$"
)

PLACEHOLDER = re.compile(
    r"\b(?:TODO|TBD|PLACEHOLDER|FIXME)\b|待补|占位|待填写|未提取|原文内容未能可靠提取",
    re.IGNORECASE,
)
MARKERS = {
    "svg": re.compile(r"<svg\b|\bsvg\b|【SVG[^】]*】|\[SVG[^\]]*\]", re.I),
    "image": re.compile(r"<img\b|!\[[^\]]*\]\s*\(|\[(?:图示|图片)[^\]]*\]|【(?:图示|图片)[^】]*】|\bimage\b", re.I),
    "table": re.compile(r"<table\b|【表格[^】]*】|\[表格[^\]]*\]|\|[^\n|]+\|[^\n]+", re.I),
    "code": re.compile(r"```|<code\b|<pre\b|【代码[^】]*】|\b代码\b|\bcode\b", re.I),
}
TEXT_FIELDS = (
    "question", "generatedQuestion", "suggestedQuestion", "answer",
    "generatedAnswer", "suggestedAnswer", "evidence", "previousAnswer",
)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read valid JSON from {path}: {exc}") from exc


def _rows(document: Any, key: str, path: Path) -> list[dict[str, Any]]:
    value = document.get(key) if isinstance(document, dict) else None
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError(f"{path} must contain a list of objects at {key!r}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _card_text(card: dict[str, Any]) -> str:
    return "\n".join(str(card.get(field) or "") for field in TEXT_FIELDS)


def build_report(root: Path | None = None, *, generated_at: datetime | None = None) -> dict[str, Any]:
    """Summarize local datasets. An explicit root supports isolated fixture tests."""
    root = Path(root) if root is not None else ROOT
    paths = {key: root / rel for key, rel in INPUTS.items()}
    articles = _rows(_read_json(paths["articles"]), "articles", paths["articles"])
    cards = _rows(_read_json(paths["cards"]), "cards", paths["cards"])
    coverage = _read_json(paths["coverage"])
    unit_path = paths["knowledgeUnits"]
    knowledge_ledger = _read_json(unit_path) if unit_path.is_file() else {}
    baseline_path = paths["408Baseline"]
    baseline = _read_json(baseline_path) if baseline_path.is_file() else {}
    if not isinstance(knowledge_ledger, dict):
        raise ValueError("knowledge-units.json must contain a JSON object")
    if not isinstance(baseline, dict):
        raise ValueError("baseline-408.json must contain a JSON object")
    if not isinstance(coverage, dict):
        raise ValueError("coverage.json must contain a JSON object")
    by_source = coverage.get("bySource", {})
    sections = coverage.get("sections", [])
    if not isinstance(by_source, dict) or not isinstance(sections, list):
        raise ValueError("coverage.json must contain object 'bySource' and list 'sections'")

    article_counts = Counter(str(row.get("sourceId") or "unknown") for row in articles)
    cards_by_source: dict[str, list[dict[str, Any]]] = {}
    for card in cards:
        cards_by_source.setdefault(str(card.get("sourceId") or "unknown"), []).append(card)
    subjects: dict[str, Any] = {}
    for sid in sorted(set(by_source) | set(article_counts) | set(cards_by_source)):
        source = by_source.get(sid, {})
        source = source if isinstance(source, dict) else {}
        group = cards_by_source.get(sid, [])
        mapped = sum(
            isinstance(row, dict) and str(row.get("sourceId") or "unknown") == sid
            and isinstance(row.get("cardCount"), int) and row["cardCount"] > 0
            for row in sections
        )
        historical_count = sum(bool(c.get("sourceSectionRemoved") or c.get("sourceArticleMissing")) for c in group)
        subjects[sid] = {
            "name": source.get("name") or sid,
            "articleCount": article_counts[sid],
            "coverageArticleCount": source.get("articleCount", 0),
            "chapterCount": source.get("sectionCount", 0),
            "mappedChapterCount": mapped,
            "coverageCardAssociationCount": source.get("cardCount", 0),
            "cardRecordCount": len(group),
            "activeCardRecordCount": len(group) - historical_count,
            "historicalCardRecordCount": historical_count,
            "sectionStatusCounts": dict(sorted((source.get("statusCounts") or {}).items())),
            "cardStatusCounts": dict(sorted(Counter(str(c.get("status") or "(missing)") for c in group if not (c.get("sourceSectionRemoved") or c.get("sourceArticleMissing"))).items())),
            "reviewReasonCounts": dict(sorted(Counter(str(c.get("reviewReason") or "(none)") for c in group if not (c.get("sourceSectionRemoved") or c.get("sourceArticleMissing"))).items())),
        }

    historical_cards = [c for c in cards if c.get("sourceSectionRemoved") or c.get("sourceArticleMissing")]
    active_cards = [c for c in cards if not (c.get("sourceSectionRemoved") or c.get("sourceArticleMissing"))]
    status_counts = Counter(str(c.get("status") or "(missing)") for c in active_cards)
    reason_counts = Counter(str(c.get("reviewReason") or "(none)") for c in active_cards)
    generic = [c for c in active_cards if GENERIC_PROMPT.fullmatch(str(c.get("question") or ""))]
    prompt_counts = Counter(str(c.get("question") or "") for c in generic)
    placeholder = [c for c in active_cards if PLACEHOLDER.search(_card_text(c))]
    extraction_reason = sum(c.get("reviewReason") == "source-extraction-incomplete" for c in active_cards)
    extraction_text = sum("原文内容未能可靠提取" in _card_text(c) for c in active_cards)
    marker_counts = {
        key: sum(bool(pattern.search(_card_text(card))) for card in active_cards)
        for key, pattern in MARKERS.items()
    }
    knowledge_units = coverage.get("knowledgeUnits", [])
    if not isinstance(knowledge_units, list):
        knowledge_units = []
    unit_status_counts = Counter(str(row.get("status") or "(missing)") for row in knowledge_units if isinstance(row, dict))
    human_review_counts = Counter(str(row.get("reviewerDecision") or "pending") for row in knowledge_units if isinstance(row, dict))
    retired_units = [row for row in knowledge_ledger.get("units", []) if isinstance(row, dict) and row.get("presentInCurrentSource") is False]
    baseline_candidates = (
        root / "data/baselines/408-syllabus.json",
        root / "data/baselines/408-syllabus.md",
        root / "data/syllabus/408.md",
    )
    baselines = [p.relative_to(root).as_posix() for p in baseline_candidates if p.is_file()]
    now = generated_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc).replace(microsecond=0)
    return {
        "schemaVersion": 1,
        "generatedAt": now.isoformat().replace("+00:00", "Z"),
        "scope": "offline structural inventory; not a syllabus, correctness, or exam-readiness certification",
        "snapshot": {
            "hashAlgorithm": "sha256",
            "inputs": {
                key: {"path": rel.as_posix(), "sha256": _sha256(paths[key]), "bytes": paths[key].stat().st_size}
                for key, rel in INPUTS.items() if paths[key].is_file()
            },
        },
        "inventory": {
            "articleRecordCount": len(articles), "cardRecordCount": len(cards),
            "activeCardRecordCount": len(active_cards), "historicalCardRecordCount": len(historical_cards),
            "coverageSectionRecordCount": len(sections), "subjects": subjects,
        },
        "sourceSectionMapping": {
            "articleCount": coverage.get("sourceArticleCount", len(articles)),
            "parsedArticleCount": coverage.get("parsedArticleCount", 0),
            "chapterCount": coverage.get("sectionCount", len(sections)),
            "mappedChapterCount": coverage.get("coverageCount", 0),
            "missingCardChapterCount": coverage.get("missingCardCount", 0),
            "extractionReviewChapterCount": coverage.get("extractionReviewCount", 0),
            "orphanCardCount": coverage.get("orphanCardCount", 0),
            "duplicateCardIdCount": len(coverage.get("duplicateCardIds", [])),
            "ambiguousMappingCount": len(coverage.get("ambiguousCardMappings", [])),
            "sourceParseFailureCount": len(coverage.get("sourceParseFailures", [])),
            "sourceUnitCandidateCount": len(knowledge_units),
            "sourceUnitMappedToCandidateCardCount": sum(bool(row.get("cardIds")) for row in knowledge_units if isinstance(row, dict)),
            "sourceUnitStatusCounts": dict(sorted(unit_status_counts.items())),
            "humanReviewedKnowledgeUnitCount": human_review_counts["accepted"],
            "humanAcceptedKnowledgeUnitCount": human_review_counts["accepted"],
            "humanRejectedKnowledgeUnitCount": human_review_counts["rejected"],
            "humanPendingKnowledgeUnitCount": sum(human_review_counts[state] for state in ("pending", "needs-more-evidence")),
            "staleHumanReviewCount": human_review_counts["stale"],
            "retiredSourceUnitCount": len(retired_units),
            "interpretation": "A mapped chapter means coverage.json associates a current card record with a parsed source section. A source unit is a machine-extracted source fragment, not a human-verified exam knowledge point; neither mapping establishes official 408 syllabus coverage, correctness, adequate question design, or exam readiness.",
        },
        "cards": {
            "statusCounts": dict(sorted(status_counts.items())),
            "reviewReasonCounts": dict(sorted(reason_counts.items())),
            "genericTemplatePrompts": {
                "pattern": "回忆「…」的核心定义、机制与易错点。 or 请解释「…」本部分的关键概念、条件、过程与结论。 (optional multipart suffix)",
                "cardCount": len(generic), "distinctPromptCount": len(prompt_counts),
                "mostFrequentPrompts": [
                    {"prompt": prompt, "cardCount": count}
                    for prompt, count in prompt_counts.most_common(10)
                ],
            },
            "extractionPlaceholders": {
                "cardCount": len(placeholder), "extractionReviewReasonCardCount": extraction_reason,
                "explicitUnreliableExtractionTextCardCount": extraction_text,
                "detection": "text/review-reason heuristic; counts are card records, not unique sections",
            },
            "longAndMultipart": {
                "thresholds": {"longAnswerCharactersInclusive": 1000, "longQuestionCharactersInclusive": 200, "multipartPartCountGreaterThan": 1},
                "longAnswerCardCount": sum(len(str(c.get("answer") or "")) >= 1000 for c in cards),
                "longQuestionCardCount": sum(len(str(c.get("question") or "")) >= 200 for c in cards),
                "multipartCardCount": sum(isinstance(c.get("partCount"), int) and not isinstance(c.get("partCount"), bool) and c["partCount"] > 1 for c in cards),
            },
            "renderingMarkers": {
                "cardCountsByMarker": marker_counts,
                "interpretation": "Lexical/markup markers only; no renderer execution or visual fidelity check was performed.",
            },
        },
        "officialSyllabusBaseline": {
            "status": (
                "limited_reference_present_official_syllabus_body_not_reviewed"
                if baseline_path.is_file() and baseline.get("claimBoundaries", {}).get("officialAnnualSyllabusFullTextReviewed") is False
                else "baseline_file_present_scope_requires_validation" if baseline_path.is_file()
                else "missing"
            ),
            "targetExamYear": baseline.get("targetExamYear"),
            "baselineId": baseline.get("baselineId"),
            "officialSyllabusCatalogRecord": baseline.get("annualSyllabus", {}).get("officialPublisherCatalogRecord") if isinstance(baseline.get("annualSyllabus"), dict) else None,
            "officialSyllabusFullTextReviewed": baseline.get("claimBoundaries", {}).get("officialAnnualSyllabusFullTextReviewed", False),
            "referenceTopicTreeIsOfficialAnnualSyllabus": baseline.get("claimBoundaries", {}).get("frameworkBelowIsOfficial2027Syllabus", False),
            "baselineFilePath": baseline_path.relative_to(root).as_posix() if baseline_path.is_file() else None,
            "foundPaths": [p.relative_to(root).as_posix() for p in baseline_candidates if p.is_file()],
            "expectedPathsChecked": [p.relative_to(root).as_posix() for p in baseline_candidates],
        },
        "verdict": {
            "status": "not_demonstrated; human review required",
            "summary": "The snapshot shows source-section-to-card traceability, but does not demonstrate complete or accurate 408 coverage. Do not treat every card as exam-ready.",
            "humanReviewRequired": True,
            "evidenceBoundaryAndNextStep": "A limited 2027 baseline/reference file is present, but its own claim boundary says the official annual syllabus full text was not reviewed; its publisher topic tree is reference-only. There is no completed official-syllabus-item-to-reviewed-card mapping or primary past-paper audit.",
            "actionPriorities": [
                "Obtain and independently review the official syllabus body for the target year; map every clause to a human-reviewed knowledge point, source evidence, and card.",
                "Audit primary past papers across years and subjects; record source, year, question, and independently checked solution links.",
                "Resolve extraction-incomplete placeholders against original sources before using affected cards for study.",
                "Replace or enrich generic recall prompts with independently reviewed, discriminative questions and checked answers.",
                "Visually and semantically verify SVG, image, table, and code-bearing cards in the actual app renderer.",
                "Review every source unit as a discovery aid, then maintain a separate human knowledge-point ledger and trace each accepted point to cards or an evidence-backed no-card decision.",
                "Repeat the structural audit after data refreshes and compare input hashes; keep human quality review separate.",
            ],
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    inv, mapping, cards, verdict = report["inventory"], report["sourceSectionMapping"], report["cards"], report["verdict"]
    lines = [
        "# 408 Readiness Structural Audit", "", f"- Generated (UTC): {report['generatedAt']}",
        f"- Scope: {report['scope']}", "- Snapshot: SHA-256 of local input datasets (hashes below).",
        "", "## Responsible verdict", "", f"**{verdict['status']}** — {verdict['summary']}",
        "", "This structural inventory is not an exam-readiness certification. A mapped source section only means a card record is associated with that section; it does not mean the section is in the official 408 syllabus or that a card is correct, sufficient, or exam-ready.",
        "", "## Inventory and source-section mapping", "",
        f"- Article records: {inv['articleRecordCount']}", f"- Card records: {inv['cardRecordCount']}",
        f"- Coverage section records: {inv['coverageSectionRecordCount']}",
        f"- Parsed articles: {mapping['parsedArticleCount']} / {mapping['articleCount']}",
        f"- Source sections mapped to at least one current card: {mapping['mappedChapterCount']} / {mapping['chapterCount']}",
        f"- Machine-extracted source fragments: {mapping['sourceUnitMappedToCandidateCardCount']} / {mapping['sourceUnitCandidateCount']} associated with candidate cards; human-accepted units: {mapping['humanAcceptedKnowledgeUnitCount']}; rejected: {mapping['humanRejectedKnowledgeUnitCount']}; pending: {mapping['humanPendingKnowledgeUnitCount']}; stale: {mapping['staleHumanReviewCount']}",
        f"- Missing-card sections: {mapping['missingCardChapterCount']}; extraction-review sections: {mapping['extractionReviewChapterCount']}",
        f"- Orphan cards: {mapping['orphanCardCount']}; duplicate IDs: {mapping['duplicateCardIdCount']}; ambiguous mappings: {mapping['ambiguousMappingCount']}; parse failures: {mapping['sourceParseFailureCount']}",
        "", "| Subject | Articles (data / coverage) | Chapters | Mapped chapters | Cards (records / associations) |", "|---|---:|---:|---:|---:|",
    ]
    for sid, subject in inv["subjects"].items():
        lines.append(f"| {subject['name']} (`{sid}`) | {subject['articleCount']} / {subject['coverageArticleCount']} | {subject['chapterCount']} | {subject['mappedChapterCount']} | {subject['cardRecordCount']} / {subject['coverageCardAssociationCount']} |")
    lines.extend(["", "## Card structure and review flags", "", "### Card statuses", ""])
    lines.extend(f"- `{key}`: {count}" for key, count in cards["statusCounts"].items())
    lines.extend(["", "### Review reasons", ""])
    lines.extend(f"- `{key}`: {count}" for key, count in cards["reviewReasonCounts"].items())
    prompt, extraction, lengths = cards["genericTemplatePrompts"], cards["extractionPlaceholders"], cards["longAndMultipart"]
    lines.extend([
        "", "### Structural flags (heuristics, not quality scores)", "",
        f"- Generic template-pattern prompts: {prompt['cardCount']} cards / {prompt['distinctPromptCount']} distinct prompts.",
        f"- Extraction-placeholder matches: {extraction['cardCount']}; extraction review reason: {extraction['extractionReviewReasonCardCount']}; explicit unreliable-extraction text: {extraction['explicitUnreliableExtractionTextCardCount']}.",
        f"- Long answers (≥{lengths['thresholds']['longAnswerCharactersInclusive']} chars): {lengths['longAnswerCardCount']}; long questions (≥{lengths['thresholds']['longQuestionCharactersInclusive']} chars): {lengths['longQuestionCardCount']}; multipart cards: {lengths['multipartCardCount']}.",
        "- Rendering marker cards: " + ", ".join(f"{k} {v}" for k, v in cards["renderingMarkers"]["cardCountsByMarker"].items()) + ". Text/markup detection only; rendering was not validated.",
        "", "#### Most frequent generic prompts", "", "| Prompt | Cards |", "|---|---:|",
    ])
    for row in prompt["mostFrequentPrompts"]:
        escaped_prompt = row["prompt"].replace("|", "\\|")
        lines.append(f"| {escaped_prompt} | {row['cardCount']} |")
    syllabus = report["officialSyllabusBaseline"]
    lines.extend([
        "", "## Evidence boundary and next steps", "",
        f"- Official year-specific syllabus baseline: **{syllabus['status']}**.",
        f"- {verdict['evidenceBoundaryAndNextStep']}", "", "### Priorities", "",
    ])
    lines.extend(f"{i}. {action}" for i, action in enumerate(verdict["actionPriorities"], 1))
    lines.extend(["", "## Snapshot hashes", "", "| Input | Bytes | SHA-256 |", "|---|---:|---|"])
    for item in report["snapshot"]["inputs"].values():
        lines.append(f"| `{item['path']}` | {item['bytes']} | `{item['sha256']}` |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="project root containing data/")
    args = parser.parse_args(argv)
    report = build_report(args.root)
    (args.root / REPORT_JSON).parent.mkdir(parents=True, exist_ok=True)
    (args.root / REPORT_JSON).write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (args.root / REPORT_MARKDOWN).write_text(render_markdown(report), encoding="utf-8")
    print(f"408 readiness: {report['inventory']['cardRecordCount']} cards; {report['sourceSectionMapping']['mappedChapterCount']}/{report['sourceSectionMapping']['chapterCount']} source sections mapped; {report['verdict']['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


