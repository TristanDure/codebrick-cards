"""Deterministic offline generator for review-only atomic flashcard candidates.
Dry-run is read-only. --apply writes reports and reconciles only owned candidates;
never edits review ledgers or approves cards.
"""
from __future__ import annotations
import argparse, hashlib, json, re, sys, tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
ROOT = Path(__file__).resolve().parents[1]
try:
    from scripts import sync_sources
except ModuleNotFoundError as exc:
    # Direct execution puts scripts/ on sys.path rather than the project root.
    if exc.name not in {"scripts", "scripts.sync_sources"}:
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import sync_sources
ORIGIN = "atomic-source-candidate"
VERSION = 2
_MAX_RECALL_ANSWER_CHARS = 240
_UNRESOLVED_MARKUP = re.compile(r"\[(?:SVG公式/图示|MathML公式|图片需人工核对|交互图示)(?:\s*[:：][^\]]*)?\]", re.I)
_OWNED = {"sourceId", "articlePath", "articleTitle", "articleUrl", "section", "sectionHeadingPath", "sectionAnchor", "sectionIndex", "knowledgeUnitIds", "knowledgeUnitReviewStatus", "provenance", "examPoints", "auditFlags", "question", "answer", "generatedQuestion", "generatedAnswer", "evidence", "reviewReason", "origin", "generatorVersion", "sourceHash", "sourceContentHash", "candidateKind", "candidateStrategy", "sourceUnitId", "sourceFragmentIndex", "sourceTextHash", "clozeText"}
_PLACEHOLDER = re.compile(r"(?:需人工核对|内容未能可靠提取|原文内容未能可靠提取|交互图示|图片需人工核对|MathML公式需人工核对|SVG公式/图示需人工核对)", re.I)
_NAV = re.compile(r"^(?:返回顶部|目录|上一篇|下一篇|上一页|下一页|点击查看|展开|收起|更多)$")
_LABELS = {"注意", "例如", "比如", "说明", "提示", "结论", "步骤", "答案", "解析", "定义", "性质", "特点", "区别", "总结", "易错点", "考点", "重点", "推导", "证明", "例题", "思考", "问题", "补充", "拓展", "图源", "图片来源", "图表来源", "资料来源", "出处", "参考文献"}
def _hash(data: bytes) -> str: return hashlib.sha256(data).hexdigest()
def _id(*parts: Any) -> str: return "atomic-" + _hash("\x1f".join(map(str, parts)).encode())[:20]
def _cache(root: Path, value: str) -> Path:
    base = root.resolve(); path = (base / value).resolve()
    if path == base or base not in path.parents: raise ValueError("cache path escapes project root")
    return path
def _substantive(text: str, minimum: int = 3) -> bool:
    return len(text.strip()) >= minimum and bool(re.search(r"[\w\u3400-\u9fff]", text)) and not _PLACEHOLDER.search(text) and not _NAV.fullmatch(text.strip())
def _trim(text: str) -> str: return text.strip().strip(" \t\r\n，。；;：:")

_OPEN_TO_CLOSE = {"(": ")", "（": "）", "[": "]", "【": "】", "{": "}", "“": "”", "‘": "’"}
_DANGLING_START = re.compile(r"^(?:又|且|以及|并且|同时|而|因此|所以|该|其|此|这|这些|上述|前述)")
_DANGLING_END = re.compile(r"(?:不只是|不单是|不仅是|不止是|不光是|不但|不仅|不只|不单|又|且|以及|并且|和|与|或|但是|而|但|包括|如下|例如|因为|由于|从而|因此|所以|[+−×÷=<>→⇒—–])$")
_TRACE_FRAGMENT = re.compile(r"(?:\b[ts]\s*=\s*\d|第\s*\d+\s*(?:步|轮)|时间片|取队首|队列\s*[\[【]|(?:图|表)\s*\d+|图源|图片来源|参考文献)", re.I)
_CITATION_FRAGMENT = re.compile(r"(?:\b[a-z]{2,4}[-_]\s*20\d{2}[-_]\d+\b|\b20\d{2}[-–]\d+\b|第\s*[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩIVX\d]+\s*条|(?:图|表)\s*\d+|同书(?:印刷)?\s*p\.?\s*\d+|被考过)", re.I)
_NOISY_SUBJECT = re.compile(r"^(?:算法为|算法是|大纲写|教材写|问|答|答案(?:为|是)?|例如|比如|注意|说明|想清楚|记住|推荐使用流程)|(?:统称|正确答案是|答创建|答：|答\s)")
_CODE_SYNTAX = re.compile(r"(?:#include|\b(?:if|for|while|return|break|continue|int|char|void|bool|float|double|struct|class|def|function)\b|::|->|[{};]|==|<=|>=|!=|\b[A-Za-z_]\w*\s*\([^)]*\)\s*(?:\{|;))")

def _balanced_fragment(text: str) -> bool:
    stack: list[str] = []
    for char in text:
        if char in _OPEN_TO_CLOSE:
            stack.append(_OPEN_TO_CLOSE[char])
        elif char in _OPEN_TO_CLOSE.values():
            if not stack or stack.pop() != char:
                return False
    return not stack

