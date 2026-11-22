from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

try:
    from .sync_sources import ROOT, SOURCES, load, parse_article, sections
except ImportError:  # direct script execution
    from sync_sources import ROOT, SOURCES, load, parse_article, sections


HUMAN_REVIEW_FIELDS = (
    "reviewerDecision", "reviewerNote", "reviewer", "reviewedAt",
    "acceptedCardIds", "examPointIds",
)

# Keep this order and normalization aligned with web/app.js's
# UNIT_REVIEW_SOURCE_FIELDS / unitReviewSourceSnapshot. The separate
# reviewSourceSha256 binds every decision to the exact visible source snapshot.
REVIEW_SOURCE_FIELDS = (
    "sourceId", "articleTitle", "articleUrl", "sectionIndex",
    "sectionHeadingPath", "sectionAnchor", "blockIndex", "unitIndex",
    "tag", "text", "href", "title", "src", "alt", "cardIds", "status",
    "bodySha256", "presentInCurrentSource", "machineMappingStatus",
)

REVIEW_EXPORT_SCHEMA = "codebrick-knowledge-unit-review-ledger"
REVIEW_EXPORT_RECORD_FIELDS = {
    "knowledgeUnitId", "decision", "reason", "reviewer", "examPoints",
    "acceptedCardIds", "reviewedAt", "sourceHash", "textHash",
}
CARD_ID_RE = re.compile(r"^[a-f0-9]{16}$")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
GENERIC_CARD_QUESTION_RE = re.compile(
    r"^(?:回忆「.+」的核心定义、机制与易错点。|"
    r"请解释「.+」本部分的关键概念、条件、过程与结论。)"
    r"(?:（第\s*\d+\s*/\s*\d+\s*部分）)?$"
)
PLACEHOLDER_ANSWER_RE = re.compile(
    r"^(原文内容未能可靠提取|内容未能可靠提取|待人工核对|占位内容|placeholder\b)(?:[。.!！\s]|$)",
    re.IGNORECASE,
)


