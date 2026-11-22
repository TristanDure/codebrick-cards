from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from . import sync_sources
    from .audit_coverage import _review_source_sha256
except ImportError:  # direct script execution
    import sync_sources
    from audit_coverage import _review_source_sha256

ROOT = Path(__file__).resolve().parents[1]
PACK_SCHEMA = "codebrick-offline-review-pack"
PACK_VERSION = 3
_MAX_SECTION_CONTEXT_CHARS = 12000
INPUTS = {
    "knowledgeUnits": Path("data/knowledge-units.json"),
    "cards": Path("data/cards/cards.json"),
    "articles": Path("data/articles.json"),
}


class ReviewPackError(ValueError):
    """Raised when a review pack cannot be built or safely written."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReviewPackError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _read_json(path: Path) -> tuple[Any, bytes]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ReviewPackError(f"cannot read input {path}: {exc}") from exc
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object), raw
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReviewPackError(f"invalid UTF-8 JSON in {path}: {exc}") from exc


def _rows(document: Any, key: str, label: str) -> list[dict[str, Any]]:
    if not isinstance(document, dict) or not isinstance(document.get(key), list):
        raise ReviewPackError(f"{label} must be an object containing a {key!r} array")
    rows = document[key]
    if any(not isinstance(row, dict) for row in rows):
        raise ReviewPackError(f"every row in {label}.{key} must be an object")
    return rows


def _require_unique_ids(rows: list[dict[str, Any]], field: str, label: str) -> None:
    seen: set[str] = set()
    for index, row in enumerate(rows):
        value = row.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ReviewPackError(f"{label}[{index}] has a missing or invalid {field}")
        if value in seen:
            raise ReviewPackError(f"duplicate {field} in {label}: {value}")
        seen.add(value)


def _require_unique_reference_ids(rows: list[dict[str, Any]], field: str, label: str) -> None:
    for index, row in enumerate(rows):
        values = row.get(field, [])
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            raise ReviewPackError(f"{label}[{index}].{field} must be an array of strings")
        if len(values) != len(set(values)):
            raise ReviewPackError(f"duplicate ID in {label}[{index}].{field}")


def _article_key(article: dict[str, Any]) -> str:
    cache = article.get("cache")
    return Path(cache).stem if isinstance(cache, str) and cache else ""


def _url_key(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    # Fragments identify section locators, not distinct source articles.
    return value.split("#", 1)[0].rstrip("/").casefold()


def _validate_articles(articles: list[dict[str, Any]]) -> None:
    urls: set[str] = set()
    article_ids: set[str] = set()
    for index, article in enumerate(articles):
        url = article.get("url")
        if not isinstance(url, str) or not url.strip():
            raise ReviewPackError(f"articles[{index}] has a missing or invalid url")
        normalized = _url_key(url)
        if normalized in urls:
            raise ReviewPackError(f"duplicate article URL: {url}")
        urls.add(normalized)
        article_id = _article_key(article)
        if article_id:
            if article_id in article_ids:
                raise ReviewPackError(f"duplicate article ID (cache filename stem): {article_id}")
            article_ids.add(article_id)


def _article_filter_matches(query: str, unit: dict[str, Any], article: dict[str, Any] | None) -> bool:
    """Exact URL/cache article ID/unit ID first; otherwise case-insensitive text substring."""
    q = query.strip()
    if not q:
        return True
    if q.casefold() == str(unit.get("knowledgeUnitId", "")).casefold():
        return True
    article_url = (article or {}).get("url") or unit.get("articleUrl", "")
    unit_url = unit.get("articleUrl", "")
    if _url_key(q) and _url_key(q) in {_url_key(article_url), _url_key(unit_url)}:
        return True
    article_id = _article_key(article or {})
    if article_id and q.casefold() == article_id.casefold():
        return True
    searchable = (
        (article or {}).get("title", ""), article_url,
        unit.get("articleTitle", ""), unit.get("sectionHeadingPath", ""), unit.get("text", ""),
    )
    needle = q.casefold()
    return any(isinstance(value, str) and needle in value.casefold() for value in searchable)


def _linked_cards(
    unit: dict[str, Any],
    cards_by_id: dict[str, dict[str, Any]],
    cards_by_unit: dict[str, list[str]],
) -> tuple[list[dict[str, Any]], list[str]]:
    unit_id = unit["knowledgeUnitId"]
    card_ids = list(unit.get("cardIds", []))
    card_ids.extend(card_id for card_id in cards_by_unit.get(unit_id, []) if card_id not in card_ids)
    cards: list[dict[str, Any]] = []
    missing: list[str] = []
    for card_id in card_ids:
        card = cards_by_id.get(card_id)
        if card is None:
            missing.append(card_id)
        else:
            cards.append({
                "id": card_id,
                "question": card.get("question", ""),
                "answer": card.get("answer", ""),
                "status": card.get("status", "unknown"),
                "knowledgeUnitReviewStatus": card.get("knowledgeUnitReviewStatus", "unknown"),
            })
    return cards, missing


def _load_article_context(root: Path, article: dict[str, Any] | None) -> dict[str, Any]:
    """Parse and verify one cached article once before extracting section context."""
    cache = (article or {}).get("cache")
    if not isinstance(cache, str) or not cache.strip():
        return {"status": "unavailable", "reason": "article-cache-path-missing"}
    try:
        root = root.resolve()
        cache_path = (root / cache).resolve()
        cache_path.relative_to(root)
    except (OSError, ValueError):
        return {"status": "unavailable", "reason": "article-cache-path-escapes-project"}
    try:
        raw = cache_path.read_bytes()
        source_html_hash = hashlib.sha256(raw).hexdigest()
        parsed = sync_sources.parse_article(raw.decode("utf-8"), str((article or {}).get("url", "")))
    except FileNotFoundError:
        return {"status": "unavailable", "reason": "article-cache-file-missing", "cacheHtmlSha256": ""}
    except (OSError, UnicodeDecodeError, ValueError, TypeError, RecursionError) as exc:
        return {"status": "unavailable", "reason": f"article-cache-parse-failed:{type(exc).__name__}"}

    actual_content_hash = hashlib.sha256(
        json.dumps(parsed["blocks"], ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    expected_content_hash = (article or {}).get("contentHash")
    common = {
        "cachePath": cache.replace("\\", "/"),
        "cacheHtmlSha256": source_html_hash,
        "expectedContentHash": expected_content_hash or "",
        "actualContentHash": actual_content_hash,
    }
    if not isinstance(expected_content_hash, str) or not expected_content_hash:
        return {"status": "unavailable", "reason": "article-content-hash-missing", **common}
    if actual_content_hash != expected_content_hash:
        return {
            "status": "content-hash-mismatch",
            "reason": "cached-article-does-not-match-article-manifest",
            **common,
        }
    return {"status": "verified", "reason": "parsed-cache-content-hash-matches-article-manifest",
            "sections": sync_sources.sections(parsed), **common}


def _section_context(
    article_context: dict[str, Any], unit: dict[str, Any]
) -> dict[str, Any]:
    """Return bounded section units only after content and unit locator verification."""
    if article_context.get("status") != "verified":
        return {key: value for key, value in article_context.items() if key != "sections"} | {"sectionUnits": []}
    sections = article_context["sections"]
    wanted_index = unit.get("sectionIndex")
    wanted_anchor = unit.get("sectionAnchor", "")
    section = next((
        candidate for candidate in sections
        if candidate.get("sectionIndex") == wanted_index and candidate.get("anchor", "") == wanted_anchor
    ), None)
    base = {key: value for key, value in article_context.items() if key != "sections"}
    if section is None:
        return {**base, "status": "locator-mismatch",
                "reason": "section-index-or-anchor-not-found-in-verified-cache", "sectionUnits": []}

    flat_units: list[dict[str, Any]] = []
    for block in section.get("sourceUnits", []):
        for source_unit in block.get("units", []):
            flat_units.append({
                "knowledgeUnitId": source_unit.get("id", ""),
                "blockIndex": source_unit.get("blockIndex", block.get("blockIndex", "")),
                "unitIndex": source_unit.get("unitIndex", ""),
                "tag": source_unit.get("tag", block.get("tag", "")),
                "text": source_unit.get("text", ""),
                "href": source_unit.get("href", block.get("href", "")),
                "src": source_unit.get("src", block.get("src", "")),
                "alt": source_unit.get("alt", block.get("alt", "")),
            })
    focus_index = next((
        index for index, source_unit in enumerate(flat_units)
        if source_unit["knowledgeUnitId"] == unit.get("knowledgeUnitId")
    ), None)
    if focus_index is None:
        return {**base, "status": "locator-mismatch",
                "reason": "knowledge-unit-id-not-found-in-verified-cache-section", "sectionUnits": []}
    focus_unit = flat_units[focus_index]
    if (
        focus_unit["blockIndex"] != unit.get("blockIndex")
        or focus_unit["unitIndex"] != unit.get("unitIndex")
        or focus_unit["tag"] != unit.get("tag")
        or focus_unit["text"] != unit.get("text")
    ):
        return {**base, "status": "locator-mismatch",
                "reason": "unit-id-locator-or-text-does-not-match-verified-cache", "sectionUnits": []}

    kept: list[dict[str, Any]] = []
    used_chars = 0
    truncated = False
    for source_unit in flat_units:
        text = source_unit["text"]
        remaining = _MAX_SECTION_CONTEXT_CHARS - used_chars
        if remaining <= 0:
            truncated = True
            break
        if len(text) > remaining:
            clipped = dict(source_unit)
            clipped["text"] = text[:remaining]
            clipped["truncated"] = True
            kept.append(clipped)
            truncated = True
            break
        kept.append(source_unit)
        used_chars += len(text)
    return {
        **base,
        "status": "verified",
        "sectionHeadingPath": section.get("headingPath", ""),
        "sectionIndex": section.get("sectionIndex"),
        "sectionAnchor": section.get("anchor", ""),
        "sourceUnitCount": len(flat_units),
        "displayedUnitCount": len(kept),
        "focusUnitIndex": focus_index,
        "focusUnitDisplayed": any(row["knowledgeUnitId"] == unit.get("knowledgeUnitId") for row in kept),
        "sectionUnits": kept,
        "sectionUnitsTruncated": truncated,
    }


def build_review_pack(
    root: Path = ROOT,
    *, source: str | None = None,
    article_filter: str | None = None,
    offset: int = 0,
    limit: int = 30,
    sampling_mode: str = "sequential",
) -> dict[str, Any]:
    """Build an offline package containing explicitly pending units only."""
    if type(offset) is not int or offset < 0:
        raise ReviewPackError("offset must be a non-negative integer")
    if type(limit) is not int or limit <= 0:
        raise ReviewPackError("limit must be a positive integer")
    if sampling_mode not in {"sequential", "article-round-robin"}:
        raise ReviewPackError("sampling_mode must be sequential or article-round-robin")
    root = Path(root).resolve()
    if not root.is_dir():
        raise ReviewPackError(f"project root is not a directory: {root}")

    documents: dict[str, Any] = {}
    input_hashes: dict[str, str] = {}
    for name, relative in INPUTS.items():
        document, raw = _read_json(root / relative)
        documents[name] = document
        input_hashes[name] = hashlib.sha256(raw).hexdigest()
    units = _rows(documents["knowledgeUnits"], "units", str(INPUTS["knowledgeUnits"]))
    cards = _rows(documents["cards"], "cards", str(INPUTS["cards"]))
    articles = _rows(documents["articles"], "articles", str(INPUTS["articles"]))
    _require_unique_ids(units, "knowledgeUnitId", "knowledge units")
    _require_unique_ids(cards, "id", "cards")
    _require_unique_reference_ids(units, "cardIds", "knowledge units")
    _require_unique_reference_ids(cards, "knowledgeUnitIds", "cards")
    _validate_articles(articles)

    valid_sources = {row.get("sourceId") for row in articles if isinstance(row.get("sourceId"), str)}
    if source is not None and source not in valid_sources:
        raise ReviewPackError(f"unknown source {source!r}; choose one of: {', '.join(sorted(valid_sources))}")
    articles_by_url = {_url_key(article["url"]): article for article in articles}
    cards_by_id = {card["id"]: card for card in cards}
    cards_by_unit: dict[str, list[str]] = {}
    for card in cards:
        for unit_id in card.get("knowledgeUnitIds", []):
            cards_by_unit.setdefault(unit_id, []).append(card["id"])

    # Filter and paginate before projecting card bodies and computing per-unit hashes.
    matched: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
    for unit in units:
        if unit.get("reviewerDecision") != "pending":
            continue
        if source is not None and unit.get("sourceId") != source:
            continue
        article = articles_by_url.get(_url_key(unit.get("articleUrl")))
        if article_filter and not _article_filter_matches(article_filter, unit, article):
            continue
        matched.append((unit, article))

    if sampling_mode == "article-round-robin":
        grouped: dict[str, list[tuple[dict[str, Any], dict[str, Any] | None]]] = {}
        for pair in matched:
            unit, article = pair
            group_key = _url_key((article or {}).get("url") or unit.get("articleUrl", ""))
            grouped.setdefault(group_key, []).append(pair)
        keys = list(grouped)
        balanced: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
        depth = 0
        while True:
            round_items = [grouped[key][depth] for key in keys if depth < len(grouped[key])]
            if not round_items:
                break
            balanced.extend(round_items)
            depth += 1
        matched = balanced
    selected_pairs = matched[offset:offset + limit]
    selected: list[dict[str, Any]] = []
    article_context_cache: dict[tuple[str, str, str], dict[str, Any]] = {}
    for unit, article in selected_pairs:
        text = unit.get("text")
        if not isinstance(text, str):
            raise ReviewPackError(f"knowledge unit {unit['knowledgeUnitId']} has non-string text")
        linked_cards, missing_card_ids = _linked_cards(unit, cards_by_id, cards_by_unit)
        cache_key = (
            _url_key((article or {}).get("url", "")),
            str((article or {}).get("cache", "")),
            str((article or {}).get("contentHash", "")),
        )
        if cache_key not in article_context_cache:
            article_context_cache[cache_key] = _load_article_context(root, article)
        source_context = _section_context(article_context_cache[cache_key], unit)
        selected.append({
            "knowledgeUnitId": unit["knowledgeUnitId"],
            "sourceId": unit.get("sourceId", ""),
            "article": {
                "title": (article or {}).get("title") or unit.get("articleTitle", ""),
                "url": (article or {}).get("url") or unit.get("articleUrl", ""),
                "id": Path((article or {}).get("cache", "")).stem if (article or {}).get("cache") else "",
                "cache": (article or {}).get("cache", ""),
                "contentHash": (article or {}).get("contentHash", ""),
            },
            "locator": {
                field: unit.get(field, "")
                for field in ("sectionIndex", "sectionHeadingPath", "sectionAnchor", "blockIndex", "unitIndex", "tag", "href", "title", "src", "alt")
            },
            "originalText": text,
            "status": {
                "reviewerDecision": "pending",
                "unitStatus": unit.get("status", "unknown"),
                "machineMappingStatus": unit.get("machineMappingStatus", "unknown"),
                "presentInCurrentSource": unit.get("presentInCurrentSource"),
            },
            "hashes": {
                "sourceSha256": _review_source_sha256(unit),
                "textSha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "storedReviewSourceSha256": unit.get("reviewSourceSha256", ""),
                "storedBodySha256": unit.get("bodySha256", ""),
            },
            "sourceContext": source_context,
            "cards": linked_cards,
            "unresolvedCardIds": missing_card_ids,
            "reviewTemplate": {
                "decision": "pending", "reason": "", "reviewer": "", "examPoints": [],
                "acceptedCardIds": [], "reviewedAt": "",
                "instruction": "仅供离线填写；此模板不是审核决定，也不是可导入的 v2 决定台账。",
            },
        })

    return {
        "schema": PACK_SCHEMA,
        "version": PACK_VERSION,
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "importable": False,
        "notice": "离线待审材料包，不是 import_knowledge_reviews v2 决定台账；pending 模板不构成审核决定或导入许可。",
        "inputs": {
            "sha256": input_hashes,
            "files": {name: relative.as_posix() for name, relative in INPUTS.items()},
        },
        "selection": {
            "source": source, "articleFilter": article_filter,
            "articleFilterSemantics": "exact URL (fragment ignored), exact article cache filename stem or knowledgeUnitId; otherwise case-insensitive substring of article title, URL, section heading path, or original text",
            "offset": offset, "limit": limit,
            "samplingMode": sampling_mode,
            "sampledArticleCount": len({
                _url_key((article or {}).get("url") or unit.get("articleUrl", ""))
                for unit, article in selected_pairs
            }),
            "pendingTotalBeforePagination": len(matched), "itemCount": len(selected),
        },
        "items": selected,
    }


def _escape(value: Any) -> str:
    if isinstance(value, str):
        return html.escape(value, quote=True)
    return html.escape(json.dumps(value, ensure_ascii=False, indent=2), quote=True)


def render_html(pack: dict[str, Any]) -> str:
    """Render package data only as escaped text; never execute data or load remote assets."""
    input_rows = "".join(
        f"<li><code>{_escape(name)}</code>: <code>{_escape(digest)}</code></li>"
        for name, digest in pack["inputs"]["sha256"].items()
    )
    sections: list[str] = []
    for item in pack["items"]:
        article, locator = item["article"], item["locator"]
        cards_html = "".join(
            "<article class=\"card\"><h3>关联卡 <code>" + _escape(card["id"]) + "</code></h3>"
            + "<p><b>状态：</b>" + _escape(card["status"]) + " / " + _escape(card["knowledgeUnitReviewStatus"]) + "</p>"
            + "<h4>问题</h4><pre>" + _escape(card["question"]) + "</pre>"
            + "<h4>答案</h4><pre>" + _escape(card["answer"]) + "</pre></article>"
            for card in item["cards"]
        ) or "<p>未关联到现存卡片。</p>"
        if item["unresolvedCardIds"]:
            cards_html += "<p class=\"warning\">未解析卡片 ID：" + _escape(", ".join(item["unresolvedCardIds"])) + "</p>"
        template = json.dumps(item["reviewTemplate"], ensure_ascii=False, indent=2)
        source_context = item["sourceContext"]
        context_items = source_context.get("sectionUnits", [])
        if source_context.get("status") == "verified":
            context_rows = "".join(
                "<li class=\"source-unit" + (" focus" if source_unit["knowledgeUnitId"] == item["knowledgeUnitId"] else "")
                + "\" data-knowledge-unit-id=\"" + _escape(source_unit["knowledgeUnitId"]) + "\"><code>"
                + _escape(source_unit["tag"]) + " · block " + _escape(source_unit["blockIndex"])
                + " / unit " + _escape(source_unit["unitIndex"]) + "</code>: "
                + _escape(source_unit["text"])
                + (" <b>[本条内容截断]</b>" if source_unit.get("truncated") else "") + "</li>"
                for source_unit in context_items
            )
            truncation_notice = ""
            if source_context.get("sectionUnitsTruncated"):
                truncation_notice = (
                    "<p class=\"warning\">本节上下文受长度限制，仅展示 "
                    + _escape(source_context.get("displayedUnitCount", len(context_items))) + " / "
                    + _escape(source_context.get("sourceUnitCount", 0))
                    + " 个单元；未显示内容不能据此视为已审阅。</p>"
                )
            if not source_context.get("focusUnitDisplayed"):
                truncation_notice += "<p class=\"warning\">当前知识单元不在已展示的上下文片段中，不能依此确认其局部上下文。</p>"
            context_html = (
                "<details><summary>缓存核验后的本节提取上下文（已显示 "
                + _escape(source_context.get("displayedUnitCount", len(context_items))) + " / "
                + _escape(source_context["sourceUnitCount"]) + " 个单元）</summary>"
                + "<p>文章正文哈希与清单匹配；缓存 HTML SHA-256：<code>"
                + _escape(source_context["cacheHtmlSha256"]) + "</code></p>"
                + truncation_notice + "<ol>" + context_rows + "</ol></details>"
            )
        else:
            context_html = (
                "<p class=\"warning\">整节上下文无法验证："
                + _escape(source_context.get("status", "unknown")) + " / "
                + _escape(source_context.get("reason", "unknown")) + "</p>"
            )
        sections.append(
            "<section class=\"unit\"><h2>知识单元 <code>" + _escape(item["knowledgeUnitId"]) + "</code></h2>"
            + "<p><b>来源：</b>" + _escape(item["sourceId"]) + " · <b>文章：</b>" + _escape(article["title"])
            + " · <b>文章 ID：</b><code>" + _escape(article["id"]) + "</code> · <b>URL：</b><code>"
            + _escape(article["url"]) + "</code></p><p><b>定位：</b>章节 " + _escape(locator["sectionIndex"])
            + " / " + _escape(locator["sectionHeadingPath"]) + " / 锚点 <code>" + _escape(locator["sectionAnchor"])
            + "</code> / block " + _escape(locator["blockIndex"]) + " / unit " + _escape(locator["unitIndex"])
            + " / tag <code>" + _escape(locator["tag"]) + "</code></p><p><b>审核：</b>pending（待审、未批准） · <b>单元状态：</b>"
            + _escape(item["status"]["unitStatus"]) + "</p><h3>原文</h3><pre>" + _escape(item["originalText"])
            + "</pre><p><b>source SHA-256：</b><code>" + _escape(item["hashes"]["sourceSha256"])
            + "</code><br><b>text SHA-256：</b><code>" + _escape(item["hashes"]["textSha256"])
            + "</code></p><h3>本节上下文</h3>" + context_html + "<h3>关联卡片</h3>" + cards_html
            + "<details><summary>待填写模板（空白决定；不是可导入记录）</summary><pre>" + _escape(template)
            + "</pre></details></section>"
        )
    return (
        "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>CodeBrick 离线待审包</title>"
        "<style>:root{color-scheme:light dark;font:16px/1.6 system-ui,sans-serif}body{max-width:1000px;margin:2rem auto;padding:0 1rem}"
        "pre{white-space:pre-wrap;overflow-wrap:anywhere;padding:1rem;background:#8882;border-radius:.5rem}code{overflow-wrap:anywhere}"
        ".unit,.card{border:1px solid #8886;border-radius:.7rem;padding:1rem;margin:1.2rem 0}.source-unit.focus{background:#ffda7a66;outline:2px solid #c98200}.warning{color:#b44}</style>"
        "</head><body><h1>CodeBrick 离线知识单元待审包</h1><p class=\"warning\">"
        + _escape(pack["notice"]) + "</p><p>Schema：<code>" + _escape(pack["schema"])
        + "</code> · 条目：" + _escape(pack["selection"]["itemCount"])
        + "</p><h2>输入文件 SHA-256</h2><ul>" + input_rows + "</ul>"
        "<p>可完全离线打开；所有来源内容均作为转义文本显示，无外部脚本、无自动审核或批准功能。</p>"
        + "".join(sections) + "</body></html>\n"
    )


def _validate_output_path(root: Path, output: Path) -> Path:
    root = Path(root).resolve()
    requested = Path(output) if Path(output).is_absolute() else root / Path(output)
    if requested.resolve(strict=False) in {(root / path).resolve(strict=False) for path in INPUTS.values()}:
        raise ReviewPackError("output path must not point to an input data file")
    if requested.is_symlink() or requested.exists():
        raise ReviewPackError(f"refusing to overwrite existing output: {requested}")
    parent = requested.parent.resolve(strict=False)
    resolved_root = root
    try:
        parent.relative_to(resolved_root)
    except ValueError as exc:
        raise ReviewPackError("output path must stay inside the project root") from exc
    output = parent / requested.name
    if output in {(root / path).resolve(strict=False) for path in INPUTS.values()}:
        raise ReviewPackError("output path must not point to an input data file")
    if output.suffix.casefold() not in {".json", ".html"}:
        raise ReviewPackError("output path must end in .json or .html")
    if not parent.is_dir():
        raise ReviewPackError(f"output directory does not exist: {parent}")
    if output.exists() or output.is_symlink():
        raise ReviewPackError(f"refusing to overwrite existing output: {output}")
    return output


def write_review_pack(root: Path, pack: dict[str, Any], output: Path) -> Path:
    root = Path(root).resolve()
    output = _validate_output_path(root, Path(output))
    payload = (
        render_html(pack).encode("utf-8") if output.suffix.casefold() == ".html"
        else (json.dumps(pack, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )
    try:
        descriptor = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666)
    except FileExistsError as exc:
        raise ReviewPackError(f"refusing to overwrite existing output: {output}") from exc
    except OSError as exc:
        raise ReviewPackError(f"cannot create output {output}: {exc}") from exc
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
    except OSError as exc:
        try:
            output.unlink()
        except OSError:
            pass
        raise ReviewPackError(f"failed writing output {output}: {exc}") from exc
    return output


def _nonnegative(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def _positive(value: str) -> int:
    parsed = _nonnegative(value)
    if parsed == 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export a small offline review pack from pending CodeBrick knowledge units.")
    parser.add_argument("--source", help="filter by exact sourceId (os, co, cn, ds)")
    parser.add_argument(
        "--article",
        dest="article_filter",
        help="exact URL (fragment ignored), exact article cache filename stem or knowledgeUnitId; otherwise case-insensitive substring of title, URL, section heading, or unit text",
    )
    parser.add_argument("--offset", type=_nonnegative, default=0, help="zero-based offset (default: 0)")
    parser.add_argument("--limit", type=_positive, default=30, help="maximum items (default: 30)")
    parser.add_argument(
        "--sampling-mode",
        choices=("sequential", "article-round-robin"),
        default="sequential",
        help="selection order: sequential or spread the first item from each article before the next round",
    )
    parser.add_argument("--output", type=Path, default=Path("exports/review-pack.json"), help="new .json or .html file; --apply is required to write")
    parser.add_argument("--apply", action="store_true", help="write output (never overwrite; default is dry-run)")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve()
        pack = build_review_pack(
            root, source=args.source, article_filter=args.article_filter, offset=args.offset,
            limit=args.limit, sampling_mode=args.sampling_mode,
        )
        result = {
            "mode": "apply" if args.apply else "dry-run",
            "schema": PACK_SCHEMA,
            "pendingTotalBeforePagination": pack["selection"]["pendingTotalBeforePagination"],
            "itemCount": pack["selection"]["itemCount"],
            "samplingMode": pack["selection"]["samplingMode"],
            "sampledArticleCount": pack["selection"]["sampledArticleCount"],
            "inputSha256": pack["inputs"]["sha256"],
            "output": str((args.output if args.output.is_absolute() else root / args.output).resolve(strict=False)),
            "written": False,
        }
        if args.apply:
            result["output"] = str(write_review_pack(root, pack, args.output))
            result["written"] = True
        else:
            _validate_output_path(root, args.output)
            result["notice"] = "dry-run：未写入文件。显式传入 --apply 才会写入。"
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except (ReviewPackError, OSError) as exc:
        print(f"导出拒绝：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