def _complete_fragment(text: str) -> bool:
    value = text.strip()
    return bool(value and not _DANGLING_START.search(value)
                and not _DANGLING_END.search(value) and _balanced_fragment(value))

def _looks_like_code(text: str) -> bool:
    """Conservatively separate source code from ASCII diagrams and unresolved media."""
    return bool(text.strip() and not _UNRESOLVED_MARKUP.search(text) and _CODE_SYNTAX.search(text))

def _safe_pair(subject: str, answer: str) -> bool:
    """Reject fragments that look like a partial prompt, citation, or clipped clause."""
    head = subject.strip()
    if not head or _NOISY_SUBJECT.search(head) or _CITATION_FRAGMENT.search(head + " " + answer):
        return False
    if not _complete_fragment(head) or not _complete_fragment(answer):
        return False
    # A quoted concept name is fine; prose containing nested quotations is not a stable prompt.
    quotes = re.findall(r'["“”]', head)
    if quotes and not (head.startswith("“") and head.endswith("”") and quotes == ["“", "”"]):
        return False
    return True

def _subject(text: str) -> str:
    text = re.sub(r"^(?:(?:\d+|[一二三四五六七八九十]+)[.、)）]\s*|[•●▪-]\s*)", "", text)
    text = re.sub(r"^(?:其中|因此|所以|而|并且|同时|所谓|对于|关于|如果|当|则|其|该|此)", "", text.strip())
    return text.strip(" \t\r\n，。；;：:、")
def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[。！？!?；;])\s*|\n+", text) if s.strip()]
def _semantic(text: str) -> tuple[str, str, str] | None:
    """Only create Q/A when source syntax supplies a recognizable relation."""
    text = text.strip()
    if not _substantive(text, 7) or re.search(r"[?？]\s*$", text): return None
    patterns = [
        (r"^(.{1,36}?)(?:是指|指的是|定义为|被称为|又称为|简称为|称为)(.+)$", "definition", "“{s}”指的是什么？"),
        (r"^(.{2,32}?)是(.{4,220})$", "is-definition", "“{s}”是什么？"),
        (r"^(.{2,32}?)(?:由)(.{3,180}?)(?:组成|构成)[。！!]?\s*$", "composition", "“{s}”由哪些部分组成？"),
        (r"^(.{2,32}?)(?:分为|分成|划分为)(.{3,180})$", "classification", "“{s}”分为哪些类别？"),
        (r"^(.{2,32}?)(?:具有|包括|包含|拥有)(.{3,180})$", "properties", "“{s}”具有/包含哪些内容？"),
        (r"^(.{2,32}?)(?:会导致|导致|使得|从而)(.{3,180})$", "causal-relation", "“{s}”会产生什么结果？"),
    ]
    for pattern, strategy, question in patterns:
        m = re.match(pattern, text)
        if not m: continue
        subject, answer = _subject(m.group(1)), _trim(m.group(2))
        if strategy == "is-definition":
            # Do not turn a negation, predicate clause, trace fragment, or answer choice
            # into a false “what is ...?” definition card.
            if (subject.endswith(("如果", "当", "因为", "由于", "不", "没", "未", "非", "的", "地", "得"))
                    or re.search(r"[，,；;。！？!?—–→⇒]", subject)
                    or _TRACE_FRAGMENT.search(subject) or _TRACE_FRAGMENT.search(answer)):
                continue
        classification_is_specific = True
        if strategy == "classification":
            # A later explanatory comma must not make a single category count as an
            # enumeration (e.g. “分为多级，每一级都是一台机器”).
            category_list = re.split(r"[。；;：:]", answer, maxsplit=1)[0]
            category_items = [part.strip(" \t，,、") for part in re.split(r"(?:、|，|,|和|与|及)", category_list) if part.strip(" \t，,、")]
            category_items_are_specific = len(category_items) >= 2 and all(
                len(item) >= 2 and not re.match(r"^(?:每|各|所有|其中|例如|分别|即|就是)", item)
                and not re.search(r"(?:都是|均是|就是|具有|包括|包含|每一级|每一层)", item)
                for item in category_items
            )
            classification_is_specific = (
                not re.fullmatch(r"(?:共)?[一二三四五六七八九十\d]+(?:种|类|个)?(?:模型|方式|类别|类型|方法|情形|情况|状态|策略|阶段|部分)?[：:]?", answer)
                and category_items_are_specific
            )
        if (_substantive(subject) and _safe_pair(subject, answer)
                and not _DANGLING_START.search(subject)
                and _substantive(answer)
                and classification_is_specific
                and len(answer) <= _MAX_RECALL_ANSWER_CHARS):
            rendered_question = question.format(s=subject)
            if strategy == "classification" and re.search(r"(?:[一二三四五六七八九十\d]+步|步骤)", answer):
                rendered_question = f"“{subject}”包括哪些步骤？"
            return rendered_question, answer, strategy
    m = re.match(r"^(.{2,32}?)(?:通过|利用|采用|依靠|基于)(.{2,120}?)(?:实现|完成|获得|进行)(.{0,100})$", text)
    if m:
        subject, mechanism, outcome = _subject(m.group(1)), _trim(m.group(2)), _trim(m.group(3))
        if (not _TRACE_FRAGMENT.search(subject) and not _TRACE_FRAGMENT.search(mechanism)
                and _substantive(subject) and _safe_pair(subject, mechanism)
                and _substantive(mechanism)
                and len(mechanism) <= _MAX_RECALL_ANSWER_CHARS):
            tail = f"以实现{outcome}" if outcome else ""
            return f"“{subject}”通过什么机制{tail}？", mechanism, "mechanism"
    m = re.match(r"^([^：:]{1,32})[：:](.{4,180})$", text)
    if m:
        subject, answer = _subject(m.group(1)), _trim(m.group(2))
        # Colons also introduce timestamps, traces, citations, and enumerated prose.
        # Keep those ambiguous fragments in the review backlog.
        label_is_concept_like = not re.search(r"\d|[=<>+*/]|\bp\.?\s*\d", subject, re.I)
        if (subject.casefold() not in _LABELS and label_is_concept_like
                and _safe_pair(subject, answer)
                and not _TRACE_FRAGMENT.search(subject) and not _TRACE_FRAGMENT.search(answer)
                and not re.match(r"^(例如|注意|提示|说明|证明|推导|如下|如图|同书)", subject)
                and _complete_fragment(subject) and _substantive(answer)
                and _complete_fragment(answer) and len(answer) <= _MAX_RECALL_ANSWER_CHARS):
            return f"“{subject}”具体指什么？", answer, "label-explanation"
    return None