def _load_review_export(path: Path) -> dict[str, dict]:
    """Convert a browser v2 export to source-ledger records without trusting its decisions."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"review export could not be read: {exc}") from exc
    if (
        not isinstance(raw, dict)
        or set(raw) != {"schema", "version", "exportedAt", "records"}
        or raw.get("schema") != REVIEW_EXPORT_SCHEMA
        or raw.get("version") != 2
        or not isinstance(raw.get("exportedAt"), str)
        or not isinstance(raw.get("records"), list)
    ):
        raise ValueError("review export must use the version-2 knowledge-unit review schema")
    try:
        datetime.fromisoformat(raw["exportedAt"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("review export has an invalid exportedAt timestamp") from exc

    by_id: dict[str, dict] = {}
    for index, record in enumerate(raw["records"]):
        if not isinstance(record, dict) or set(record) != REVIEW_EXPORT_RECORD_FIELDS:
            raise ValueError(f"review export record {index} has an invalid schema")
        unit_id = record.get("knowledgeUnitId")
        if not isinstance(unit_id, str) or not CARD_ID_RE.fullmatch(unit_id):
            raise ValueError(f"review export record {index} has an invalid knowledgeUnitId")
        if unit_id in by_id:
            raise ValueError(f"review export contains duplicate knowledgeUnitId: {unit_id}")
        decision = record.get("decision")
        if decision == "needs-more":
            decision = "needs-more-evidence"
        if decision not in {"accepted", "rejected", "needs-more-evidence"}:
            raise ValueError(f"review export record {unit_id} has an invalid decision")
        reason, reviewer = record.get("reason"), record.get("reviewer")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 4000:
            raise ValueError(f"review export record {unit_id} has an invalid reason")
        if not isinstance(reviewer, str) or not reviewer.strip() or len(reviewer) > 240:
            raise ValueError(f"review export record {unit_id} has an invalid reviewer")
        exam_points = record.get("examPoints")
        card_ids = record.get("acceptedCardIds")
        if (
            not isinstance(exam_points, list)
            or any(not isinstance(point, str) or not point.strip() or len(point) > 2400 for point in exam_points)
            or not isinstance(card_ids, list)
            or any(not isinstance(card_id, str) or not CARD_ID_RE.fullmatch(card_id) for card_id in card_ids)
        ):
            raise ValueError(f"review export record {unit_id} has invalid examPoints or acceptedCardIds")
        if decision == "accepted" and (not exam_points or not card_ids):
            raise ValueError(f"accepted review export record {unit_id} needs examPoints and acceptedCardIds")
        reviewed_at = record.get("reviewedAt")
        if not isinstance(reviewed_at, str):
            raise ValueError(f"review export record {unit_id} has an invalid reviewedAt")
        try:
            datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"review export record {unit_id} has an invalid reviewedAt") from exc
        source_hash, text_hash = record.get("sourceHash"), record.get("textHash")
        if not isinstance(source_hash, str) or not SHA256_RE.fullmatch(source_hash):
            raise ValueError(f"review export record {unit_id} has an invalid sourceHash")
        if not isinstance(text_hash, str) or not SHA256_RE.fullmatch(text_hash):
            raise ValueError(f"review export record {unit_id} has an invalid textHash")
        by_id[unit_id] = {
            "knowledgeUnitId": unit_id,
            "bodySha256": text_hash,
            "reviewSourceSha256": source_hash,
            "reviewerDecision": decision,
            "reviewerNote": reason,
            "reviewer": reviewer,
            "reviewedAt": reviewed_at,
            "acceptedCardIds": list(dict.fromkeys(card_ids)),
            "examPointIds": list(dict.fromkeys(point.strip() for point in exam_points)),
        }
    return by_id


def _is_concrete_unit_card(unit: dict, card: dict) -> bool:
    """Mirror the browser's current-unit/card binding and concrete-card checks."""
    card_id = str(card.get("id") or "").strip()
    unit_id = str(unit.get("knowledgeUnitId") or "")
    if not CARD_ID_RE.fullmatch(card_id) or card_id not in _browser_data_list(unit.get("cardIds")):
        return False
    linked_unit_ids = _browser_data_list(card.get("knowledgeUnitIds"))
    provenance = card.get("provenance")
    if isinstance(provenance, dict):
        linked_unit_ids.extend(_browser_data_list(provenance.get("knowledgeUnitIds")))
    if unit_id not in linked_unit_ids:
        return False
    status = re.sub(r"\s+", "_", str(card.get("status") or "pending").strip().lower())
    if status in {"archived", "deleted", "rejected"}:
        return False
    question = card.get("question")
    if question is None:
        question = card.get("front")
    question = str(question or "").strip()
    answer = card.get("answer")
    if answer is None:
        answer = card.get("back")
    answer = str(answer or "").strip()
    return bool(
        question and answer
        and not PLACEHOLDER_ANSWER_RE.match(answer)
        and not GENERIC_CARD_QUESTION_RE.fullmatch(question)
    )


def _accepted_card_evidence_is_valid(unit: dict, prior: dict, cards: list[dict]) -> bool:
    card_ids = prior.get("acceptedCardIds")
    if not isinstance(card_ids, list) or not card_ids:
        return False
    cards_by_id: dict[str, list[dict]] = defaultdict(list)
    for card in cards:
        cards_by_id[str(card.get("id") or "").strip()].append(card)
    return all(
        isinstance(card_id, str)
        and CARD_ID_RE.fullmatch(card_id)
        and len(cards_by_id.get(card_id, [])) == 1
        and _is_concrete_unit_card(unit, cards_by_id[card_id][0])
        for card_id in card_ids
    )


