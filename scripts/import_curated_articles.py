from __future__ import annotations

"""Read-only structural audit for article-scoped curated card proposals.

Proposal schema (version 1)::

    {
      "schema": "codebrick-curated-article",
      "version": 1,
      "article": {"sourceId": "os", "url": "...", "cache": "...",
                  "contentHash": "<sha256-of-parsed-blocks>"},
      "sourceUnits": [
        {"knowledgeUnitId": "...", "disposition": "card", "cardId": "..."},
        {"knowledgeUnitId": "...", "disposition": "context", "reason": "..."}
      ],
      "cards": [{"cardId": "...", "articleUrl": "...", "front": "...",
                 "back": "...", "knowledgeUnitIds": ["..."]}]
    }

The authored {sourceId, articleUrl, articleContentHash, author, cards,
unitDisposition, issues} format is also supported, including multiple cards per
unit. Authored card fields are id/question/answer/unitIds. Non-card dispositions
require a reason. Structural success never grants content approval.
Stable card IDs can be produced by
:func:`stable_card_id`. This module only reads project files and emits a JSON
summary to stdout; it never imports, rewrites, or approves formal cards.
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    from . import sync_sources
except ImportError:  # direct invocation
    import sync_sources

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "codebrick-curated-article"
VERSION = 1
AUDIT_SCHEMA = "codebrick-curated-article-audit"
AUDIT_VERSION = 1
DISPOSITIONS = {"card", "context", "navigation", "duplicate", "conflict", "unresolved"}
ARTICLE_FIELDS = {"sourceId", "url", "cache", "contentHash"}
ARTICLE_OPTIONAL_FIELDS = {"title"}
SOURCE_UNIT_FIELDS = {"knowledgeUnitId", "disposition", "reason", "cardId", "cardIds"}
SOURCE_UNIT_OPTIONAL_FIELDS = {"sourceText", "locator", "notes", "evidence", "tags"}
CARD_FIELDS = {"cardId", "articleUrl", "front", "back", "knowledgeUnitIds"}
CARD_OPTIONAL_FIELDS = {"tags", "examPoints", "notes", "evidence", "examRelevance", "sourceExcerpt"}
MAX_JSON_BYTES = 128 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class CuratedArticleError(ValueError):
    """A structural or snapshot-binding validation failure."""


def stable_card_id(article_url: str, knowledge_unit_ids: list[str]) -> str:
    """Return the deterministic ID for one curated card and its source units."""
    if not isinstance(article_url, str) or not article_url.strip():
        raise ValueError("article_url must be a non-empty string")
    if not isinstance(knowledge_unit_ids, list) or not knowledge_unit_ids:
        raise ValueError("knowledge_unit_ids must be a non-empty list")
    if any(not isinstance(item, str) or not item for item in knowledge_unit_ids):
        raise ValueError("knowledge_unit_ids must contain non-empty strings")
    if len(knowledge_unit_ids) != len(set(knowledge_unit_ids)):
        raise ValueError("knowledge_unit_ids must be unique")
    key = json.dumps(
        [_url(article_url), sorted(knowledge_unit_ids)],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(("codebrick-curated-card-v1:" + key).encode("utf-8")).hexdigest()
    return "curated-" + digest[:16]


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CuratedArticleError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise CuratedArticleError(f"non-standard JSON numeric constant: {value}")


def _decode_json(raw: bytes, path: Path) -> Any:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CuratedArticleError(f"invalid UTF-8 JSON: {path}: {exc}") from exc
    try:
        return json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise CuratedArticleError(f"invalid JSON: {path}: {exc}") from exc


def _read_json(path: Path, *, max_bytes: int = MAX_JSON_BYTES) -> Any:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise CuratedArticleError(f"cannot read {path}: {exc}") from exc
    if len(raw) > max_bytes:
        raise CuratedArticleError(f"JSON exceeds {max_bytes}-byte safety limit: {path}")
    return _decode_json(raw, path)


def _as_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CuratedArticleError(f"{label} must be a JSON object")
    return value


def _as_array(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise CuratedArticleError(f"{label} must be a JSON array")
    return value


def _url(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.split("#", 1)[0]


def _normalise_cache(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.replace("\\", "/")


def _path_inside(root: Path, relative: Any, label: str) -> Path:
    if not isinstance(relative, str) or not relative.strip():
        raise CuratedArticleError(f"{label} must be a non-empty project-relative path")
    raw = Path(relative)
    if raw.is_absolute() or raw.drive:
        raise CuratedArticleError(f"{label} must be project-relative")
    root_resolved = root.resolve()
    resolved = (root_resolved / raw).resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise CuratedArticleError(f"{label} escapes the project root")
    return resolved


def _hash_parsed_article(parsed: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(parsed["blocks"], ensure_ascii=False).encode("utf-8")).hexdigest()


def _article_by_url(article_doc: Any) -> dict[str, dict[str, Any]]:
    doc = _as_object(article_doc, "data/articles.json")
    rows = _as_array(doc.get("articles"), "data/articles.json.articles")
    result: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        article = _as_object(row, f"data/articles.json.articles[{index}]")
        url = _url(article.get("url"))
        if not url:
            raise CuratedArticleError(f"data/articles.json.articles[{index}] has an invalid url")
        if url in result:
            raise CuratedArticleError(f"duplicate article URL in data/articles.json: {url}")
        result[url] = article
    return result


def _units_by_id(unit_doc: Any) -> dict[str, dict[str, Any]]:
    doc = _as_object(unit_doc, "data/knowledge-units.json")
    rows = _as_array(doc.get("units"), "data/knowledge-units.json.units")
    result: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        unit = _as_object(row, f"data/knowledge-units.json.units[{index}]")
        unit_id = unit.get("knowledgeUnitId")
        if not isinstance(unit_id, str) or not unit_id.strip():
            raise CuratedArticleError(f"data/knowledge-units.json.units[{index}] has an invalid knowledgeUnitId")
        if unit_id in result:
            raise CuratedArticleError(f"duplicate knowledgeUnitId in data/knowledge-units.json: {unit_id}")
        result[unit_id] = unit
    return result


def _formal_card_ids(root: Path) -> set[str]:
    """Read formal card IDs only to detect collisions; never modify that file."""
    path = root / "data/cards/cards.json"
    if not path.is_file():
        return set()
    doc = _as_object(_read_json(path), "data/cards/cards.json")
    rows = _as_array(doc.get("cards"), "data/cards/cards.json.cards")
    ids: set[str] = set()
    for index, row in enumerate(rows):
        card = _as_object(row, f"data/cards/cards.json.cards[{index}]")
        card_id = card.get("id")
        if not isinstance(card_id, str) or not card_id.strip():
            raise CuratedArticleError(f"data/cards/cards.json.cards[{index}] has an invalid id")
        if card_id in ids:
            raise CuratedArticleError(f"duplicate formal card id: {card_id}")
        ids.add(card_id)
    return ids


def _parsed_units(parsed: dict[str, Any], source_id: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for section in sync_sources.sections(parsed):
        for block in section.get("sourceUnits", []):
            for unit in block.get("units", []):
                result.append({
                    "knowledgeUnitId": unit.get("id", ""),
                    "sourceId": source_id,
                    "articleTitle": parsed.get("title", ""),
                    "articleUrl": parsed.get("url", ""),
                    "sectionIndex": section.get("sectionIndex"),
                    "sectionHeadingPath": section.get("headingPath", ""),
                    "sectionAnchor": section.get("anchor", ""),
                    "blockIndex": unit.get("blockIndex"),
                    "unitIndex": unit.get("unitIndex"),
                    "tag": unit.get("tag", ""),
                    "text": unit.get("text", ""),
                    "href": unit.get("href", ""),
                    "title": unit.get("title", ""),
                    "src": unit.get("src", ""),
                    "alt": unit.get("alt", ""),
                })
    return result


def _validate_current_units(
    *,
    article_url: str,
    source_id: str,
    parsed_units: list[dict[str, Any]],
    ledger_by_id: dict[str, dict[str, Any]],
    errors: list[dict[str, str]],
) -> None:
    parsed_by_id: dict[str, dict[str, Any]] = {}
    for index, unit in enumerate(parsed_units):
        unit_id = unit["knowledgeUnitId"]
        if not isinstance(unit_id, str) or not unit_id:
            errors.append({"code": "parsed_unit_missing_id", "path": f"parsed.units[{index}]", "message": "parsed source unit has no stable ID"})
            continue
        if unit_id in parsed_by_id:
            errors.append({"code": "duplicate_parsed_unit_id", "path": f"parsed.units[{index}]", "message": f"duplicate parsed knowledgeUnitId: {unit_id}"})
        parsed_by_id[unit_id] = unit

    ledger_target = {
        unit_id: row for unit_id, row in ledger_by_id.items()
        if _url(row.get("articleUrl")) == article_url
    }
    parsed_ids, ledger_ids = set(parsed_by_id), set(ledger_target)
    for unit_id in sorted(parsed_ids - ledger_ids):
        errors.append({"code": "ledger_missing_unit", "path": f"data/knowledge-units.json[{unit_id}]", "message": "current parsed source unit is absent from the knowledge-unit ledger"})
    for unit_id in sorted(ledger_ids - parsed_ids):
        errors.append({"code": "ledger_extra_unit", "path": f"data/knowledge-units.json[{unit_id}]", "message": "knowledge-unit ledger contains an article unit not produced by the current cache"})

    fields = ("sourceId", "articleUrl", "articleTitle", "sectionIndex", "sectionHeadingPath", "sectionAnchor", "blockIndex", "unitIndex", "tag", "text", "href", "title", "src", "alt")
    for unit_id in sorted(parsed_ids & ledger_ids):
        parsed, ledger = parsed_by_id[unit_id], ledger_target[unit_id]
        for field in fields:
            expected = parsed.get(field)
            actual = ledger.get(field)
            if field == "articleUrl":
                expected, actual = _url(expected), _url(actual)
            if actual != expected:
                errors.append({
                    "code": "ledger_locator_mismatch" if field != "text" else "ledger_text_mismatch",
                    "path": f"data/knowledge-units.json[{unit_id}].{field}",
                    "message": f"ledger {field} does not match the current parsed cache",
                })


def _add_error(errors: list[dict[str, str]], code: str, path: str, message: str) -> None:
    errors.append({"code": code, "path": path, "message": message})


def _summary(ok: bool, candidate_path: Path, article: dict[str, Any], counts: dict[str, Any], errors: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "schema": AUDIT_SCHEMA,
        "version": AUDIT_VERSION,
        "ok": bool(ok),
        "candidate": candidate_path.as_posix(),
        "article": article,
        "counts": counts,
        "errors": errors,
        "projectFilesWritten": False,
        "structuralOk": bool(ok),
        "contentApproved": False,
        "contentReviewStatus": "not-evaluated",
        "contentBlocked": True,
    }


def _empty_counts() -> dict[str, Any]:
    return {
        "parsedKnowledgeUnits": 0,
        "curatedSourceUnits": 0,
        "cards": 0,
        "dispositions": {name: 0 for name in sorted(DISPOSITIONS)},
    }


def _normalise_proposal(proposal: Any, articles: dict[str, dict[str, Any]]) -> tuple[Any, list[dict[str, str]]]:
    """Adapt the authored article format without modifying its bytes or IDs.

    The original {article, sourceUnits} format remains supported. Both formats
    use the same fail-closed source/hash and bidirectional reference checks.
    """
    errors: list[dict[str, str]] = []
    if not isinstance(proposal, dict) or not ({"articleUrl", "unitDisposition"} & set(proposal)):
        return proposal, errors
    required = {"schema", "version", "sourceId", "articleUrl", "articleContentHash", "author", "cards", "unitDisposition"}
    optional = {"issues", "metadata", "createdAt", "reviewNotes"}
    if not required <= set(proposal) or set(proposal) - required - optional:
        _add_error(errors, "schema_fields", "$", "authored proposal has missing, mixed-format or unsupported fields")
    author = proposal.get("author")
    if not isinstance(author, dict) or not isinstance(author.get("kind"), str) or author.get("kind") not in {"ai", "human"}:
        _add_error(errors, "author", "$.author", "author must declare kind ai or human; this is provenance, not approval")
    if "issues" in proposal and not isinstance(proposal["issues"], list):
        _add_error(errors, "issues", "$.issues", "issues must be an array")
    elif isinstance(proposal.get("issues"), list):
        for index, issue in enumerate(proposal["issues"]):
            if not isinstance(issue, dict) or ("status" in issue and not isinstance(issue["status"], str)):
                _add_error(errors, "issues", f"$.issues[{index}]", "issue must be an object with a string status when present")
    raw_url = proposal.get("articleUrl")
    manifest = articles.get(_url(raw_url), {})
    result = {
        "schema": proposal.get("schema"), "version": proposal.get("version"),
        "article": {"sourceId": proposal.get("sourceId"), "url": raw_url,
                    "cache": manifest.get("cache", ""), "contentHash": proposal.get("articleContentHash")},
        "cards": [], "sourceUnits": [],
    }
    cards = proposal.get("cards")
    if not isinstance(cards, list):
        _add_error(errors, "cards", "$.cards", "cards must be an array")
        cards = []
    for index, row in enumerate(cards):
        path = f"$.cards[{index}]"
        if not isinstance(row, dict):
            _add_error(errors, "card", path, "card must be an object")
            continue
        fields = {"id", "question", "answer", "unitIds"}
        optional_card = {"examSkill", "tags", "assumptions", "sourceNotes", "notes", "examPoints", "evidence"}
        if not fields <= set(row) or set(row) - fields - optional_card:
            _add_error(errors, "card_fields", path, "authored card has missing or unsupported fields")
        for field in ("tags", "assumptions", "sourceNotes"):
            if field in row and (not isinstance(row[field], list) or any(not isinstance(v, str) for v in row[field])):
                _add_error(errors, "card_field", f"{path}.{field}", f"{field} must be a string array")
        result["cards"].append({"cardId": row.get("id"), "articleUrl": raw_url,
                                "front": row.get("question"), "back": row.get("answer"),
                                "knowledgeUnitIds": row.get("unitIds")})
    units = proposal.get("unitDisposition")
    if not isinstance(units, list):
        _add_error(errors, "source_units", "$.unitDisposition", "unitDisposition must be an array")
        units = []
    for index, row in enumerate(units):
        path = f"$.unitDisposition[{index}]"
        if not isinstance(row, dict):
            _add_error(errors, "source_unit", path, "disposition must be an object")
            continue
        if not {"unitId", "action"} <= set(row) or set(row) - {"unitId", "action", "cardIds", "reason"}:
            _add_error(errors, "source_unit_fields", path, "disposition has missing or unsupported fields")
        mapped = {"knowledgeUnitId": row.get("unitId"), "disposition": row.get("action"),
                  "cardIds": row.get("cardIds", [])}
        if "reason" in row:
            mapped["reason"] = row["reason"]
        result["sourceUnits"].append(mapped)
    return result, errors


def _validate_proposal(
    proposal: Any,
    *,
    root: Path,
    candidate_path: Path,
    articles: dict[str, dict[str, Any]],
    ledger_by_id: dict[str, dict[str, Any]],
    formal_card_ids: set[str],
) -> dict[str, Any]:
    proposal, errors = _normalise_proposal(proposal, articles)
    counts = _empty_counts()
    article_summary: dict[str, Any] = {}
    if not isinstance(proposal, dict):
        _add_error(errors, "schema", "$", "curated proposal must be an object")
        return _summary(False, candidate_path, article_summary, counts, errors)

    expected_top = {"schema", "version", "article", "sourceUnits", "cards"}
    top_optional = {"metadata", "curator", "createdAt", "reviewNotes"}
    if not expected_top <= set(proposal) or set(proposal) - expected_top - top_optional:
        _add_error(errors, "schema_fields", "$", f"top-level fields must contain {sorted(expected_top)} and no unsupported fields")
    if proposal.get("schema") != SCHEMA:
        _add_error(errors, "schema", "$.schema", f"schema must be {SCHEMA!r}")
    if type(proposal.get("version")) is not int or proposal.get("version") != VERSION:
        _add_error(errors, "version", "$.version", f"version must be integer {VERSION}")
    article_meta = proposal.get("article")
    if not isinstance(article_meta, dict):
        _add_error(errors, "article_metadata", "$.article", "article must be an object")
        return _summary(False, candidate_path, article_summary, counts, errors)
    if not ARTICLE_FIELDS <= set(article_meta) or set(article_meta) - ARTICLE_FIELDS - ARTICLE_OPTIONAL_FIELDS:
        _add_error(errors, "article_fields", "$.article", "article must contain required bindings and no unsupported fields")
    if not ARTICLE_FIELDS <= set(article_meta):
        return _summary(False, candidate_path, article_summary, counts, errors)

    source_id = article_meta.get("sourceId")
    raw_url = article_meta.get("url")
    article_url = _url(raw_url)
    cache_value = _normalise_cache(article_meta.get("cache"))
    declared_hash = article_meta.get("contentHash")
    article_summary.update({"sourceId": source_id, "url": article_url, "cache": cache_value, "contentHash": declared_hash})
    if not isinstance(source_id, str) or not source_id.strip():
        _add_error(errors, "article_metadata", "$.article.sourceId", "sourceId must be a non-empty string")
    if not isinstance(raw_url, str) or not article_url or raw_url != article_url:
        _add_error(errors, "article_metadata", "$.article.url", "url must be a non-empty canonical article URL without a fragment")
    if not isinstance(declared_hash, str) or not SHA256_RE.fullmatch(declared_hash):
        _add_error(errors, "article_metadata", "$.article.contentHash", "contentHash must be a lowercase SHA-256 hex digest")

    manifest = articles.get(article_url)
    if manifest is None:
        _add_error(errors, "article_not_in_manifest", "$.article.url", "article URL is not in data/articles.json")
    else:
        if source_id != manifest.get("sourceId"):
            _add_error(errors, "article_binding_mismatch", "$.article.sourceId", "sourceId does not match data/articles.json")
        if cache_value != _normalise_cache(manifest.get("cache")):
            _add_error(errors, "article_binding_mismatch", "$.article.cache", "cache path does not match data/articles.json")
        if declared_hash != manifest.get("contentHash"):
            _add_error(errors, "article_binding_mismatch", "$.article.contentHash", "contentHash does not match data/articles.json")
        if "title" in article_meta and article_meta["title"] != manifest.get("title"):
            _add_error(errors, "article_binding_mismatch", "$.article.title", "title does not match data/articles.json")
        article_summary["manifest"] = {
            "sourceId": manifest.get("sourceId"),
            "url": _url(manifest.get("url")),
            "cache": _normalise_cache(manifest.get("cache")),
            "contentHash": manifest.get("contentHash"),
        }

    parsed_units: list[dict[str, Any]] = []
    parsed_ok = False
    if manifest is not None:
        try:
            cache_path = _path_inside(root, manifest.get("cache"), "manifest cache")
            if not cache_path.is_file():
                raise CuratedArticleError(f"manifest cache does not exist: {manifest.get('cache')}")
            raw = cache_path.read_text(encoding="utf-8")
            parsed = sync_sources.parse_article(raw, article_url)
            computed_hash = _hash_parsed_article(parsed)
            article_summary["computedContentHash"] = computed_hash
            if computed_hash != manifest.get("contentHash"):
                _add_error(errors, "cache_hash_mismatch", "data/articles.json.contentHash", "cache content hash does not match parsed cache")
            parsed_units = _parsed_units(parsed, str(manifest.get("sourceId", "")))
            counts["parsedKnowledgeUnits"] = len(parsed_units)
            parsed_ok = True
        except (OSError, UnicodeError, ValueError) as exc:
            _add_error(errors, "cache_unavailable", "$.article.cache", str(exc))

    if parsed_ok and not parsed_units:
        _add_error(errors, "empty_current_units", "$.article.cache", "current cache has no parsable knowledge units; coverage cannot be established as complete")
    if parsed_ok:
        _validate_current_units(
            article_url=article_url,
            source_id=str(manifest.get("sourceId", "")),
            parsed_units=parsed_units,
            ledger_by_id=ledger_by_id,
            errors=errors,
        )
    parsed_by_id = {unit["knowledgeUnitId"]: unit for unit in parsed_units if unit.get("knowledgeUnitId")}
    parsed_ids = set(parsed_by_id)

    source_rows = proposal.get("sourceUnits")
    if not isinstance(source_rows, list):
        _add_error(errors, "source_units", "$.sourceUnits", "sourceUnits must be an array")
        source_rows = []
    card_rows = proposal.get("cards")
    if not isinstance(card_rows, list):
        _add_error(errors, "cards", "$.cards", "cards must be an array")
        card_rows = []
    counts["curatedSourceUnits"] = len(source_rows)
    counts["cards"] = len(card_rows)

    disposition_by_unit: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(source_rows):
        path = f"$.sourceUnits[{index}]"
        if not isinstance(row, dict):
            _add_error(errors, "source_unit", path, "source unit must be an object")
            continue
        unit_id = row.get("knowledgeUnitId")
        if not isinstance(unit_id, str) or not unit_id.strip():
            _add_error(errors, "source_unit", f"{path}.knowledgeUnitId", "knowledgeUnitId must be a non-empty string")
            continue
        if set(row) - SOURCE_UNIT_FIELDS - SOURCE_UNIT_OPTIONAL_FIELDS or not {"knowledgeUnitId", "disposition"} <= set(row):
            _add_error(errors, "source_unit_fields", path, "source unit has missing or unsupported fields")
        if unit_id in disposition_by_unit:
            _add_error(errors, "duplicate_disposition", path, f"knowledgeUnitId has more than one disposition: {unit_id}")
            continue
        disposition_by_unit[unit_id] = row
        disposition = row.get("disposition")
        if not isinstance(disposition, str) or disposition not in DISPOSITIONS:
            _add_error(errors, "disposition", f"{path}.disposition", f"disposition must be one of {sorted(DISPOSITIONS)}")
            continue
        counts["dispositions"][disposition] += 1
        if "cardId" in row and "cardIds" in row:
            _add_error(errors, "card_reference", path, "use cardId or cardIds, not both")
        refs = row.get("cardIds", [row["cardId"]] if "cardId" in row else [])
        if not isinstance(refs, list) or any(not isinstance(v, str) or not v.strip() for v in refs):
            _add_error(errors, "card_reference", path, "card references must be a string array")
            refs = []
        elif len(refs) != len(set(refs)):
            _add_error(errors, "card_reference", path, "card references must be unique")
        row["cardIds"] = refs
        if disposition == "card":
            if not refs:
                _add_error(errors, "card_reference", path, "card disposition requires one or more card references")
        else:
            if refs or "cardId" in row:
                _add_error(errors, "card_reference", path, "non-card dispositions cannot reference cards")
            if not isinstance(row.get("reason"), str) or not row.get("reason", "").strip():
                _add_error(errors, "reason", f"{path}.reason", "non-card dispositions require a non-empty reason")

    for unit_id in sorted(parsed_ids - set(disposition_by_unit)):
        _add_error(errors, "missing_disposition", "$.sourceUnits", f"current parsed knowledge unit has no disposition: {unit_id}")
    for unit_id in sorted(set(disposition_by_unit) - parsed_ids):
        _add_error(errors, "unknown_source_unit", "$.sourceUnits", f"proposal references a unit not produced by the current cache: {unit_id}")

    cards_by_id: dict[str, dict[str, Any]] = {}
    disposition_units_by_card: dict[str, set[str]] = {}
    for unit_id, row in disposition_by_unit.items():
        if row.get("disposition") == "card":
            for card_id in row.get("cardIds", []):
                disposition_units_by_card.setdefault(card_id, set()).add(unit_id)

    for index, row in enumerate(card_rows):
        path = f"$.cards[{index}]"
        if not isinstance(row, dict):
            _add_error(errors, "card", path, "card must be an object")
            continue
        card_id = row.get("cardId")
        if not CARD_FIELDS <= set(row) or set(row) - CARD_FIELDS - CARD_OPTIONAL_FIELDS:
            _add_error(errors, "card_fields", path, f"card fields must contain {sorted(CARD_FIELDS)} and no unsupported fields")
        if not isinstance(card_id, str) or not card_id.strip() or any(ch.isspace() for ch in card_id) or len(card_id) > 128:
            _add_error(errors, "card_id", f"{path}.cardId", "cardId must be a non-empty stable identifier without whitespace")
            continue
        if card_id in cards_by_id:
            _add_error(errors, "duplicate_card_id", f"{path}.cardId", f"duplicate cardId: {card_id}")
            continue
        cards_by_id[card_id] = row
        if card_id in formal_card_ids:
            _add_error(errors, "formal_card_collision", f"{path}.cardId", "cardId already exists in formal data/cards/cards.json; formal data is never overwritten")
        if not isinstance(row.get("front"), str) or not row.get("front", "").strip():
            _add_error(errors, "card_field", f"{path}.front", "front must be a non-empty string")
        if not isinstance(row.get("back"), str) or not row.get("back", "").strip():
            _add_error(errors, "card_field", f"{path}.back", "back must be a non-empty string")
        if _url(row.get("articleUrl")) != article_url or row.get("articleUrl") != article_url:
            _add_error(errors, "card_scope", f"{path}.articleUrl", "card articleUrl must exactly match the proposal article URL")
        ids = row.get("knowledgeUnitIds")
        if not isinstance(ids, list) or not ids or any(not isinstance(item, str) or not item.strip() for item in ids) or len(ids) != len(set(ids)):
            _add_error(errors, "card_units", f"{path}.knowledgeUnitIds", "knowledgeUnitIds must be a non-empty unique string array")
            ids = []
        else:
            for unit_id in ids:
                if unit_id not in parsed_ids:
                    _add_error(errors, "card_units", f"{path}.knowledgeUnitIds", f"card references unknown source unit: {unit_id}")
        assigned_ids = disposition_units_by_card.get(card_id, set())
        if set(ids) != assigned_ids:
            _add_error(errors, "card_reference", f"{path}.knowledgeUnitIds", "card knowledgeUnitIds must exactly equal the units assigned to this cardId by card dispositions")
        for unit_id in ids:
            disposition = disposition_by_unit.get(unit_id)
            if disposition is None or disposition.get("disposition") != "card" or card_id not in disposition.get("cardIds", []):
                _add_error(errors, "card_reference", f"{path}.knowledgeUnitIds", f"card reference is not mirrored by that unit's card disposition: {unit_id}")

    for unit_id, row in disposition_by_unit.items():
        if row.get("disposition") == "card":
            for card_id in row.get("cardIds", []):
                if card_id not in cards_by_id:
                    _add_error(errors, "card_reference", f"$.sourceUnits[{unit_id}].cardIds", f"cardId does not exist in $.cards: {card_id}")
    for card_id in sorted(set(cards_by_id) - set(disposition_units_by_card)):
        _add_error(errors, "unreferenced_card", "$.cards", f"card is not referenced by a card disposition: {card_id}")

    if parsed_ok:
        expected = parsed_ids
        observed = set(disposition_by_unit)
        if expected != observed:
            _add_error(errors, "coverage", "$.sourceUnits", "source unit dispositions do not exactly cover the current parsed unit set")
    else:
        _add_error(errors, "coverage_unverifiable", "$.sourceUnits", "cannot prove full source-unit coverage without a verified cache parse")

    return _summary(not errors, candidate_path, article_summary, counts, errors)


def audit_article(article_path: Path | str, root: Path | str | None = None) -> dict[str, Any]:
    """Audit one proposal and return a JSON-serialisable summary without writes."""
    root_path = Path(root or ROOT).resolve()
    candidate = Path(article_path)
    if not candidate.is_absolute():
        candidate = root_path / candidate
    empty_counts = _empty_counts()
    try:
        candidate = candidate.resolve()
        if candidate == root_path or root_path not in candidate.parents:
            raise CuratedArticleError("candidate path must stay inside the project root")
        candidate_raw = candidate.read_bytes()
        if len(candidate_raw) > MAX_JSON_BYTES:
            raise CuratedArticleError("candidate exceeds JSON safety limit")
        proposal = _decode_json(candidate_raw, candidate)
        articles = _article_by_url(_read_json(root_path / "data/articles.json"))
        ledger = _units_by_id(_read_json(root_path / "data/knowledge-units.json"))
        formal_ids = _formal_card_ids(root_path)
        summary = _validate_proposal(
            proposal,
            root=root_path,
            candidate_path=candidate,
            articles=articles,
            ledger_by_id=ledger,
            formal_card_ids=formal_ids,
        )
        try:
            from . import supplemental_sources
        except ImportError:
            import supplemental_sources
        has_supplements = isinstance(proposal, dict) and isinstance(proposal.get("metadata"), dict) and "supplementalSources" in proposal["metadata"]
        manifest = articles.get(summary.get("article", {}).get("url")) if summary["ok"] and has_supplements else None
        if manifest is not None:
            parsed = sync_sources.parse_article(_path_inside(root_path, manifest["cache"], "manifest cache").read_text(encoding="utf-8"), manifest["url"])
            section_indices = set(range(1, len(sync_sources.sections(parsed)) + 1))
            static_units = {u["knowledgeUnitId"]: u for u in _parsed_units(parsed, manifest["sourceId"])}
            supplements, supplemental_errors = supplemental_sources.validate(proposal, root_path, section_indices, static_units)
            summary["errors"].extend(supplemental_errors)
            summary["ok"] = summary["ok"] and not supplemental_errors
            summary["supplementalSourceCount"] = len(supplements)
        summary["candidateSha256"] = hashlib.sha256(candidate_raw).hexdigest()
        summary["structuralOk"] = summary["ok"]
        summary["contentApproved"] = False
        summary["contentReviewStatus"] = "not-evaluated"
        issues = proposal.get("issues", []) if isinstance(proposal, dict) else []
        summary["openIssueCount"] = sum(1 for issue in issues if not isinstance(issue, dict) or issue.get("status") not in ("resolved", "closed")) if isinstance(issues, list) else 1
        summary["blockedUnitCount"] = sum(summary["counts"]["dispositions"][name] for name in ("unresolved", "conflict"))
        summary["contentBlocked"] = not summary["ok"] or bool(summary["openIssueCount"] or summary["blockedUnitCount"])
        return summary
    except (OSError, UnicodeError, CuratedArticleError, ValueError, RecursionError) as exc:
        return _summary(False, candidate, {}, empty_counts, [{"code": "audit_failure", "path": str(candidate), "message": str(exc)}])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only structural audit of article-scoped curated cards")
    parser.add_argument("--article", required=True, help="proposal JSON path, relative to --root or absolute")
    parser.add_argument("--root", default=str(ROOT), help="project root (defaults to this project)")
    parser.add_argument("--check", action="store_true", help="explicitly request the default read-only audit")
    args = parser.parse_args(argv)  # There are intentionally no mutation/import flags.
    root = Path(args.root).resolve()
    summary = audit_article(args.article, root)
    print(json.dumps(summary, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())



