from __future__ import annotations

"""Read-only DOM triage for sections with zero extracted source blocks.

Reads the existing coverage report, article manifest, and cached HTML only.
Writes only the explicitly selected triage JSON and Markdown outputs.
No source data, cards, or review states are modified.
"""

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

try:
    from .sync_sources import Node, Tree, clean, parse_article, sections, text, walk
except ImportError:  # direct script execution
    from sync_sources import Node, Tree, clean, parse_article, sections, text, walk

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COVERAGE = ROOT / "data" / "reports" / "coverage.json"
DEFAULT_ARTICLES = ROOT / "data" / "articles.json"
DEFAULT_CACHE = ROOT / ".cache" / "html"
DEFAULT_JSON = ROOT / "data" / "reports" / "empty-section-triage-2026-11-20.json"
DEFAULT_MARKDOWN = ROOT / "data" / "reports" / "empty-section-triage-2026-11-20.md"

CATEGORY_LABELS = {
    "empty_parent_with_descendant_practice_links": "空父标题；后继子树存在真题链接",
    "same_level_exam_component_followed_by_related_links": "真题组件标题；后继同级组件有真题链接",
    "empty_parent_with_deeper_heading_unverified": "空父标题；存在更深标题，子树完整性未验收",
    "dynamic_component_static_skeleton": "动态组件静态骨架；加载内容未核实",
    "empty_practice_section_without_static_questions": "真题练习标题；缓存无题目链接，原因未定",
    "empty_section_without_static_evidence": "无静态正文且无上述结构证据；原因未定",
    "unresolved": "证据不足或定位/缓存校验失败",
}

HEADING_TAGS = {"h2", "h3", "h4", "h5", "h6"}
SEMANTIC_TAGS = HEADING_TAGS | {
    "h1", "p", "li", "ul", "ol", "blockquote", "pre", "table",
    "svg", "canvas", "math", "a", "img",
}
SKIP_TAGS = {"script", "style", "noscript", "button", "nav"}


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_heading(value: str) -> str:
    return clean(value).strip()


def _flatten_with_parents(root: Node) -> tuple[list[Node], dict[int, Node | None]]:
    nodes: list[Node] = []
    parents: dict[int, Node | None] = {}

    def visit(node: Node, parent: Node | None) -> None:
        nodes.append(node)
        parents[id(node)] = parent
        for child in node.children:
            if isinstance(child, Node):
                visit(child, node)

    visit(root, None)
    return nodes, parents


def _has_semantic_child(node: Node) -> bool:
    for child in node.children:
        if not isinstance(child, Node) or child.tag in SKIP_TAGS:
            continue
        if child.tag in SEMANTIC_TAGS or _has_semantic_child(child):
            return True
    return False


def _is_parser_capture(node: Node) -> bool:
    if node.tag in SKIP_TAGS:
        return False
    if node.tag == "a":
        classes = set(node.attrs.get("class", "").split())
        return "header-anchor" not in classes and node.attrs.get("aria-hidden") != "true"
    if node.tag in SEMANTIC_TAGS or node.tag == "img":
        return True
    if node.tag == "span":
        return node.attrs.get("aria-hidden") != "true" and not _has_semantic_child(node)
    return bool(node.attrs.get("aria-label") or node.attrs.get("role") == "img") and not _has_semantic_child(node)


def _captured_nodes(nodes: list[Node], parents: dict[int, Node | None], start: int, end: int) -> list[Node]:
    """Approximate sync_sources' semantic traversal on a flat DOM interval."""
    region = nodes[start:end]
    region_ids = {id(node) for node in region}
    captures: list[Node] = []
    for node in region:
        if not _is_parser_capture(node):
            continue
        parent = parents.get(id(node))
        skipped_ancestor = False
        while parent is not None:
            if parent.tag in SKIP_TAGS:
                skipped_ancestor = True
                break
            parent = parents.get(id(parent))
        if skipped_ancestor:
            continue
        parent = parents.get(id(node))
        shadowed = False
        while parent is not None and id(parent) in region_ids:
            if _is_parser_capture(parent):
                shadowed = True
                break
            parent = parents.get(id(parent))
        if not shadowed:
            captures.append(node)
    return captures


def _heading_bounds(nodes: list[Node], heading_index: int, level: int) -> tuple[int, int]:
    direct_end = len(nodes)
    subtree_end = len(nodes)
    for index in range(heading_index + 1, len(nodes)):
        node = nodes[index]
        if node.tag not in HEADING_TAGS:
            continue
        next_level = int(node.tag[1])
        if direct_end == len(nodes):
            direct_end = index
        if next_level <= level:
            subtree_end = index
            break
    return direct_end, subtree_end


