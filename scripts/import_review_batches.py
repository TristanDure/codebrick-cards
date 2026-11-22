from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

try:
    from .sync_sources import ROOT, parse_article, sections
except ImportError:  # direct invocation
    from sync_sources import ROOT, parse_article, sections

BATCH_DIR = Path("data/review-batches")
CARDS_PATH = Path("data/cards/cards.json")
ARTICLES_PATH = Path("data/articles.json")
UNITS_PATH = Path("data/knowledge-units.json")
REVIEW_REASON = "human-content-and-408-review-required"
GENERIC_QUESTIONS = (
    "请解释", "回忆「"
)


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _norm_evidence(value: str) -> str:
    # Ignore whitespace/punctuation and the parser's explicit math/media markers.
    import re
    value = re.sub(r"\[(?:SVG[^\]]*|公式[^\]]*)\]", "", value, flags=re.I)
    return "".join(ch.casefold() for ch in value if ch.isalnum())


def _stable_card_id(row: dict) -> str:
    key = json.dumps([
        row["sourceId"], row["articleUrl"], row["sectionIndex"], row["sectionAnchor"],
        sorted(row["sourceKnowledgeUnitIds"]), row["question"].strip(),
    ], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(("codebrick-review-batch-v1:" + key).encode("utf-8")).hexdigest()[:16]


def _load_snapshot(root: Path):
    article_doc = _read_json(root / ARTICLES_PATH)
    unit_doc = _read_json(root / UNITS_PATH)
    articles = article_doc.get("articles") if isinstance(article_doc, dict) else None
    units = unit_doc.get("units") if isinstance(unit_doc, dict) else None
    if not isinstance(articles, list) or not isinstance(units, list):
        raise ValueError("article inventory and knowledge-unit ledger must contain arrays")
    by_url = {}
    for article in articles:
        if not isinstance(article, dict) or not isinstance(article.get("url"), str) or not article["url"].strip():
            raise ValueError("article inventory contains a malformed record")
        url = article["url"].split("#", 1)[0]
        if url in by_url:
            raise ValueError(f"duplicate article URL in inventory: {url}")
        by_url[url] = article
    units_by_id = {}
    for unit in units:
        if not isinstance(unit, dict):
            raise ValueError("knowledge-unit ledger contains a malformed record")
        unit_id = unit.get("knowledgeUnitId")
        if not isinstance(unit_id, str) or not unit_id:
            raise ValueError("knowledge-unit ledger contains a record without an ID")
        if unit_id in units_by_id:
            raise ValueError(f"duplicate knowledge-unit ID in ledger: {unit_id}")
        units_by_id[unit_id] = unit
    return articles, by_url, units_by_id


def _parse_article_sections(root: Path, article: dict, cache_by_url: dict):
    url = str(article.get("url", "")).split("#", 1)[0]
    if url not in cache_by_url:
        cache = (root / str(article.get("cache", ""))).resolve()
        if root.resolve() not in cache.parents or not cache.is_file():
            raise ValueError(f"article cache missing/outside project: {article.get('cache')}")
        parsed = parse_article(cache.read_text(encoding="utf-8"), url)
        cache_by_url[url] = sections(parsed)
    return cache_by_url[url]


def _validate_row(row, *, root: Path, units_by_id: dict, article_by_url: dict, parsed_sections: dict):
    errors = []
    if not isinstance(row, dict):
        return None, ["row must be an object"]
    source_id = row.get("sourceId")
    article_url = str(row.get("articleUrl", "")).split("#", 1)[0]
    ids = row.get("sourceKnowledgeUnitIds")
    question = row.get("question")
    answer = row.get("answer")
    evidence = row.get("evidence")
    if row.get("status") != "needs-review": errors.append("status must remain needs-review")
    if not isinstance(source_id, str) or source_id not in {"os", "co", "cn", "ds"}: errors.append("invalid sourceId")
    if not isinstance(article_url, str) or article_url not in article_by_url: errors.append("articleUrl is not in current local article inventory")
    if not isinstance(ids, list) or not ids or any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids): errors.append("sourceKnowledgeUnitIds must be a non-empty unique string list")
    if not isinstance(question, str) or len(question.strip()) < 5 or question.strip().startswith(GENERIC_QUESTIONS): errors.append("question is empty or a generic template")
    if not isinstance(answer, str) or len(answer.strip()) < 2: errors.append("answer is empty")
    evidence_cache = None
    if not isinstance(evidence, dict) or not all(isinstance(evidence.get(k), str) and evidence[k].strip() for k in ("excerpt", "locator", "cachePath")):
        errors.append("evidence needs excerpt, locator, and cachePath")
    else:
        raw_cache_path = Path(evidence["cachePath"])
        if raw_cache_path.is_absolute() or ".." in raw_cache_path.parts:
            errors.append("evidence cachePath must be project-relative")
        else:
            evidence_cache = (root / raw_cache_path).resolve()
            if root.resolve() not in evidence_cache.parents or not evidence_cache.is_file():
                errors.append("evidence cachePath must resolve to a file inside the project")
    try:
        section_index = row.get("sectionIndex")
        section_anchor = row.get("sectionAnchor")
        if not isinstance(section_index, int) or isinstance(section_index, bool) or section_index < 1: errors.append("invalid sectionIndex")
        if not isinstance(section_anchor, str): errors.append("invalid sectionAnchor")
    except Exception:
        errors.append("invalid section locator")
    if errors:
        return None, errors

    article = article_by_url[article_url]
    if source_id != article.get("sourceId"): errors.append("sourceId disagrees with article inventory")
    article_cache = (root / str(article.get("cache", ""))).resolve()
    if root.resolve() not in article_cache.parents or not article_cache.is_file():
        errors.append("article cache must resolve to a file inside the project")
    elif evidence_cache != article_cache:
        errors.append("evidence cachePath does not match the article cache")
    cache_by_url = parsed_sections
    try:
        article_sections = _parse_article_sections(root, article, cache_by_url)
        if section_index > len(article_sections):
            errors.append("sectionIndex is outside parsed source article")
            section = None
        else:
            section = article_sections[section_index - 1]
            if section.get("anchor", "") != section_anchor: errors.append("sectionAnchor disagrees with parsed source article")
    except Exception as exc:
        errors.append(f"article parse failed: {type(exc).__name__}: {exc}")
        section = None
    source_units = []
    for unit_id in ids:
        unit = units_by_id.get(unit_id)
        if not unit:
            errors.append(f"unknown source knowledge unit: {unit_id}")
            continue
        if unit.get("sourceId") != source_id: errors.append(f"{unit_id}: subject mismatch")
        if str(unit.get("articleUrl", "")).split("#", 1)[0] != article_url: errors.append(f"{unit_id}: article mismatch")
        if unit.get("sectionIndex") != section_index or unit.get("sectionAnchor", "") != section_anchor: errors.append(f"{unit_id}: section locator mismatch")
        if not str(unit.get("text", "")).strip(): errors.append(f"{unit_id}: source text is empty")
        source_units.append(unit)
    if errors:
        return None, errors

    proposed_excerpt = evidence["excerpt"].strip()
    normalized_excerpt = _norm_evidence(proposed_excerpt)
    all_unit_text = " ".join(str(unit.get("text", "")) for unit in source_units)
    exact_evidence = bool(normalized_excerpt and normalized_excerpt in _norm_evidence(all_unit_text))
    # Always retain exact source-unit text as the review evidence. A proposal's
    # paraphrase/markup variant is separate and explicitly flagged for human check.
    exact_source_excerpt = "\n\n".join(str(unit["text"]).strip() for unit in source_units)
    cache_relative = evidence["cachePath"].replace("\\", "/")
    article_title = str(article.get("title", ""))
    heading = str(section.get("heading", "")) if section else ""
    source_hash = str(article.get("contentHash", ""))
    card_id = _stable_card_id(row)
    flags = ["candidate-proposal-unreviewed"]
    if not exact_evidence:
        flags.append("proposal-excerpt-not-verbatim-source")
    card = {
        "id": card_id,
        "sourceId": source_id,
        "articleTitle": article_title,
        "articleUrl": article_url + (f"#{section_anchor}" if section_anchor else ""),
        "section": heading,
        "sectionHeadingPath": str(source_units[0].get("sectionHeadingPath", heading)),
        "sectionAnchor": section_anchor,
        "sectionIndex": section_index,
        "knowledgeUnitIds": list(ids),
        "question": question.strip(),
        "answer": answer.strip(),
        "evidence": f"原文知识单元摘录：\n{exact_source_excerpt}\n\n定位：{evidence['locator'].strip()}\n缓存：{cache_relative}",
        "provenance": {
            "articleUrl": article_url,
            "sectionAnchor": section_anchor,
            "sectionIndex": section_index,
            "knowledgeUnitIds": list(ids),
            "sourceHash": source_hash,
            "verificationStatus": "not-reviewed",
            "sourceExcerpt": exact_source_excerpt,
            "candidateEvidenceExcerpt": proposed_excerpt,
            "evidenceExcerptMatchesSource": exact_evidence,
            "cachePath": cache_relative,
            "examRelevanceRationale": str(row.get("examRelevanceRationale", "")),
            "reviewBatch": "data/review-batches",
        },
        "tags": list(row.get("tags", [])) if isinstance(row.get("tags"), list) else [],
        "examPoints": [],
        "auditFlags": flags,
        "status": "needs-review",
        "reviewReason": REVIEW_REASON,
        "origin": "review-batch-candidate",
    }
    return card, []


