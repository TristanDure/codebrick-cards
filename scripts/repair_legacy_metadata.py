from __future__ import annotations

"""Repair stale source-removal flags without changing card learning content.

The full sync can leave historical ``sourceSectionRemoved`` /
``sourceArticleMissing`` flags on cards whose current cached article still
contains the section. This command only clears those flags (and fills a
missing current section index) after an unambiguous mapping to the cached
source. It is dry-run by default; use ``--apply`` to write a backup and update
``data/cards/cards.json``.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from typing import Any

try:
    from .sync_sources import ROOT, load, parse_article, sections
except ImportError:  # direct script execution
    from sync_sources import ROOT, load, parse_article, sections


def resolve_section(card: dict[str, Any], article_sections: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Resolve a card to one current section, refusing ambiguous matches."""
    anchor = str(card.get("sectionAnchor") or "")
    if anchor:
        candidates = [section for section in article_sections if section.get("anchor") == anchor]
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            heading = str(card.get("section") or "")
            narrowed = [section for section in candidates if section.get("heading") == heading]
            if len(narrowed) == 1:
                return narrowed[0]
            return None
    raw_index = card.get("sectionIndex")
    if isinstance(raw_index, int) and not isinstance(raw_index, bool) and 1 <= raw_index <= len(article_sections):
        return article_sections[raw_index - 1]
    return None


def build_plan(root: Path | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    root = Path(root) if root is not None else ROOT
    articles = load(root / "data" / "articles.json", {"articles": []}).get("articles", [])
    cards = load(root / "data" / "cards" / "cards.json", {"cards": []}).get("cards", [])
    articles_by_url = {str(article.get("url")): article for article in articles if article.get("url")}
    parsed_by_url: dict[str, list[dict[str, Any]]] = {}
    failures: list[dict[str, str]] = []
    for url, article in articles_by_url.items():
        cache = root / str(article.get("cache") or "")
        try:
            parsed_by_url[url] = sections(parse_article(cache.read_text(encoding="utf-8"), url))
        except Exception as exc:  # keep the repair conservative
            failures.append({"articleUrl": url, "error": f"{type(exc).__name__}: {exc}"})

    changes: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for card in cards:
        if not (card.get("sourceSectionRemoved") or card.get("sourceArticleMissing")):
            continue
        url = str(card.get("articleUrl") or "").split("#", 1)[0]
        target = resolve_section(card, parsed_by_url.get(url, []))
        if target is None:
            unresolved.append({"cardId": card.get("id"), "articleUrl": url, "section": card.get("section")})
            continue
        changes.append({
            "cardId": card.get("id"),
            "articleUrl": url,
            "fromSectionIndex": card.get("sectionIndex"),
            "toSectionIndex": target.get("sectionIndex"),
            "section": target.get("heading"),
        })
    summary = {
        "flaggedCardCount": sum(bool(card.get("sourceSectionRemoved") or card.get("sourceArticleMissing")) for card in cards),
        "repairableCardCount": len(changes),
        "unresolvedCardCount": len(unresolved),
        "articleParseFailureCount": len(failures),
        "changes": changes,
        "unresolved": unresolved,
        "articleParseFailures": failures,
    }
    return cards, summary


def apply_plan(root: Path, cards: list[dict[str, Any]], summary: dict[str, Any]) -> Path:
    backup_dir = root / "_backups" / f"legacy-metadata-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    backup_cards = backup_dir / "data" / "cards" / "cards.json"
    backup_cards.parent.mkdir(parents=True, exist_ok=False)
    cards_path = root / "data" / "cards" / "cards.json"
    shutil.copy2(cards_path, backup_cards)
    changes_by_id = {str(item["cardId"]): item for item in summary["changes"]}
    for card in cards:
        change = changes_by_id.get(str(card.get("id")))
        if not change:
            continue
        card.pop("sourceSectionRemoved", None)
        card.pop("sourceArticleMissing", None)
        card["sectionIndex"] = change["toSectionIndex"]
    cards_path.write_text(json.dumps({"version": 1, "cards": cards}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return backup_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--apply", action="store_true", help="write a dated backup and apply only unambiguous metadata repairs")
    args = parser.parse_args(argv)
    cards, summary = build_plan(args.root)
    print(json.dumps({key: summary[key] for key in ("flaggedCardCount", "repairableCardCount", "unresolvedCardCount", "articleParseFailureCount")}, ensure_ascii=False))
    if args.apply and summary["repairableCardCount"]:
        backup = apply_plan(args.root, cards, summary)
        print(f"已应用 {summary['repairableCardCount']} 张卡的元数据修复；备份：{backup}")
    elif args.apply:
        print("没有可安全应用的修复")
    else:
        print("预览模式：未修改 cards.json；使用 --apply 写入备份并应用")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