def _short_dom_text(node: Node, limit: int = 180) -> str:
    value = clean(text(node))
    return value[:limit] + ("…" if len(value) > limit else "")


def _practice_links(nodes: list[Node], start: int, end: int) -> list[dict[str, str]]:
    result = []
    for node in nodes[start:end]:
        if node.tag != "a":
            continue
        href = clean(node.attrs.get("href", ""))
        if "/practice/q/" not in href:
            continue
        result.append({"text": _short_dom_text(node, 100), "href": href})
    return result


def _dynamic_evidence(nodes: list[Node], start: int, end: int) -> list[dict[str, str]]:
    result = []
    seen: set[tuple[str, str]] = set()
    for node in nodes[start:end]:
        classes = [name for name in node.attrs.get("class", "").split() if name.startswith("algo-embed-")]
        if not classes and node.tag != "iframe":
            continue
        selector = "." + ".".join(classes) if classes else "iframe"
        short = _short_dom_text(node, 140)
        key = (selector, short)
        if key in seen:
            continue
        seen.add(key)
        result.append({"tag": node.tag, "selector": selector, "shortEvidence": short})
    return result


def _find_doc(raw: str) -> Node:
    parser = Tree()
    parser.feed(raw)
    doc = next((node for node in walk(parser.root) if "vp-doc" in node.attrs.get("class", "").split()), None)
    if doc is None:
        raise ValueError("正文容器 .vp-doc 不存在")
    return doc


def _evidence(kind: str, selector: str, short: str, **extra: Any) -> dict[str, Any]:
    return {"type": kind, "selector": selector, "shortEvidence": short, **extra}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _analyze_article(article: dict, cache_root: Path) -> dict[str, Any]:
    cache_rel = article.get("cache")
    if not isinstance(cache_rel, str) or not cache_rel:
        raise ValueError("文章清单缺少缓存相对路径")
    cache_parts = Path(cache_rel).parts
    if len(cache_parts) >= 3 and cache_parts[:2] == (".cache", "html"):
        cache_path = (cache_root / Path(*cache_parts[2:])).resolve()
    else:
        cache_path = (ROOT / cache_rel).resolve()
    resolved_cache_root = cache_root.resolve()
    if not cache_path.is_relative_to(resolved_cache_root):
        raise ValueError("缓存路径越出指定缓存目录")
    if not cache_path.is_file():
        raise FileNotFoundError(f"缓存文件不存在：{cache_rel}")
    raw_bytes = cache_path.read_bytes()
    raw = raw_bytes.decode("utf-8")
    parsed = parse_article(raw, article["url"])
    parsed_digest = _sha256_bytes(json.dumps(parsed["blocks"], ensure_ascii=False).encode("utf-8"))
    expected_digest = article.get("contentHash")
    doc = _find_doc(raw)
    nodes, parents = _flatten_with_parents(doc)
    headings = [(index, node) for index, node in enumerate(nodes) if node.tag in HEADING_TAGS]
    parsed_sections = sections(parsed)
    return {
        "cachePath": cache_path,
        "cacheRelativePath": cache_rel,
        "cacheSha256": _sha256_bytes(raw_bytes),
        "contentHashExpected": expected_digest,
        "contentHashActual": parsed_digest,
        "contentHashMatches": bool(expected_digest and expected_digest == parsed_digest),
        "parsed": parsed,
        "parsedSections": parsed_sections,
        "nodes": nodes,
        "parents": parents,
        "headings": headings,
        "cacheBytesSha256": _sha256_bytes(raw_bytes),
    }


def _category_for(record: dict[str, Any], next_heading: Node | None, sibling_links: list[dict[str, str]]) -> str:
    if record["recordIntegrity"] != "verified" or record["directBodyBlockCount"] != 0:
        return "unresolved"
    if record["dynamicSkeletonCount"]:
        return "dynamic_component_static_skeleton"
    if (
        next_heading is not None
        and next_heading.tag == record["sectionLocator"].get("sectionLevel")
        and "相关真题" in _normalize_heading(text(next_heading))
        and sibling_links
    ):
        return "same_level_exam_component_followed_by_related_links"
    if record["subtreePracticeQuestionLinkCount"]:
        return "empty_parent_with_descendant_practice_links"
    if record["hasDeeperHeading"]:
        return "empty_parent_with_deeper_heading_unverified"
    if _normalize_heading(record["sectionLocator"].get("heading", "")) == "真题练习":
        return "empty_practice_section_without_static_questions"
    if record["directBodyBlockCount"] == 0 and record["subtreeBodyBlockCount"] == 0:
        return "empty_section_without_static_evidence"
    return "unresolved"