def plan_import(root: Path | None = None, batch_paths=None):
    root = (root or ROOT).resolve()
    articles, article_by_url, units_by_id = _load_snapshot(root)
    cache_by_url = {}
    paths = sorted(batch_paths if batch_paths is not None else (root / BATCH_DIR).glob("*.json"))
    if not paths:
        return {"new": [], "duplicates": [], "errors": [], "bySource": {}}
    existing_doc = _read_json(root / CARDS_PATH)
    if not isinstance(existing_doc, dict) or not isinstance(existing_doc.get("cards"), list):
        raise ValueError("cards.json must be an object with cards array")
    existing = {}
    for card in existing_doc["cards"]:
        if not isinstance(card, dict) or not isinstance(card.get("id"), str) or not card["id"]:
            raise ValueError("cards.json contains a malformed card or missing ID")
        if card["id"] in existing:
            raise ValueError(f"cards.json contains duplicate card ID: {card['id']}")
        existing[card["id"]] = card
    new, duplicates, errors = [], [], []
    source_counts = defaultdict(Counter)
    seen_ids = set()
    for path in paths:
        try:
            rows = _read_json(Path(path))
            if not isinstance(rows, list): raise ValueError("batch JSON must be an array")
        except Exception as exc:
            errors.append({"file": str(path), "row": None, "errors": [f"cannot read batch: {exc}"]})
            continue
        for index, row in enumerate(rows, 1):
            sid = row.get("sourceId", "unknown") if isinstance(row, dict) else "unknown"
            card, issues = _validate_row(row, root=root, units_by_id=units_by_id, article_by_url=article_by_url, parsed_sections=cache_by_url)
            if issues:
                errors.append({"file": Path(path).name, "row": index, "sourceId": sid, "errors": issues})
                source_counts[sid]["invalid"] += 1
                continue
            if card["id"] in seen_ids:
                errors.append({"file": Path(path).name, "row": index, "sourceId": sid, "errors": ["duplicate proposal card ID within input batches"]})
                source_counts[sid]["invalid"] += 1
                continue
            seen_ids.add(card["id"])
            prior = existing.get(card["id"])
            if prior:
                comparable = (prior.get("question"), prior.get("answer"), prior.get("knowledgeUnitIds"), prior.get("provenance", {}).get("candidateEvidenceExcerpt") if isinstance(prior.get("provenance"), dict) else None)
                candidate = (card["question"], card["answer"], card["knowledgeUnitIds"], card["provenance"]["candidateEvidenceExcerpt"])
                if comparable != candidate:
                    errors.append({"file": Path(path).name, "row": index, "sourceId": sid, "errors": ["stable ID conflicts with existing card content; refusing overwrite"]})
                    source_counts[sid]["invalid"] += 1
                else:
                    duplicates.append(card["id"])
                    source_counts[sid]["duplicate"] += 1
                continue
            new.append(card)
            source_counts[sid]["new"] += 1
    return {"new": new, "duplicates": duplicates, "errors": errors, "bySource": {k: dict(v) for k, v in sorted(source_counts.items())}, "existingDoc": existing_doc}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate and import reviewed-batch card proposals without auto-approving them.")
    parser.add_argument("--apply", action="store_true", help="write additions to cards.json; default is a dry run")
    parser.add_argument("--batch", action="append", type=Path, help="import only this batch JSON; may be repeated")
    args = parser.parse_args(argv)
    root = ROOT.resolve()
    result = plan_import(root, args.batch)
    print(json.dumps({"mode": "apply" if args.apply else "dry-run", "new": len(result["new"]), "duplicates": len(result["duplicates"]), "invalid": len(result["errors"]), "bySource": result["bySource"], "errors": result["errors"][:30]}, ensure_ascii=False, indent=2))
    if result["errors"]:
        return 2
    if args.apply and result["new"]:
        path = root / CARDS_PATH
        backup = path.with_name(f"cards.pre-review-batches-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json")
        shutil.copy2(path, backup)
        doc = result["existingDoc"]
        doc["cards"].extend(result["new"])
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(path)
        print(f"Applied {len(result['new'])} candidates. Backup: {backup.relative_to(root)}")
    elif args.apply:
        print("No additions required.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