def _card(source: dict, article: dict, section: dict, sec_i: int, unit: dict,
          fragment_i: int, question: str, answer: str, evidence: str,
          strategy: str, raw_hash: str, parsed_hash: str, kind: str = "qa",
          cloze: str = "") -> dict:
    anchor = section.get("anchor", "") or ""; url = article["url"]
    digest = _hash(evidence.encode()); uid = str(unit["id"])
    cid = _id(ORIGIN, source["id"], url, anchor, sec_i, uid, fragment_i, strategy, digest)
    path = section.get("headingPath") or section.get("heading", "")
    card = {
        "id": cid, "sourceId": source["id"], "articlePath": url,
        "articleTitle": article.get("title", ""), "articleUrl": url + (f"#{anchor}" if anchor else ""),
        "section": section.get("heading", ""), "sectionHeadingPath": path,
        "sectionAnchor": anchor, "sectionIndex": sec_i, "knowledgeUnitIds": [uid],
        "knowledgeUnitReviewStatus": "candidate-unreviewed",
        "provenance": {"articleUrl": url, "sectionAnchor": anchor, "sectionIndex": sec_i,
            "sectionHeadingPath": path, "knowledgeUnitIds": [uid], "sourceHash": raw_hash,
            "sourceContentHash": parsed_hash, "sourceTextHash": digest, "verificationStatus": "not-reviewed"},
        "examPoints": [], "auditFlags": ["machine-generated", "atomic-candidate-needs-human-review"],
        "question": question, "answer": answer, "generatedQuestion": question,
        "generatedAnswer": answer, "evidence": evidence, "status": "needs-review",
        "reviewReason": "atomic-candidate-human-content-and-408-review-required",
        "origin": ORIGIN, "generatorVersion": VERSION, "sourceHash": raw_hash,
        "sourceContentHash": parsed_hash, "candidateKind": kind, "candidateStrategy": strategy,
        "sourceUnitId": uid, "sourceFragmentIndex": fragment_i, "sourceTextHash": digest,
    }
    if cloze: card["clozeText"] = cloze
    return card


def _backlog(report: dict, source: dict, article: dict, section: dict,
             sec_i: int, unit: dict | None, reason: str, detail: str = "") -> None:
    unit = unit or {}
    report["backlog"].append({
        "sourceId": source["id"], "articleUrl": article.get("url", ""),
        "articleTitle": article.get("title", ""), "section": section.get("heading", ""),
        "sectionHeadingPath": section.get("headingPath") or section.get("heading", ""),
        "sectionAnchor": section.get("anchor", ""), "sectionIndex": sec_i,
        "unitId": unit.get("id", ""), "blockIndex": unit.get("blockIndex"),
        "unitIndex": unit.get("unitIndex"), "tag": unit.get("tag", ""),
        "href": unit.get("href", ""), "src": unit.get("src", ""),
        "reason": reason, "detail": detail, "evidence": unit.get("text", ""),
    })