def build_report(coverage: dict, article_manifest: dict, cache_root: Path) -> dict[str, Any]:
    articles_by_url = {item.get("url"): item for item in article_manifest.get("articles", [])}
    zero_rows = [row for row in coverage.get("sections", []) if row.get("sourceBlockCount") == 0]
    article_cache: dict[str, dict[str, Any] | Exception] = {}
    records: list[dict[str, Any]] = []

    for row in zero_rows:
        url = row.get("articleUrl", "")
        article = articles_by_url.get(url)
        evidence: list[dict[str, Any]] = []
        integrity = "verified"
        analysis: dict[str, Any] | None = None
        if article is None:
            integrity = "unresolved"
            evidence.append(_evidence("cache-manifest-missing", "data/articles.json", "未找到与文章 URL 精确匹配的缓存清单记录"))
        else:
            if url not in article_cache:
                try:
                    article_cache[url] = _analyze_article(article, cache_root)
                except Exception as exc:  # retain this row as unresolved, never abort the batch
                    article_cache[url] = exc
            cached = article_cache[url]
            if isinstance(cached, Exception):
                integrity = "unresolved"
                evidence.append(_evidence("cache-or-parse-error", article.get("cache", ""), str(cached)[:180]))
            else:
                analysis = cached
                if not analysis["contentHashMatches"]:
                    integrity = "unresolved"
                    evidence.append(_evidence(
                        "cache-content-hash-mismatch", analysis["cacheRelativePath"],
                        f"manifest={analysis['contentHashExpected'] or 'missing'}; parsed={analysis['contentHashActual']}",
                    ))

        section_index = row.get("sectionIndex")
        parsed_section = None
        heading_node = None
        heading_position = None
        direct_count = subtree_count = direct_link_count = subtree_link_count = 0
        direct_links: list[dict[str, str]] = []
        subtree_links: list[dict[str, str]] = []
        direct_dynamic: list[dict[str, str]] = []
        subtree_dynamic: list[dict[str, str]] = []
        direct_skeleton_count = subtree_skeleton_count = 0
        direct_iframe_count = subtree_iframe_count = 0
        has_deeper = False
        deeper_heading = None
        next_heading = None
        next_heading_record = None
        sibling_links: list[dict[str, str]] = []
        locator_matches = False

        if analysis is not None and isinstance(section_index, int) and 1 <= section_index <= len(analysis["parsedSections"]):
            parsed_section = analysis["parsedSections"][section_index - 1]
            locator_matches = (
                parsed_section.get("heading") == row.get("sectionHeading")
                and parsed_section.get("headingPath", parsed_section.get("heading")) == row.get("sectionHeadingPath")
                and parsed_section.get("anchor", "") == row.get("sectionAnchor", "")
            )
            candidates = [
                (index, node) for index, node in analysis["headings"]
                if node.attrs.get("id", "") == row.get("sectionAnchor", "")
                and _normalize_heading(text(node)) == _normalize_heading(row.get("sectionHeading", ""))
            ]
            if locator_matches and len(candidates) == 1:
                heading_position, heading_node = candidates[0]
            else:
                integrity = "unresolved"
                evidence.append(_evidence(
                    "section-locator-ambiguous-or-mismatched", "h2–h6[id + heading text]",
                    f"coverage locator exact match={locator_matches}; matching DOM heading candidates={len(candidates)}",
                ))

        if analysis is not None and heading_node is not None and heading_position is not None:
            level = int(heading_node.tag[1])
            direct_end, subtree_end = _heading_bounds(analysis["nodes"], heading_position, level)
            direct_start = heading_position + 1
            direct_captures = _captured_nodes(analysis["nodes"], analysis["parents"], direct_start, direct_end)
            subtree_captures = _captured_nodes(analysis["nodes"], analysis["parents"], direct_start, subtree_end)
            direct_count = len(direct_captures)
            subtree_count = len(subtree_captures)
            direct_links = _practice_links(analysis["nodes"], direct_start, direct_end)
            subtree_links = _practice_links(analysis["nodes"], direct_start, subtree_end)
            direct_link_count = len(direct_links)
            subtree_link_count = len(subtree_links)
            direct_dynamic = _dynamic_evidence(analysis["nodes"], direct_start, direct_end)
            subtree_dynamic = _dynamic_evidence(analysis["nodes"], direct_start, subtree_end)
            direct_skeleton_count = sum(".algo-embed-skeleton" in item["selector"] for item in direct_dynamic)
            subtree_skeleton_count = sum(".algo-embed-skeleton" in item["selector"] for item in subtree_dynamic)
            direct_iframe_count = sum(item["tag"] == "iframe" for item in direct_dynamic)
            subtree_iframe_count = sum(item["tag"] == "iframe" for item in subtree_dynamic)
            for index, candidate in analysis["headings"]:
                if heading_position < index < subtree_end and int(candidate.tag[1]) > level:
                    has_deeper = True
                    deeper_heading = candidate
                    break
            next_any = next(((index, node) for index, node in analysis["headings"] if index > heading_position), None)
            if next_any:
                next_index, next_heading = next_any
                next_heading_record = {"tag": next_heading.tag, "id": next_heading.attrs.get("id", ""), "text": _short_dom_text(next_heading)}
                next_level = int(next_heading.tag[1])
                if next_level == level:
                    sibling_direct_end, sibling_subtree_end = _heading_bounds(analysis["nodes"], next_index, next_level)
                    sibling_links = _practice_links(analysis["nodes"], next_index + 1, sibling_subtree_end)

            evidence.append(_evidence(
                "section-heading", f"{heading_node.tag}#{heading_node.attrs.get('id', '')}",
                _short_dom_text(heading_node), sectionLocatorMatches=locator_matches,
            ))
            if has_deeper:
                evidence.append(_evidence(
                    "deeper-heading", f"{deeper_heading.tag}#{deeper_heading.attrs.get('id', '')}",
                    _short_dom_text(deeper_heading),
                ))
            if direct_links or subtree_links:
                sample_links = (direct_links or subtree_links)[:3]
                evidence.append(_evidence(
                    "practice-question-links", "a[href*='/practice/q/']",
                    f"直接区间 {direct_link_count} 条；子树区间 {subtree_link_count} 条",
                    samples=sample_links,
                ))
            if next_heading_record and sibling_links:
                evidence.append(_evidence(
                    "next-same-level-exam-component", f"{next_heading_record['tag']}#{next_heading_record['id']}",
                    next_heading_record["text"], siblingQuestionLinkCount=len(sibling_links), samples=sibling_links[:3],
                ))
            if direct_dynamic or subtree_dynamic:
                evidence.append(_evidence(
                    "dynamic-embed-skeleton", ".algo-embed-* / iframe",
                    f"直接区间 skeleton={direct_skeleton_count}、组件标记={len(direct_dynamic)}、iframe={direct_iframe_count}；子树 skeleton={subtree_skeleton_count}、组件标记={len(subtree_dynamic)}、iframe={subtree_iframe_count}",
                    directSamples=direct_dynamic[:5], subtreeSamples=subtree_dynamic[:5],
                ))
            if direct_count:
                evidence.append(_evidence(
                    "parser-visible-direct-body", "DOM semantic elements",
                    f"直接区间存在 {direct_count} 个可见语义节点；与 coverage 的零块状态不一致，需人工核对",
                ))

        record = {
            "sourceId": row.get("sourceId"),
            "sourceName": row.get("sourceName"),
            "articleTitle": row.get("articleTitle"),
            "articleUrl": url,
            "sectionIndex": section_index,
            "sectionLocator": {
                "heading": row.get("sectionHeading"),
                "headingPath": row.get("sectionHeadingPath"),
                "anchor": row.get("sectionAnchor"),
                "sectionLevel": heading_node.tag if heading_node else None,
                "coverageStatus": row.get("status"),
                "coverageSourceBlockCount": row.get("sourceBlockCount"),
            },
            "cache": {
                "relativePath": analysis.get("cacheRelativePath") if analysis else (article.get("cache") if article else None),
                "rawHtmlSha256": analysis.get("cacheSha256") if analysis else None,
                "manifestContentHash": analysis.get("contentHashExpected") if analysis else None,
                "parsedContentHash": analysis.get("contentHashActual") if analysis else None,
                "contentHashMatches": analysis.get("contentHashMatches") if analysis else False,
            },
            "recordIntegrity": integrity,
            "parserSectionLocatorMatches": locator_matches,
            "directBodyBlockCount": direct_count,
            "subtreeBodyBlockCount": subtree_count,
            "directPracticeQuestionLinkCount": direct_link_count,
            "subtreePracticeQuestionLinkCount": subtree_link_count,
            "practiceQuestionLinks": {"direct": direct_links, "subtree": subtree_links},
            "dynamicSkeletonCount": direct_skeleton_count,
            "dynamicMarkerCount": len(direct_dynamic),
            "iframeCount": direct_iframe_count,
            "dynamicSkeletons": {"direct": direct_dynamic, "subtree": subtree_dynamic},
            "hasDeeperHeading": has_deeper,
            "nextHeading": next_heading_record,
            "sameLevelFollowingPracticeQuestionLinkCount": len(sibling_links),
            "domEvidence": evidence,
            "resolutionStatus": "unresolved",
            "autoCloseAllowed": False,
        }
        record["triageClass"] = _category_for(record, next_heading, sibling_links)
        record["triageClassLabel"] = CATEGORY_LABELS[record["triageClass"]]
        records.append(record)

    counts_by_class = Counter(record["triageClass"] for record in records)
    counts_by_source = {
        source_id: dict(Counter(record["triageClass"] for record in records if record["sourceId"] == source_id))
        for source_id in ("os", "co", "cn", "ds")
    }
    per_source_totals = Counter(record["sourceId"] for record in records)
    articles_used = {record["articleUrl"] for record in records}
    all_cache_hashes_match = all(record["cache"]["contentHashMatches"] for record in records)
    all_locators_match = all(record["parserSectionLocatorMatches"] for record in records)
    return {
        "schema": "codebrick-empty-section-dom-triage",
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "diagnosticScope": {
            "description": "只读证据分诊；结果不作内容验收，不自动关闭任何章节。",
            "targetCoverageSourceBlockCount": 0,
            "recordCount": len(records),
            "uniqueArticleCount": len(articles_used),
            "allRowsRemainUnresolved": all(record["resolutionStatus"] == "unresolved" for record in records),
            "autoClosedRecordCount": 0,
            "cacheHashVerifiedRecordCount": sum(bool(record["cache"]["contentHashMatches"]) for record in records),
            "locatorVerifiedRecordCount": sum(bool(record["parserSectionLocatorMatches"]) for record in records),
            "allCacheHashesMatch": all_cache_hashes_match,
            "allLocatorsMatch": all_locators_match,
        },
        "inputFiles": {
            "coverage": {"path": str(DEFAULT_COVERAGE.relative_to(ROOT)), "sha256": _sha256_file(DEFAULT_COVERAGE) if DEFAULT_COVERAGE.is_file() else None},
            "articleManifest": {"path": str(DEFAULT_ARTICLES.relative_to(ROOT)), "sha256": _sha256_file(DEFAULT_ARTICLES) if DEFAULT_ARTICLES.is_file() else None},
        },
        "countsBySource": {source: {"total": per_source_totals.get(source, 0), "byClass": counts_by_source[source]} for source in ("os", "co", "cn", "ds")},
        "countsByClass": {key: counts_by_class.get(key, 0) for key in CATEGORY_LABELS},
        "records": records,
    }