def _load_review_ledger(path: Path) -> dict[str, dict]:
    """Load and validate the human ledger; malformed prior work must not vanish silently."""
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"knowledge-units ledger could not be read: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("version") not in (1, 2) or not isinstance(raw.get("units"), list):
        raise ValueError("knowledge-units ledger must be version 1 or 2 with a units list")
    by_id: dict[str, dict] = {}
    for index, unit in enumerate(raw["units"]):
        if not isinstance(unit, dict):
            raise ValueError(f"knowledge-units ledger unit {index} must be an object")
        unit_id = unit.get("knowledgeUnitId")
        if not isinstance(unit_id, str) or not unit_id.strip():
            raise ValueError(f"knowledge-units ledger unit {index} has no knowledgeUnitId")
        if unit_id in by_id:
            raise ValueError(f"knowledge-units ledger contains duplicate knowledgeUnitId: {unit_id}")
        # Version-1 ledgers were machine-only and had no source hash; migrate those
        # by regenerating machine fields, but never carry unbound human decisions.
        if raw["version"] == 1:
            if any(field in unit for field in HUMAN_REVIEW_FIELDS):
                raise ValueError(f"version-1 knowledge-units ledger has unverified human decision: {unit_id}")
            continue
        body_hash = unit.get("bodySha256")
        if not isinstance(body_hash, str) or len(body_hash) != 64 or any(ch not in "0123456789abcdef" for ch in body_hash):
            raise ValueError(f"knowledge-units ledger unit {unit_id} has an invalid bodySha256")
        source_hash = unit.get("reviewSourceSha256")
        if source_hash is not None and (
            not isinstance(source_hash, str) or len(source_hash) != 64
            or any(ch not in "0123456789abcdef" for ch in source_hash)
        ):
            raise ValueError(f"knowledge-units ledger unit {unit_id} has an invalid reviewSourceSha256")
        by_id[unit_id] = unit
    return by_id


def _browser_string(value) -> str:
    """Match JavaScript String(value ?? "") for fields in the browser snapshot."""
    if value is None:
        return ""
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, list):
        return ",".join("" if item is None else _browser_string(item) for item in value)
    if isinstance(value, dict):
        return "[object Object]"
    return str(value)


def _browser_data_list(value) -> list[str]:
    """Match the browser's dataList + String + unique/sorted cardIds normalization."""
    if value is None:
        values = []
    elif isinstance(value, list):
        values = value
    elif isinstance(value, str):
        values = re.split(r"[\n,，]", value)
    else:
        values = [value]
    unique = {text for item in values if item is not None
              and (text := _browser_string(item)).strip()}
    return sorted(unique, key=lambda text: text.encode("utf-16-be", errors="surrogatepass"))


def _review_source_snapshot(unit: dict) -> list:
    """Return the ordered snapshot used by web/app.js when hashing a review."""
    snapshot = []
    for field in REVIEW_SOURCE_FIELDS:
        if field == "cardIds":
            snapshot.append(_browser_data_list(unit.get(field)))
        elif field == "presentInCurrentSource":
            snapshot.append(unit.get(field) is not False)
        else:
            snapshot.append(_browser_string(unit.get(field)))
    return snapshot