def _units(block: dict, article_url: str, section: dict, sec_i: int) -> list[dict]:
    if isinstance(block.get("units"), list) and block["units"]:
        return [dict(u) for u in block["units"] if isinstance(u, dict)]
    values = block.get("unitTexts") or [block.get("text", "")]; output = []
    for i, value in enumerate(values, 1):
        value = str(value or "")
        output.append({"id": sync_sources.stable_id(article_url, section.get("anchor", ""), str(sec_i),
            str(block.get("blockIndex", "")), str(i), str(block.get("tag", "")), value),
            "tag": block.get("tag", ""), "text": value, "blockIndex": block.get("blockIndex", 0),
            "unitIndex": i, **{k: block.get(k, "") for k in ("href", "title", "class", "src", "alt")}})
    return output


def _audit(report: dict, unit: dict, status: str, reason: str, card: dict | None = None) -> None:
    entry = {"unitId": unit.get("id", ""), "status": status, "reason": reason}
    if card: entry["candidateId"] = card["id"]
    report["unitAudit"].append(entry)


def _table_row(text: str) -> tuple[str, list[str]]:
    match = re.match(r"^(表头|行\s*\d+)\s*[:：]\s*(.*)$", text, re.S)
    return ("header" if match and match.group(1) == "表头" else "row", (match.group(2) if match else text).split("|"))


def _table(report: dict, source: dict, article: dict, section: dict, sec_i: int,
           units: list[dict], raw_hash: str, parsed_hash: str) -> None:
    headers: list[str] = []; rows: list[tuple[dict, list[str]]] = []
    for unit in units:
        kind, cells = _table_row(str(unit.get("text", "")))
        cells = [c.strip() for c in cells]
        if kind == "header" and any(cells):
            if not headers:
                headers = cells; _audit(report, unit, "context-only", "table-column-headers")
            else:
                why = "multiple-table-header-rows"
                _backlog(report, source, article, section, sec_i, unit, why, "多层表头需回看原始表格。")
                _audit(report, unit, "backlog", why)
        else: rows.append((unit, cells))
    if len([h for h in headers if h]) < 2:
        for unit, _ in rows:
            why = "table-header-missing-or-insufficient"
            _backlog(report, source, article, section, sec_i, unit, why, "无法将值可靠绑定到列名。")
            _audit(report, unit, "backlog", why)
        return
    for unit, cells in rows:
        if len(cells) != len(headers) or any(not c for c in cells):
            why = "table-row-column-count-mismatch-or-empty-cell"
            _backlog(report, source, article, section, sec_i, unit, why, f"列头数={len(headers)}，单元格数={len(cells)}。")
            _audit(report, unit, "backlog", why); continue
        if any(_UNRESOLVED_MARKUP.search(cell) for cell in cells):
            why = "table-row-unresolved-visual-content"
            _backlog(report, source, article, section, sec_i, unit, why, "表格单元含有未解析的图示或公式标记。")
            _audit(report, unit, "backlog", why); continue
        recall_fields = [(headers[col].strip(), cells[col]) for col in range(1, len(headers))
                         if headers[col].strip() and _substantive(cells[col], 1)]
        rendered_questions = [f"在“{section.get('headingPath') or section.get('heading')}”的表格中，当{headers[0].strip()}为“{cells[0]}”时，{header}对应什么？"
                              for header, _ in recall_fields]
        if any(len(question) > 280 for question in rendered_questions) or any(
                len(value) > _MAX_RECALL_ANSWER_CHARS for _, value in recall_fields):
            why = "table-recall-cell-too-long"
            _backlog(report, source, article, section, sec_i, unit, why, "至少一个题面超过280字或答案单元格超过240字；整行待人工拆分。")
            _audit(report, unit, "backlog", why); continue
        emitted = 0
        for col in range(1, len(headers)):
            header, value = headers[col].strip(), cells[col]
            if not header or not _substantive(value, 1): continue
            q = f"在“{section.get('headingPath') or section.get('heading')}”的表格中，当{headers[0].strip()}为“{cells[0]}”时，{header}对应什么？"
            card = _card(source, article, section, sec_i, unit, col, q, value,
                str(unit.get("text", "")), "table-row-with-column-context", raw_hash, parsed_hash)
            report["candidates"].append(card); _audit(report, unit, "candidate-generated", card["candidateStrategy"], card)
            emitted += 1
        if not emitted:
            why = "table-row-no-recallable-value"
            _backlog(report, source, article, section, sec_i, unit, why)
            _audit(report, unit, "backlog", why)


def _formula(text: str) -> tuple[str, str] | None:
    match = re.search(r"\[(?:公式|formula)\s*[:：]\s*(.+?)\]", text, re.I | re.S)
    if not match: return None
    formula = match.group(1).strip()
    if len(formula) < 3 or _PLACEHOLDER.search(formula): return None
    context = text[:match.start()].strip(" \t\r\n，。；;：:")
    return formula, context