def render_markdown(report: dict[str, Any]) -> str:
    scope = report["diagnosticScope"]
    lines = [
        "# 416 个 sourceBlockCount=0 章节：只读 DOM 证据分诊",
        "",
        f"- 生成时间（UTC）：`{report['generatedAt']}`",
        f"- 目标记录：**{scope['recordCount']}**；涉及缓存文章：**{scope['uniqueArticleCount']}**。",
        f"- 缓存内容哈希一致：**{scope['cacheHashVerifiedRecordCount']}/{scope['recordCount']}**；章节 locator 核对一致：**{scope['locatorVerifiedRecordCount']}/{scope['recordCount']}**。",
        "- **所有记录 resolutionStatus 均为 `unresolved`；自动关闭数为 0。**分类只描述缓存中观察到的结构，不表示内容完整、可忽略或已验收。",
        "- 题目链接只证明静态 HTML 中存在索引链接；本报告不验证题面、答案、解析或真题出处。动态骨架不代表已拿到交互内容。",
        "",
        "## 分类摘要（按证据规则重新计算）",
        "",
        "| 分类 | OS | CO | CN | DS | 合计 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for class_id, label in CATEGORY_LABELS.items():
        values = [report["countsBySource"][source]["byClass"].get(class_id, 0) for source in ("os", "co", "cn", "ds")]
        lines.append(f"| {label} (`{class_id}`) | " + " | ".join(map(str, values)) + f" | {report['countsByClass'].get(class_id, 0)} |")
    lines.extend([
        "| **合计** | " + " | ".join(str(report["countsBySource"][source]["total"]) for source in ("os", "co", "cn", "ds")) + f" | **{scope['recordCount']}** |",
        "",
        "## 逐条记录",
        "",
        "每行 locator 是 `articleUrl#anchor` + `sectionIndex` + heading path；JSON 中保留逐条 DOM 证据、直接区间/子树计数、题目链接与动态骨架样本、缓存校验结果。",
        "",
        "| # | 科目 | 文章 / 章节 | sectionIndex | 分类 | 直接块 | 子树块 | 直接/子树题链 | 动态骨架 | locator/缓存 | 短 DOM 证据 |",
        "|---:|---|---|---:|---|---:|---:|---:|---:|---|---|",
    ])
    for index, record in enumerate(report["records"], 1):
        locator = record["articleUrl"] + ("#" + str(record["sectionLocator"].get("anchor")) if record["sectionLocator"].get("anchor") else "")
        label = record["triageClassLabel"].replace("|", "\\|")
        heading = str(record["sectionLocator"].get("headingPath") or record["sectionLocator"].get("heading") or "").replace("|", "\\|")
        snippets = "；".join(item["shortEvidence"].replace("|", "\\|") for item in record["domEvidence"][:2]) or "无额外 DOM 证据"
        integrity = f"locator={'✓' if record['parserSectionLocatorMatches'] else '未核实'} / hash={'✓' if record['cache']['contentHashMatches'] else '未核实'}"
        lines.append(
            f"| {index} | {record.get('sourceId')} | [{record.get('articleTitle')} — {heading}]({locator}) | {record.get('sectionIndex')} | {label} | "
            f"{record['directBodyBlockCount']} | {record['subtreeBodyBlockCount']} | {record['directPracticeQuestionLinkCount']}/{record['subtreePracticeQuestionLinkCount']} | "
            f"{record['dynamicSkeletonCount']} | {integrity} | {snippets} |"
        )
    lines.extend([
        "",
        "## 判读边界与复跑",
        "",
        "- `sourceBlockCount` 是覆盖报告中的既有解析器产物；本分诊使用同一版本的本地 `sync_sources` 解析器校验缓存哈希和 section locator，并据缓存 DOM 重新测量标题区间。",
        "- “直接区间”到下一个任意级别标题；“子树”延伸至下一个同级或更高级标题。题目链接只匹配 `a[href*='/practice/q/']`。动态骨架按 `.algo-embed-*` 与 iframe 记录。",
        "- `empty_parent_with_descendant_practice_links`、同级组件关联等属于结构证据；父标题本身仍未解决。任何 `unresolved` 都需继续人工查证，不允许据此批量关闭。",
        "- 离线重跑（项目根目录 PowerShell）：",
        "  ```powershell",
        "  python -B -X utf8 scripts/diagnose_empty_sections.py",
        "  python -B -X utf8 -m unittest tests.test_diagnose_empty_sections -v",
        "  ```",
        "- 脚本只读 `data/reports/coverage.json`、`data/articles.json` 与 `.cache/html/`；仅写本 JSON/Markdown 报告。若更改输入或输出位置，可用 `--coverage`、`--articles`、`--cache-root`、`--json-output`、`--markdown-output` 指定。",
        "",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="只读诊断 sourceBlockCount=0 章节的缓存 DOM 证据")
    parser.add_argument("--coverage", type=Path, default=DEFAULT_COVERAGE)
    parser.add_argument("--articles", type=Path, default=DEFAULT_ARTICLES)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN)
    args = parser.parse_args(argv)
    coverage = _load_json(args.coverage)
    manifest = _load_json(args.articles)
    report = build_report(coverage, manifest, args.cache_root)
    report["inputFiles"] = {
        "coverage": {"path": str(args.coverage), "sha256": _sha256_file(args.coverage)},
        "articleManifest": {"path": str(args.articles), "sha256": _sha256_file(args.articles)},
    }
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown_output.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"recordCount": report["diagnosticScope"]["recordCount"], "countsBySource": report["countsBySource"], "countsByClass": report["countsByClass"], "cacheHashVerifiedRecordCount": report["diagnosticScope"]["cacheHashVerifiedRecordCount"], "locatorVerifiedRecordCount": report["diagnosticScope"]["locatorVerifiedRecordCount"], "autoClosedRecordCount": report["diagnosticScope"]["autoClosedRecordCount"], "json": str(args.json_output), "markdown": str(args.markdown_output)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


