"""Build per-article review workspace shards without mutating cards or review ledgers.

All exported material is a candidate. A successful build is never content approval.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import os
import stat
from pathlib import Path
import sys
import tempfile
from urllib.parse import urldefrag

ROOT = Path(__file__).resolve().parents[1]
try:
    from scripts import build_atomic_candidates as atomic
    from scripts import import_curated_articles as curated
except ModuleNotFoundError as exc:
    if exc.name not in {"scripts", "scripts.build_atomic_candidates", "scripts.import_curated_articles"}:
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import build_atomic_candidates as atomic
    import import_curated_articles as curated

SCHEMA = "codebrick-article-workspace"


def inside(root: Path, value: str) -> Path:
    path = (root / value).resolve()
    if root not in path.parents or path == root:
        raise ValueError("path escapes project root")
    return path


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def build_workspace(root: Path = ROOT, candidate_report: dict | None = None, curated_files: list[str] | None = None) -> dict:
    root = Path(root).resolve()
    manifest_raw = (root / "data/articles.json").read_bytes()
    manifest = json.loads(manifest_raw)
    articles = manifest["articles"]
    if not isinstance(articles, list):
        raise ValueError("article inventory must be an array")
    urls = [a["url"] for a in articles]
    if len(urls) != len(set(urls)):
        raise ValueError("duplicate article URL")
    report = atomic.build_candidate_set(root) if candidate_report is None else candidate_report
    if report.get("articleErrors"):
        raise ValueError("candidate generation reported article errors; refusing incomplete publication")
    grouped = defaultdict(list)
    for card in report["candidates"]:
        url = urldefrag(card.get("articlePath") or card.get("articleUrl", ""))[0]
        if url not in urls:
            raise ValueError("candidate belongs to unknown article")
        grouped[url].append(card)
    backlog = defaultdict(list)
    unit_backlog = defaultdict(list)
    for field, grouped_backlog in (("sectionBacklog", backlog), ("backlog", unit_backlog)):
        for item in report.get(field, []):
            if item["articleUrl"] not in urls:
                raise ValueError(field + " belongs to unknown article")
            grouped_backlog[item["articleUrl"]].append(item)
    drafts = defaultdict(list)
    draft_errors = []
    if curated_files is None:
        curated_paths = sorted((root / "data/curated").glob("*.json"))
    else:
        curated_paths = [inside(root, value) for value in curated_files]
        curated_dir = (root / "data/curated").resolve()
        if len(set(curated_paths)) != len(curated_paths):
            raise ValueError("duplicate explicitly selected curated file")
        if any(path.parent != curated_dir or path.suffix != ".json" for path in curated_paths):
            raise ValueError("explicit curated files must be JSON files directly in data/curated")
        curated_paths.sort()
    for path in curated_paths:
        draft_raw = path.read_bytes()
        result = curated.audit_article(path, root)
        if digest(draft_raw) != result.get("candidateSha256") or path.read_bytes() != draft_raw:
            raise ValueError("curated draft changed during build: " + path.name)
        if not result.get("structuralOk"):
            draft_errors.append({"file": path.relative_to(root).as_posix(), "errors": result.get("errors", [])})
            continue
        document = json.loads(draft_raw)
        url = document.get("articleUrl") or document.get("article", {}).get("url")
        if url not in urls:
            draft_errors.append({"file": path.relative_to(root).as_posix(), "errors": ["unknown article URL"]})
            continue
        authored = "unitDisposition" in document
        display_cards = [{
            "id": card["id" if authored else "cardId"],
            "question": card["question" if authored else "front"],
            "answer": card["answer" if authored else "back"],
            "unitIds": list(card["unitIds" if authored else "knowledgeUnitIds"]),
            "assumptions": list(card.get("assumptions", [])),
            "sourceNotes": list(card.get("sourceNotes", [])),
        } for card in document["cards"]]
        drafts[url].append({"file": path.relative_to(root).as_posix(),
            "sha256": digest(draft_raw), "validation": result, "document": document,
            "displayCards": display_cards})
    # A bad/new draft never silently disappears from a seemingly successful catalog.
    if draft_errors:
        raise ValueError("invalid curated drafts: " + json.dumps(draft_errors, ensure_ascii=True))
    index = {"schema": SCHEMA, "version": 1, "contentApproved": False,
        "status": "needs-independent-content-review", "claimsFullKnowledgeCoverage": False,
        "articleManifestSha256": digest(manifest_raw),
        "notice": "全站目录与候选，不等于全部知识点已覆盖或408备考验收通过。精编卡也须独立评审；缺图、交互、原题及来源冲突见待核清单。",
        "summary": {}, "articles": []}
    shards = {}
    for record in sorted(articles, key=lambda a: (a["sourceId"], a["url"])):
        raw = inside(root, record["cache"]).read_bytes()
        parsed = atomic.sync_sources.parse_article(raw.decode("utf-8"), record["url"])
        if curated._hash_parsed_article(parsed) != record.get("contentHash"):
            raise ValueError("cached source differs from manifest: " + record["url"])
        sections = atomic.sync_sources.sections(parsed)
        article_id = record["sourceId"] + "-" + digest(record["url"].encode())[:16]
        section_data = []
        for number, section in enumerate(sections, 1):
            units = []
            for block in section.get("sourceUnits", []):
                units.extend(atomic._units(block, record["url"], section, number))
            section_data.append({"index": number, "heading": section.get("heading", ""),
                "headingPath": section.get("headingPath", section.get("heading", "")),
                "anchor": section.get("anchor", ""), "units": units,
                "emptyExtraction": not bool(units)})
        candidates = grouped[record["url"]]
        if any(c.get("sourceHash") != digest(raw) for c in candidates):
            raise ValueError("candidate source snapshot is stale")
        ids = [card["id"] for card in candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate candidate ID in article")
        draft_cards = sum(len(d["document"].get("cards", [])) for d in drafts[record["url"]])
        summary = {"sections": len(section_data), "sourceUnits": sum(len(s["units"]) for s in section_data),
            "atomicCandidates": len(candidates), "curatedCandidates": draft_cards,
            "emptySections": sum(s["emptyExtraction"] for s in section_data),
            "candidateGapSections": len(backlog[record["url"]]),
            "sectionBacklog": len(backlog[record["url"]]),
            "unitBacklog": len(unit_backlog[record["url"]]), "approvedCards": 0}
        entry = {"id": article_id, "sourceId": record["sourceId"], "title": record["title"],
            "url": record["url"], "contentHash": record.get("contentHash", ""),
            "file": "articles/" + article_id + ".json", "summary": summary}
        shard = {"schema": SCHEMA, "version": 1, "contentApproved": False,
            "article": entry, "rawHtmlSha256": digest(raw), "sections": section_data,
            "atomicCandidates": candidates, "curated": drafts[record["url"]],
            "sectionBacklog": backlog[record["url"]], "unitBacklog": unit_backlog[record["url"]]}
        encoded = json.dumps(shard, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        entry["sha256"] = digest(encoded)
        entry["bytes"] = len(encoded)
        # The checksum applies to the published bytes, whose embedded article has no checksum.
        shards[entry["file"]] = encoded
        index["articles"].append(entry)
    index["summary"] = {"articles": len(index["articles"]),
        "subjects": dict(Counter(a["sourceId"] for a in index["articles"])),
        **{key: sum(a["summary"][key] for a in index["articles"]) for key in
           ("sections", "sourceUnits", "atomicCandidates", "curatedCandidates", "emptySections", "candidateGapSections", "sectionBacklog", "unitBacklog", "approvedCards")},
        "totalShardBytes": sum(len(v) for v in shards.values()),
        "maxShardBytes": max(map(len, shards.values()), default=0)}
    return {"index": index, "shards": shards}


def _publication_path(root: Path, relative: str, *, directory: bool = False) -> Path:
    """Reject existing redirects, including Windows junctions, below the project root."""
    root = Path(root).resolve()
    output = root / "data/study"
    value = Path(relative)
    if value.is_absolute() or value.drive or ".." in value.parts:
        raise ValueError("path escapes publication namespace")
    path = output / value
    current = root
    parts = path.relative_to(root).parts
    for number, part in enumerate(parts):
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            raise ValueError("refusing symlink/reparse component in publication namespace: " + str(current))
        if (number < len(parts) - 1 or directory) and not stat.S_ISDIR(info.st_mode):
            raise ValueError("publication namespace component is not a directory: " + str(current))
    import os
    resolved_path = os.path.normcase(str(path.resolve()))
    resolved_output = os.path.normcase(str(output.resolve()))
    try:
        if os.path.commonpath((resolved_path, resolved_output)) != resolved_output:
            raise ValueError("path escapes real publication namespace")
    except ValueError as exc:
        raise ValueError("path escapes real publication namespace") from exc
    return path


def write_atomic(path: Path, raw: bytes, *, publication_root: Path | None = None) -> None:
    def check():
        if publication_root is not None:
            root = Path(publication_root).resolve()
            namespace = (root / "data/study").resolve()
            target = Path(path).resolve(strict=False)
            import os
            target_value = os.path.normcase(str(target))
            namespace_value = os.path.normcase(str(namespace))
            if os.path.commonpath((target_value, namespace_value)) != namespace_value:
                raise ValueError("path escapes real publication namespace")
            relative = target.relative_to(namespace).as_posix()
            _publication_path(root, relative)

    check()
    path.parent.mkdir(parents=True, exist_ok=True)
    check()
    fd, temp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
        check()
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def publish(root: Path, result: dict) -> None:
    root = Path(root).resolve()
    # Versioned generation avoids an old index pointing at partially replaced shards.
    snapshot = digest(json.dumps(result["index"], sort_keys=True, ensure_ascii=False).encode())[:20]
    generation = "snapshots/" + snapshot
    # Preflight the entire namespace even when there are no articles/shards to write.
    for relative in ("", "snapshots", generation, generation + "/articles"):
        _publication_path(root, relative, directory=True)
    index_target = _publication_path(root, "index.json")
    targets = []
    for name, raw in result["shards"].items():
        if (not isinstance(name, str) or "\\" in name or ":" in name
                or len(name.split("/")) != 2 or name.split("/")[0] != "articles"
                or name.split("/")[1] in {"", ".", "..", ".json"} or not name.endswith(".json")):
            raise ValueError("invalid shard path for publication namespace")
        targets.append((_publication_path(root, generation + "/" + name), raw))
    names = [item["file"] for item in result["index"]["articles"]]
    if len(names) != len(set(names)) or set(names) != set(result["shards"]):
        raise ValueError("index/shard paths disagree in publication namespace")
    for target, raw in targets:
        write_atomic(target, raw, publication_root=root)
    index = json.loads(json.dumps(result["index"]))
    for item in index["articles"]:
        item["file"] = generation + "/" + item["file"]
    write_atomic(index_target, json.dumps(index, ensure_ascii=False, separators=(",", ":")).encode(),
                 publication_root=root)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--apply", action="store_true", help="publish data/study shards; never change formal cards/reviews")
    parser.add_argument("--curated-file", action="append", help="publish only these frozen data/curated JSON files; repeat for each selected file")
    args = parser.parse_args(argv)
    try:
        result = build_workspace(args.root, curated_files=args.curated_file)
        if args.apply:
            publish(args.root, result)
        print(json.dumps({"mode": "apply" if args.apply else "dry-run", "contentApproved": False,
                          **result["index"]["summary"]}, ensure_ascii=True, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"ok": False, "contentApproved": False, "error": str(exc)}, ensure_ascii=True))
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