def _unit(report: dict, source: dict, article: dict, section: dict, sec_i: int,
          unit: dict, previous: list[dict], raw_hash: str, parsed_hash: str) -> None:
    text, tag, uid = str(unit.get("text", "") or ""), str(unit.get("tag", "")).lower(), str(unit.get("id", ""))
    if not text.strip():
        why = "empty-source-unit"; _backlog(report, source, article, section, sec_i, unit, why); _audit(report, unit, "backlog", why); return
    if tag == "table": return
    special = {"img": "image-needs-visual-review", "svg": "svg-diagram-or-formula-needs-review",
        "canvas": "interactive-content-needs-review", "a": "link-target-needs-review",
        "accessible-component": "component-semantics-uncertain", "component-text": "component-semantics-uncertain"}
    if tag in special:
        detail = f"href={unit.get('href', '')}" if tag == "a" else f"alt={unit.get('alt', '')}; src={unit.get('src', '')}" if tag == "img" else ""
        why = special[tag]; _backlog(report, source, article, section, sec_i, unit, why, detail); _audit(report, unit, "backlog", why); return
    if _UNRESOLVED_MARKUP.search(text):
        why = "visual-or-formula-placeholder-needs-review"
        _backlog(report, source, article, section, sec_i, unit, why, "来源文本含有未解析的图示/公式占位标记。")
        _audit(report, unit, "backlog", why); return
    found_formula = _formula(text)
    if found_formula:
        formula, context = found_formula; context = context or section.get("headingPath") or section.get("heading") or "本节"
        cloze = f"{context}：{{{{c1::{formula}}}}}"
        card = _card(source, article, section, sec_i, unit, 1,
            f"公式填空（{context}）：____", formula, text,
            "formula-context-cloze", raw_hash, parsed_hash, "cloze", cloze)
        report["candidates"].append(card); _audit(report, unit, "candidate-generated", card["candidateStrategy"], card); return
    if _PLACEHOLDER.search(text):
        why = "source-placeholder-needs-recovery"; _backlog(report, source, article, section, sec_i, unit, why); _audit(report, unit, "backlog", why); return
    if tag == "math":
        why = "formula-format-unrecognized"; _backlog(report, source, article, section, sec_i, unit, why, "不猜测变量、条件或关系。")
        _audit(report, unit, "backlog", why); return
    if tag == "pre":
        if not _looks_like_code(text):
            why = "preformatted-noncode-needs-review"
            _backlog(report, source, article, section, sec_i, unit, why, "预格式块未呈现明确代码语法，可能是图示、轨迹或公式；回看原文后再决定是否制卡。")
            _audit(report, unit, "backlog", why); return
        idx = int(unit.get("blockIndex", 0) or 0); context = ""
        for other in reversed(previous):
            if int(other.get("blockIndex", 0) or 0) < idx and other.get("tag") in {"p", "blockquote"}:
                candidate_context = str(other.get("text", "")).strip()
                if _substantive(candidate_context, 10) and not _PLACEHOLDER.search(candidate_context):
                    if len(candidate_context) <= 160: context = candidate_context
                    else: context_too_broad = True
                break
        if context and text.strip():
            q = f"根据“{context}”，实现该功能的代码片段是什么？"
            card = _card(source, article, section, sec_i, unit, 1, q, text, text,
                "code-with-adjacent-prose-context", raw_hash, parsed_hash, "code")
            report["candidates"].append(card); _audit(report, unit, "candidate-generated", card["candidateStrategy"], card)
        else:
            why = "code-context-too-broad" if locals().get("context_too_broad") else "code-context-missing"
            detail = "相邻说明超过160字，需人工选择完整题意；不截断拼接。" if why == "code-context-too-broad" else "代码逐字保留，但缺少局部题意。"
            _backlog(report, source, article, section, sec_i, unit, why, detail)
            _audit(report, unit, "backlog", why)
        return
    matched = []
    for n, sentence in enumerate(_sentences(text), 1):
        generated = _semantic(sentence)
        if generated: matched.append((n, sentence, *generated))
    if matched:
        for n, sentence, q, answer, strategy in matched:
            card = _card(source, article, section, sec_i, unit, n, q, answer, sentence.strip(), strategy, raw_hash, parsed_hash)
            report["candidates"].append(card); _audit(report, unit, "candidate-generated", strategy, card)
    else:
        why = "non-teaching-or-navigation-text" if _NAV.fullmatch(text.strip()) else "no-safe-atomic-recall-pattern"
        _backlog(report, source, article, section, sec_i, unit, why, "未匹配到明确主体/关系；原文保留并待人工判断。")
        _audit(report, unit, "backlog", why)

def _restore_code(raw_html: str, parsed: dict) -> dict[int, str]:
    """Recover literal code whitespace from cache while keeping parser block indices."""
    tree = sync_sources.Tree(); tree.feed(raw_html)
    doc = next((n for n in sync_sources.walk(tree.root) if "vp-doc" in n.attrs.get("class", "").split()), None)
    raw_nodes = [n for n in sync_sources.walk(doc) if n.tag == "pre"] if doc else []
    parsed_blocks = [b for b in parsed.get("blocks", []) if b.get("tag") == "pre"]
    result = {}
    for block, node in zip(parsed_blocks, raw_nodes):
        literal = "".join(sync_sources.text(child) for child in node.children).strip("\r\n")
        literal = re.sub(r"\r\n?", "\n", literal)
        result[int(block.get("blockIndex", 0))] = literal
    return result