def _review_source_sha256(unit: dict) -> str:
    # JSON.stringify-compatible compact JSON: all values are strings, booleans,
    # or string arrays; ensure_ascii=False matches JSON.stringify's UTF-8 bytes.
    encoded = json.dumps(_review_source_snapshot(unit), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _review_state_for_unit(unit: dict, prior: dict | None, cards: list[dict]) -> dict:
    text_hash = hashlib.sha256(unit["text"].encode("utf-8")).hexdigest()
    record = dict(unit)
    record["bodySha256"] = text_hash
    record["presentInCurrentSource"] = True
    record["machineMappingStatus"] = unit["status"]
    source_hash = _review_source_sha256(record)
    record["reviewSourceSha256"] = source_hash
    if prior is None:
        record["reviewerDecision"] = "pending"
        return record

    prior_source_hash = prior.get("reviewSourceSha256")
    prior_body_hash = prior.get("bodySha256")
    source_snapshot_matches = (
        isinstance(prior_source_hash, str) and prior_source_hash == source_hash
        and isinstance(prior_body_hash, str) and prior_body_hash == text_hash
    )
    prior_decision = prior.get("reviewerDecision", "pending")
    has_human_decision = (
        prior_decision not in ("pending", "")
        or any(field in prior for field in HUMAN_REVIEW_FIELDS if field != "reviewerDecision")
    )
    if not source_snapshot_matches and has_human_decision:
        record["reviewerDecision"] = "stale"
        record["reviewStaleReason"] = (
            "source-snapshot-changed" if prior_source_hash else "source-snapshot-unbound"
        )
        if prior_source_hash:
            record["staleFromSourceSha256"] = prior_source_hash
        prior_body_hash = prior.get("bodySha256")
        if isinstance(prior_body_hash, str) and prior_body_hash != text_hash:
            record["staleFromBodySha256"] = prior_body_hash
        record["previousReview"] = {
            field: prior[field] for field in HUMAN_REVIEW_FIELDS if field in prior
        }
        return record

    if prior_decision == "accepted" and not _accepted_card_evidence_is_valid(record, prior, cards):
        record["reviewerDecision"] = "stale"
        record["reviewStaleReason"] = "accepted-card-evidence-invalid"
        record["previousReview"] = {
            field: prior[field] for field in HUMAN_REVIEW_FIELDS if field in prior
        }
        return record

    for field in HUMAN_REVIEW_FIELDS:
        if field in prior:
            record[field] = prior[field]
    record["reviewerDecision"] = prior.get("reviewerDecision", "pending")
    for field in ("reviewStaleReason", "staleFromSourceSha256", "previousReview"):
        if field in prior:
            record[field] = prior[field]
    return record


def build_report(review_export: Path | None = None) -> dict:
    articles = load(ROOT / "data" / "articles.json", {"articles": []}).get("articles", [])
    cards = load(ROOT / "data" / "cards" / "cards.json", {"cards": []}).get("cards", [])
    prior_ledger = _load_review_ledger(ROOT / "data" / "knowledge-units.json")
    if review_export is not None:
        # Explicit exports override matching local ledger decisions; omitted IDs keep history.
        prior_ledger.update(_load_review_export(Path(review_export)))
    historical_cards = [card for card in cards if card.get("sourceSectionRemoved") or card.get("sourceArticleMissing")]
    active_cards = [card for card in cards if not (card.get("sourceSectionRemoved") or card.get("sourceArticleMissing"))]
    by_url: dict[str, list[dict]] = defaultdict(list)
    for card in active_cards:
        by_url[card.get("articleUrl", "").split("#", 1)[0]].append(card)

    rows = []
    failures = []
    mapped_card_ids: set[str] = set()
    ambiguous_cards: list[dict] = []
    unit_rows: list[dict] = []
    orphan_unit_mappings: list[dict] = []
    for article in articles:
        cache = ROOT / article.get("cache", "")
        try:
            parsed = parse_article(cache.read_text(encoding="utf-8"), article["url"])
            article_sections = sections(parsed)
        except Exception as exc:
            failures.append({"sourceId": article.get("sourceId"), "articleUrl": article.get("url"), "error": f"{type(exc).__name__}: {exc}"})
            continue

        article_cards = by_url.get(article["url"], [])
        section_cards: dict[int, list[dict]] = defaultdict(list)
        for card in article_cards:
            target = None
            raw_index = card.get("sectionIndex")
            if isinstance(raw_index, int) and not isinstance(raw_index, bool) and 1 <= raw_index <= len(article_sections):
                indexed = article_sections[raw_index - 1]
                anchor_matches = not card.get("sectionAnchor") or card.get("sectionAnchor") == indexed["anchor"]
                heading_matches = not card.get("section") or card.get("section") == indexed["heading"]
                if anchor_matches and heading_matches:
                    target = indexed
            if target is None:
                anchor_candidates = [
                    section for section in article_sections
                    if card.get("sectionAnchor") and card.get("sectionAnchor") == section["anchor"]
                ]
                if len(anchor_candidates) == 1:
                    target = anchor_candidates[0]
                elif len(anchor_candidates) > 1:
                    candidates = [
                        section for section in anchor_candidates
                        if card.get("section") == section["heading"]
                    ]
                    if len(candidates) == 1:
                        target = candidates[0]
                    else:
                        # Preserve candidate sections for review when the legacy
                        # heading cannot uniquely identify one.
                        unresolved_candidates = candidates or anchor_candidates
                        ambiguous_cards.append({"cardId": card.get("id"), "articleUrl": article["url"], "candidateSectionIndexes": [item["sectionIndex"] for item in unresolved_candidates]})
            if target is not None:
                section_cards[target["sectionIndex"]].append(card)
                mapped_card_ids.add(str(card.get("id", "")))

        for section in article_sections:
            related = section_cards.get(section["sectionIndex"], [])
            needs_review = any(
                card.get("reviewReason") == "source-extraction-incomplete"
                or "linked-question-index-not-question-content" in card.get("auditFlags", [])
                for card in related
            )
            if not related:
                status = "missing-card"
            elif needs_review:
                status = "needs-human-source-review"
            else:
                status = "card-generated-408-review-pending"
            section_unit_ids = {unit["id"] for block in section.get("sourceUnits", []) for unit in block.get("units", [])}
            for block in section.get("sourceUnits", []):
                for unit in block.get("units", []):
                    unit_id = unit["id"]
                    mapped_cards = [card for card in related if unit_id in card.get("knowledgeUnitIds", [])]
                    unit_status = "mapped-candidate-unreviewed" if mapped_cards else "unmapped-blocking"
                    if mapped_cards and unit.get("tag") in {"a", "img", "svg", "canvas"}:
                        unit_status = "linked-reference-pending-review" if unit.get("tag") == "a" else "rich-content-pending-review"
                    unit_rows.append(_review_state_for_unit({
                        "knowledgeUnitId": unit_id,
                        "sourceId": article.get("sourceId"),
                        "articleTitle": parsed["title"],
                        "articleUrl": article["url"],
                        "sectionIndex": section["sectionIndex"],
                        "sectionHeadingPath": section.get("headingPath", section["heading"]),
                        "sectionAnchor": section["anchor"],
                        "blockIndex": unit["blockIndex"],
                        "unitIndex": unit["unitIndex"],
                        "tag": unit["tag"],
                        "text": unit["text"],
                        "href": unit.get("href", ""),
                        "title": unit.get("title", ""),
                        "src": unit.get("src", ""),
                        "alt": unit.get("alt", ""),
                        "cardIds": [card.get("id") for card in mapped_cards],
                        "status": unit_status,
                    }, prior_ledger.get(unit_id), cards))
            for card in related:
                for unit_id in card.get("knowledgeUnitIds", []):
                    if unit_id not in section_unit_ids:
                        orphan_unit_mappings.append({"cardId": card.get("id"), "knowledgeUnitId": unit_id, "articleUrl": article["url"], "sectionIndex": section["sectionIndex"]})
            rows.append({
                "sourceId": article.get("sourceId"),
                "sourceName": next((item["name"] for item in SOURCES if item["id"] == article.get("sourceId")), article.get("sourceId")),
                "articleTitle": parsed["title"],
                "articleUrl": article["url"],
                "sectionIndex": section["sectionIndex"],
                "sectionHeading": section["heading"],
                "sectionHeadingPath": section.get("headingPath", section["heading"]),
                "sectionAnchor": section["anchor"],
                "sourceBlockCount": len(section["content"]),
                "cardCount": len(related),
                "cardIds": [card["id"] for card in related],
                "knowledgeUnitIds": [unit["id"] for block in section.get("sourceUnits", []) for unit in block.get("units", [])],
                "knowledgeUnitCount": sum(len(block.get("units", [])) for block in section.get("sourceUnits", [])),
                "mappedKnowledgeUnitCount": sum(any(unit["id"] in card.get("knowledgeUnitIds", []) for card in related) for block in section.get("sourceUnits", []) for unit in block.get("units", [])),
                "status": status,
            })

    all_card_ids = [str(card.get("id", "")) for card in cards]
    duplicate_ids = sorted(card_id for card_id, count in Counter(all_card_ids).items() if card_id and count > 1)
    orphan_cards = [
        {"cardId": card.get("id"), "sourceId": card.get("sourceId"), "articleUrl": card.get("articleUrl"), "section": card.get("section")}
        for card in active_cards if str(card.get("id", "")) not in mapped_card_ids
    ]
    by_source = {}
    for source in SOURCES:
        source_rows = [row for row in rows if row["sourceId"] == source["id"]]
        counts = Counter(row["status"] for row in source_rows)
        by_source[source["id"]] = {
            "name": source["name"],
            "articleCount": len({row["articleUrl"] for row in source_rows}),
            "sectionCount": len(source_rows),
            "cardCount": sum(row["cardCount"] for row in source_rows),
            "statusCounts": dict(counts),
        }
    current_unit_ids = {unit["knowledgeUnitId"] for unit in unit_rows}
    retired_units = []
    for unit_id, prior in prior_ledger.items():
        if unit_id in current_unit_ids:
            continue
        retired = dict(prior)
        retired["machineMappingStatus"] = "source-unit-removed"
        retired["presentInCurrentSource"] = False
        retired_units.append(retired)
    ledger = {
        "version": 2,
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": "local-synchronized-snapshot",
        "sourceArticleCount": len(articles),
        "knowledgeUnitCount": len(unit_rows),
        "mappedKnowledgeUnitCount": sum(bool(unit["cardIds"]) for unit in unit_rows),
        "unmappedKnowledgeUnitCount": sum(not unit["cardIds"] for unit in unit_rows),
        "units": unit_rows + retired_units,
    }
    decisions = Counter(unit.get("reviewerDecision", "pending") for unit in unit_rows)
    machine_exit_code = 1 if any((
        sum(row["status"] == "missing-card" for row in rows),
        sum(row["status"] == "needs-human-source-review" for row in rows),
        sum(not unit["cardIds"] for unit in unit_rows),
        orphan_unit_mappings, failures, orphan_cards, duplicate_ids, ambiguous_cards,
    )) else 0
    return {
        "version": 2,
        "sourceArticleCount": len(articles),
        "parsedArticleCount": len(articles) - len(failures),
        "sectionCount": len(rows),
        "cardRecordCount": len(cards),
        "activeCardCount": len(active_cards),
        "historicalCardCount": len(historical_cards),
        "coverageCount": sum(row["cardCount"] > 0 for row in rows),
        "missingCardCount": sum(row["status"] == "missing-card" for row in rows),
        "extractionReviewCount": sum(row["status"] == "needs-human-source-review" for row in rows),
        "orphanCardCount": len(orphan_cards),
        "orphanCards": orphan_cards,
        "duplicateCardIds": duplicate_ids,
        "ambiguousCardMappings": ambiguous_cards,
        "knowledgeUnitCount": len(unit_rows),
        "mappedKnowledgeUnitCount": sum(bool(unit["cardIds"]) for unit in unit_rows),
        "reviewedKnowledgeUnitCount": decisions["accepted"],
        "humanAcceptedKnowledgeUnitCount": decisions["accepted"],
        "humanRejectedKnowledgeUnitCount": decisions["rejected"],
        "staleKnowledgeUnitReviewCount": decisions["stale"],
        "pendingKnowledgeUnitReviewCount": sum(decisions[d] for d in ("pending", "needs-more-evidence", "")),
        "retiredKnowledgeUnitCount": len(retired_units),
        "knowledgeUnitLedger": ledger,
        "machineAuditExitCode": machine_exit_code,
        "machineAuditStatus": "pass" if machine_exit_code == 0 else "fail",
        "unmappedKnowledgeUnitCount": sum(not unit["cardIds"] for unit in unit_rows),
        "knowledgeUnits": unit_rows,
        "orphanKnowledgeUnitMappings": orphan_unit_mappings,
        "sourceParseFailures": failures,
        "bySource": by_source,
        "sections": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit source coverage and human review bindings.")
    parser.add_argument(
        "--review-export", type=Path,
        help="validate and apply a browser schema-v2 knowledge-unit review export",
    )
    args = parser.parse_args(argv)
    report = build_report(args.review_export)
    out = ROOT / "data" / "reports"
    out.mkdir(parents=True, exist_ok=True)
    (out / "coverage.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ROOT / "data" / "knowledge-units.json").write_text(json.dumps(report["knowledgeUnitLedger"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# 全文章—章节—知识单元—记忆卡覆盖审计", "", f"- 本地快照文章：{report['sourceArticleCount']}", f"- 成功解析文章：{report['parsedArticleCount']}", f"- 章节：{report['sectionCount']}", f"- 有卡片章节：{report['coverageCount']}", f"- 缺卡章节：{report['missingCardCount']}", f"- 当前章节卡片记录：{report['activeCardCount']}", f"- 已移出来源章节的历史卡（保留，不计入当前覆盖）：{report['historicalCardCount']}", f"- 来源知识单元候选：{report['knowledgeUnitCount']}", f"- 已映射到候选卡：{report['mappedKnowledgeUnitCount']}", f"- 未映射单元：{report['unmappedKnowledgeUnitCount']}", f"- 已人工验收知识单元：{report['reviewedKnowledgeUnitCount']}", f"- 待人工验收知识单元：{report['pendingKnowledgeUnitReviewCount']}", f"- 人工拒绝单元：{report['humanRejectedKnowledgeUnitCount']}", f"- 来源变更后审核失效单元：{report['staleKnowledgeUnitReviewCount']}", f"- 已从当前来源移除、保留历史单元：{report['retiredKnowledgeUnitCount']}", f"- 孤儿知识单元映射：{len(report['orphanKnowledgeUnitMappings'])}", f"- 需人工核对提取：{report['extractionReviewCount']}", f"- 孤儿卡：{report['orphanCardCount']}", f"- 重复卡 ID：{len(report['duplicateCardIds'])}", f"- 歧义章节关联：{len(report['ambiguousCardMappings'])}", "", "> 来源单元到卡片的映射仍是候选追踪记录，不代表每个知识点已由人工确认、题面已原子化或答案正确。", "", "| 科目 | 文章 | 章节 | 卡片关联 | 缺卡 | 待核对 |", "|---|---:|---:|---:|---:|---:|"]
    for sid, item in report["bySource"].items():
        counts = item["statusCounts"]
        lines.append(f"| {item['name']} | {item['articleCount']} | {item['sectionCount']} | {item['cardCount']} | {counts.get('missing-card', 0)} | {counts.get('needs-human-source-review', 0)} |")
    (out / "coverage.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"文章 {report['parsedArticleCount']}/{report['sourceArticleCount']}；章节关联 {report['coverageCount']}/{report['sectionCount']}；来源单元映射 {report['mappedKnowledgeUnitCount']}/{report['knowledgeUnitCount']}；未映射 {report['unmappedKnowledgeUnitCount']}；待人工核对 {report['extractionReviewCount']}；解析失败 {len(report['sourceParseFailures'])}")
    return 1 if any((report["missingCardCount"], report["extractionReviewCount"], report["unmappedKnowledgeUnitCount"], report["orphanKnowledgeUnitMappings"], report["sourceParseFailures"], report["orphanCardCount"], report["duplicateCardIds"], report["ambiguousCardMappings"])) else 0


if __name__ == "__main__":
    raise SystemExit(main())