def _inline_links(raw_html: str, parsed: dict, sections: list[dict]) -> dict[int, list[dict]]:
    """Find anchors flattened into prose/table/list units by the source parser."""
    tree = sync_sources.Tree(); tree.feed(raw_html)
    doc = next((n for n in sync_sources.walk(tree.root)
                if "vp-doc" in n.attrs.get("class", "").split()), None)
    if doc is None:
        return {}

    standalone: dict[int, Counter] = defaultdict(Counter)
    for sec_i, section in enumerate(sections, 1):
        for block in section.get("sourceUnits", []) or []:
            if str(block.get("tag", "")).lower() == "a":
                standalone[sec_i][str(block.get("href", ""))] += 1

    has_intro = bool(sections and sections[0].get("heading") == "导言")
    heading_count = 0
    occurrence_count: Counter = Counter()
    found: dict[int, list[dict]] = defaultdict(list)

    def visit(node: Any, section_i: int) -> None:
        nonlocal heading_count
        if not isinstance(node, sync_sources.Node) or node.tag in sync_sources.SKIP:
            return
        if node.tag in {"h2", "h3", "h4", "h5", "h6"}:
            heading_count += 1
            section_i = heading_count + (1 if has_intro else 0)
        if node.tag == "a" and "header-anchor" not in node.attrs.get("class", "").split() \
                and node.attrs.get("aria-hidden") != "true":
            href = sync_sources.clean(node.attrs.get("href", ""))
            label = sync_sources.clean("".join(sync_sources.text(child) for child in node.children))
            if standalone[section_i][href]:
                standalone[section_i][href] -= 1
            else:
                occurrence_count[section_i] += 1
                section = sections[section_i - 1] if section_i <= len(sections) else {}
                uid = sync_sources.stable_id(str(parsed.get("url", "")),
                    str(section.get("anchor", "")), str(section_i), "inline-link",
                    str(occurrence_count[section_i]), href, label)
                found[section_i].append({"id": uid, "tag": "a", "text": label,
                    "href": href, "blockIndex": None,
                    "unitIndex": occurrence_count[section_i]})
        for child in node.children:
            if isinstance(child, sync_sources.Node):
                visit(child, section_i)

    visit(doc, 1)
    return dict(found)


def build_candidate_set(root: Path = ROOT) -> dict:
    """Parse every local article and section; emit cards and explicit backlog."""
    root = Path(root).resolve()
    manifest_path = root / "data" / "articles.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    articles = manifest.get("articles", []) if isinstance(manifest, dict) else manifest
    if not isinstance(articles, list): raise ValueError("articles.json must contain an articles list")
    sources = {str(s["id"]): s for s in sync_sources.SOURCES}
    report = {"version": 1, "generatorVersion": VERSION, "origin": ORIGIN,
        "offlineOnly": True, "reviewStatus": "needs-review", "claimsFullKnowledgeCoverage": False,
        "notes": ["候选生成不等于知识点已覆盖、卡片已核实或408适用性已验收。",
                  "所有候选均待人工核查；无法安全制卡的单元和章节进入待补清单。"],
        "summary": {}, "sourceSummary": {}, "candidates": [], "backlog": [],
        "sectionBacklog": [], "unitAudit": [], "articleErrors": []}
    for record in sorted(articles, key=lambda a: (str(a.get("sourceId", "")), str(a.get("url", "")))):
        sid, url = str(record.get("sourceId", "")), str(record.get("url", ""))
        source = sources.get(sid); article_meta = {"url": url, "title": record.get("title", "")}
        if source is None:
            report["articleErrors"].append({"sourceId": sid, "articleUrl": url, "reason": "unknown-source-id"}); continue
        try:
            raw = _cache(root, str(record.get("cache", ""))).read_bytes()
            raw_html = raw.decode("utf-8")
            raw_hash = _hash(raw)
            parsed = sync_sources.parse_article(raw_html, url)
            sections = sync_sources.sections(parsed)
            code_by_block = _restore_code(raw_html, parsed)
            inline_links = _inline_links(raw_html, parsed, sections)
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"
            report["articleErrors"].append({"sourceId": sid, "articleUrl": url, "reason": "article-parse-or-cache-error", "detail": detail})
            report["backlog"].append({"sourceId": sid, "articleUrl": url, "articleTitle": record.get("title", ""),
                "section": "", "sectionHeadingPath": "", "sectionAnchor": "", "sectionIndex": 0,
                "unitId": "", "blockIndex": None, "unitIndex": None, "tag": "", "href": "", "src": "",
                "reason": "article-parse-or-cache-error", "detail": detail, "evidence": ""})
            continue
        if not sections:
            sections = [{"heading": "未识别章节结构", "headingPath": "未识别章节结构", "anchor": "", "sourceUnits": []}]
        per_source = report["sourceSummary"].setdefault(sid, {"articles": 0, "sections": 0, "candidates": 0, "backlogUnits": 0})
        per_source["articles"] += 1
        for sec_i, section_value in enumerate(sections, 1):
            section = dict(section_value); per_source["sections"] += 1
            for link in inline_links.get(sec_i, []):
                why = "inline-link-needs-review"
                _backlog(report, source, article_meta, section, sec_i, link, why,
                         f"href={link.get('href', '')}")
                _audit(report, link, "backlog", why)
            flattened = []
            for block_value in section.get("sourceUnits", []) or []:
                block = dict(block_value); block_units = _units(block, url, section, sec_i)
                if str(block.get("tag", "")).lower() == "pre":
                    literal = code_by_block.get(int(block.get("blockIndex", 0) or 0))
                    if literal is not None and block_units:
                        block_units[0]["text"] = literal
                flattened.extend(block_units)
            flattened.sort(key=lambda u: (int(u.get("blockIndex", 0) or 0), int(u.get("unitIndex", 0) or 0)))
            start_count = len(report["candidates"])
            if not flattened:
                why = "empty-section-no-extractable-source-units"
                _backlog(report, source, article_meta, section, sec_i, None, why, "章节没有可解析正文；回看缓存中的图表/交互内容。")
                report["sectionBacklog"].append({"sourceId": sid, "articleUrl": url, "articleTitle": record.get("title", ""),
                    "section": section.get("heading", ""), "sectionHeadingPath": section.get("headingPath") or section.get("heading", ""),
                    "sectionAnchor": section.get("anchor", ""), "sectionIndex": sec_i, "reason": why, "candidateCount": 0})
                continue
            by_block: dict[int, list[dict]] = defaultdict(list)
            for unit in flattened: by_block[int(unit.get("blockIndex", 0) or 0)].append(unit)
            done_tables: set[int] = set(); previous: list[dict] = []
            parsed_hash = str(record.get("contentHash", ""))
            for unit in flattened:
                block_i = int(unit.get("blockIndex", 0) or 0)
                if str(unit.get("tag", "")).lower() == "table":
                    if block_i not in done_tables:
                        _table(report, source, article_meta, section, sec_i, by_block[block_i], raw_hash, parsed_hash)
                        done_tables.add(block_i)
                    previous.append(unit); continue
                _unit(report, source, article_meta, section, sec_i, unit, previous, raw_hash, parsed_hash)
                previous.append(unit)
            emitted = len(report["candidates"]) - start_count
            if not emitted:
                report["sectionBacklog"].append({"sourceId": sid, "articleUrl": url, "articleTitle": record.get("title", ""),
                    "section": section.get("heading", ""), "sectionHeadingPath": section.get("headingPath") or section.get("heading", ""),
                    "sectionAnchor": section.get("anchor", ""), "sectionIndex": sec_i, "reason": "no-candidate-generated", "candidateCount": 0})
    for sid, values in report["sourceSummary"].items():
        values["candidates"] = sum(c["sourceId"] == sid for c in report["candidates"])
        values["backlogUnits"] = sum(b["sourceId"] == sid for b in report["backlog"])
    ids = [c["id"] for c in report["candidates"]]
    duplicates = [i for i, n in Counter(ids).items() if n > 1]
    if duplicates: report["articleErrors"].append({"reason": "duplicate-generated-card-ids", "ids": duplicates[:20]})
    report["summary"] = {"articles": sum(v["articles"] for v in report["sourceSummary"].values()),
        "sections": sum(v["sections"] for v in report["sourceSummary"].values()),
        "candidates": len(report["candidates"]), "backlogUnits": len(report["backlog"]),
        "sectionBacklog": len(report["sectionBacklog"]), "articleErrors": len(report["articleErrors"]),
        "candidateStrategies": dict(Counter(c["candidateStrategy"] for c in report["candidates"])),
        "backlogReasons": dict(Counter(b["reason"] for b in report["backlog"])),
        "allCandidatesNeedsReview": all(c["status"] == "needs-review" for c in report["candidates"]),
        "duplicateCandidateIds": len(duplicates)}
    return report

def reconcile_owned_cards(existing: list[dict], generated: list[dict]) -> dict:
    """Upsert untouched owned candidates; never change review state or other cards."""
    by_id = {str(card.get("id", "")): card for card in existing}
    new_by_id = {card["id"]: card for card in generated}
    output, conflicts, seen = [], [], set()
    for old in existing:
        cid = str(old.get("id", "")); candidate = new_by_id.get(cid)
        if candidate is None:
            output.append(old); continue
        seen.add(cid)
        if old.get("origin") != ORIGIN:
            conflicts.append({"id": cid, "reason": "id-collision-with-non-generator-card-preserved"})
            output.append(old); continue
        edited = any(old.get(field) != old.get(f"generated{field.title()}", old.get(field)) for field in ("question", "answer"))
        if edited or old.get("status") != "needs-review":
            conflicts.append({"id": cid, "reason": "edited-or-reviewed-candidate-preserved"})
            output.append(old); continue
        merged = dict(old)
        for key in _OWNED:
            if key in candidate: merged[key] = candidate[key]
            else: merged.pop(key, None)
        # Status is intentionally not in _OWNED: keep review state byte-for-byte.
        output.append(merged)
    inserted = 0
    for candidate in generated:
        if candidate["id"] in seen or candidate["id"] in by_id: continue
        output.append(dict(candidate)); inserted += 1
    stale = [str(c.get("id", "")) for c in existing if c.get("origin") == ORIGIN and str(c.get("id", "")) not in new_by_id]
    return {"cards": output, "inserted": inserted,
        "updated": sum(1 for c in generated if c["id"] in seen and not any(x["id"] == c["id"] for x in conflicts)),
        "preservedNonGeneratorCards": sum(c.get("origin") != ORIGIN for c in existing),
        "preservedConflicts": conflicts, "staleOwnedCandidatesPreserved": stale}


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); temp = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=path.parent,
                                         prefix=f".{path.name}.", suffix=".tmp", delete=False) as stream:
            temp = Path(stream.name); stream.write(text)
        temp.replace(path)
    finally:
        if temp and temp.exists(): temp.unlink()


def _markdown(report: dict) -> str:
    s = report["summary"]
    lines = ["# 原子记忆卡候选（机器生成，尚未审核）", "",
        "> 离线可重复提取结果不代表知识点覆盖完整，也不代表已通过 408 适用性验收。", "",
        f"- 文章：{s['articles']}", f"- 章节：{s['sections']}", f"- 候选卡：{s['candidates']}",
        f"- 待补知识单元：{s['backlogUnits']}", f"- 无候选章节：{s['sectionBacklog']}",
        f"- 文章/缓存错误：{s['articleErrors']}", f"- 候选全部待审：{s['allCandidatesNeedsReview']}",
        f"- 重复候选 ID：{s['duplicateCandidateIds']}", "", "## 分科统计", "",
        "| 科目 | 文章 | 章节 | 候选卡 | 待补单元 |", "|---|---:|---:|---:|---:|"]
    for sid, v in sorted(report["sourceSummary"].items()):
        lines.append(f"| {sid} | {v['articles']} | {v['sections']} | {v['candidates']} | {v['backlogUnits']} |")
    lines += ["", "## 候选策略", ""]
    lines += [f"- `{k}`：{v}" for k, v in sorted(s["candidateStrategies"].items())]
    lines += ["", "## 待补原因", ""]
    lines += [f"- `{k}`：{v}" for k, v in sorted(s["backlogReasons"].items())]
    lines += ["", "## 与旧泛化卡集成建议", "",
        "本生成器不删除或替换旧卡。主流程整合时若以原子候选替换泛化卡，应把旧卡保留为历史记录并记录 supersededBy/替代原因；泛化卡构建器需将这些已替代 ID 排除，避免下次同步复活。候选未审核前不得进入正式复习集。", ""]
    return "\n".join(lines)


def write_outputs(root: Path, report: dict, apply: bool = False) -> dict | None:
    """Write reports only when explicitly called by CLI; mutate cards only with --apply."""
    root = Path(root).resolve(); reconciled = None; card_text = None
    if apply:
        path = root / "data" / "cards" / "cards.json"
        document = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"version": 1, "cards": []}
        if not isinstance(document, dict) or not isinstance(document.get("cards"), list):
            raise ValueError("cards.json must contain a cards list")
        reconciled = reconcile_owned_cards(document["cards"], report["candidates"])
        report["applySummary"] = {k: v for k, v in reconciled.items() if k != "cards"}
        document["cards"] = reconciled["cards"]
        card_text = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    report_dir = root / "data" / "reports"
    backlog = {"version": 1, "summary": {"backlogUnits": len(report["backlog"]),
        "sectionBacklog": len(report["sectionBacklog"])}, "sections": report["sectionBacklog"],
        "units": report["backlog"], "articleErrors": report["articleErrors"]}
    _write(report_dir / "atomic-candidates.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    _write(report_dir / "atomic-candidates.md", _markdown(report))
    _write(report_dir / "atomic-candidates-backlog.json", json.dumps(backlog, ensure_ascii=False, indent=2) + "\n")
    if apply and card_text is not None: _write(root / "data" / "cards" / "cards.json", card_text)
    return reconciled


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build deterministic offline atomic card candidates.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--apply", action="store_true", help="write reports and upsert only this generator's cards")
    args = parser.parse_args(argv)
    try:
        report = build_candidate_set(args.root)
        if args.apply:
            reconciled = write_outputs(args.root, report, apply=True)
            report["summary"]["cardsInserted"] = reconciled["inserted"] if reconciled else 0
            report["summary"]["cardsUpdated"] = reconciled["updated"] if reconciled else 0
            print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
        else:
            print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
            print("Dry-run: read-only; no data or report files written. Use --apply to persist reports/cards.")
        return 1 if report["summary"]["articleErrors"] or report["summary"]["duplicateCandidateIds"] else 0
    except Exception as exc:
        print(f"atomic candidate build failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
