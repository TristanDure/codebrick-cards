"""Audit complete VitePress article route manifests from saved live index HTML.

No network requests and no card/ledger mutations. --apply writes only reports.
A matching route inventory does not prove semantic or rich-content coverage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import os
import stat
import sys
import tempfile
from html.parser import HTMLParser
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

sys.dont_write_bytecode = True

try:
    from . import sync_sources
except ImportError:
    import sync_sources

ROOT = Path(__file__).resolve().parents[1]
MAP_RE = re.compile(r'__VP_HASH_MAP__\s*=\s*JSON\.parse\((".*?")\)', re.S)


# Two observed CO routes have their own migration article and a successor
# declaration. Both routes remain independent entries in the article inventory.
CO_RETAINED_MIGRATIONS = {
    "posts/storage/cache-comprehensive.html": "posts/storage/cache-mapping",
    "posts/storage/cache-performance.html": "posts/storage/cache-concept",
}


def extract_manifest(raw: str, source: dict) -> dict[str, str]:
    match = MAP_RE.search(raw)
    if not match:
        raise ValueError("VitePress build manifest not found")
    mapping = json.loads(json.loads(match.group(1)))
    if not isinstance(mapping, dict):
        raise ValueError("VitePress build manifest must be an object")
    routes = {}
    for key, asset_hash in mapping.items():
        if not isinstance(key, str):
            raise ValueError("manifest key must be text")
        if not key.startswith("posts_") or not key.endswith(".md"):
            continue
        parts = key[:-3].split("_")
        if any(not part or part in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9-]+", part) for part in parts):
            raise ValueError(f"noncanonical or ambiguous flattened route key: {key}")
        if not isinstance(asset_hash, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", asset_hash):
            raise ValueError(f"invalid article asset hash: {key}")
        route = source["base"] + key[:-3].replace("_", "/") + source["extension"]
        if route in routes:
            raise ValueError(f"ambiguous article route: {route}")
        routes[route] = asset_hash
    if not routes:
        raise ValueError("build manifest contains no article routes")
    return routes


class PageIdentity(HTMLParser):
    def __init__(self):
        super().__init__()
        self.canonicals = []
        self.head_canonicals = []
        self.refresh = []
        self.modules = []
        self.in_head = False

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        if tag == "head":
            self.in_head = True
        if tag == "link" and "canonical" in (attr.get("rel") or "").split():
            canonical = attr.get("href") or ""
            self.canonicals.append(canonical)
            if self.in_head:
                self.head_canonicals.append(canonical)
        if self.in_head and tag == "meta" and (attr.get("http-equiv") or "").lower() == "refresh":
            self.refresh.append(attr.get("content") or "")
        if tag == "link" and "modulepreload" in (attr.get("rel") or "").split():
            self.modules.append(attr.get("href", ""))

    def handle_endtag(self, tag):
        if tag == "head":
            self.in_head = False


def checked_path(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("cache path escapes project root or is invalid")
    path = (root / relative).resolve()
    if root not in path.parents:
        raise ValueError("cache path escapes project root")
    return path


def article_manifest_key(url: str, source: dict) -> str:
    """Validate the exact inferred route; do not normalize arbitrary URL syntax."""
    base = source["base"]
    if not url.startswith(base) or urlsplit(url).query or urlsplit(url).fragment:
        raise ValueError("article URL is not an exact source article route")
    relative = url[len(base):]
    extension = source["extension"]
    if extension:
        if not relative.endswith(extension):
            raise ValueError("article URL has an unexpected extension")
        relative = relative[:-len(extension)]
    if not re.fullmatch(r"posts/(?:[A-Za-z0-9-]+/)*[A-Za-z0-9-]+", relative):
        raise ValueError("article URL has a noncanonical article path")
    return relative.replace("/", "_") + ".md"


def canonical_evidence(canonicals: list[str], url: str, source: dict) -> dict:
    """Only OS has the observed same-article, fixed-.html canonical alias."""
    article_manifest_key(url, source)
    normalized, rules = [], []
    for canonical in canonicals:
        if (source["id"] == "os" and source["extension"] == ""
                and canonical == url + ".html"):
            normalized.append(url)
            rules.append("os-same-article-fixed-html-suffix")
        else:
            normalized.append(canonical)
            rules.append("exact" if canonical == url else "no-permitted-alias")
    matches = len(canonicals) == 1 and normalized == [url]
    return {"canonicalUrls": canonicals, "normalizedCanonicalUrls": normalized,
            "canonicalIdentityRules": rules, "canonicalIdentityMatches": matches,
            "canonicalAliasApplied": matches and rules == ["os-same-article-fixed-html-suffix"]}


def retained_migration(identity: PageIdentity, url: str, source: dict, manifest: dict, local_urls: set[str]) -> dict | None:
    if source["id"] != "co":
        return None
    target_path = CO_RETAINED_MIGRATIONS.get(url[len(source["base"]):])
    if target_path is None:
        return None
    declared_target = source["base"] + target_path
    target_route = declared_target + ".html"
    declared_refresh = "0;url=" + urlsplit(declared_target).path
    if (Counter(identity.canonicals) != Counter((url, declared_target))
            or identity.head_canonicals != identity.canonicals
            or identity.refresh != [declared_refresh]
            or target_route not in manifest or target_route not in local_urls):
        return None
    return {"targetUrl": target_route, "declaredTargetUrl": declared_target, "refresh": declared_refresh}


def audit_catalog(root: Path, snapshot_date: str) -> dict:
    root = root.resolve()
    if not re.fullmatch(r"\d{8}", snapshot_date):
        raise ValueError("snapshot date must be YYYYMMDD")
    datetime.strptime(snapshot_date, "%Y%m%d")
    raw_articles = checked_path(root, "data/articles.json").read_bytes()
    articles = json.loads(raw_articles)["articles"]
    if not isinstance(articles, list) or not articles or any(
            not isinstance(a, dict) or not isinstance(a.get("url"), str)
            or not a["url"] or a["url"].strip() != a["url"] for a in articles):
        raise ValueError("articles must be a nonempty list of objects with nonempty URL strings")
    counts = Counter(a["url"] for a in articles)
    duplicate_urls = sorted(u for u, count in counts.items() if count > 1)
    known_sources = {s["id"] for s in sync_sources.SOURCES}
    unknown_sources = [a["url"] for a in articles if a.get("sourceId") not in known_sources]
    observations = []
    for source in sync_sources.SOURCES:
        sid = source["id"]
        relative = f".cache/{sid}-index-live-{snapshot_date}.html"
        records = [(i, a) for i, a in enumerate(articles) if a.get("sourceId") == sid]
        local_urls = {a["url"] for _, a in records}
        row = {"sourceId": sid, "indexUrl": source["base"], "snapshot": relative,
               "localArticleCount": len(records), "routeEvidence": "inferred-from-flattened-VitePress-keys; not-an-independent-link-crawl"}
        if not records:
            row["inputError"] = "no local article records for this source; cache evidence not verified"
        manifest = None
        try:
            raw = checked_path(root, relative).read_bytes()
            manifest = extract_manifest(raw.decode("utf-8"), source)
            row.update({"snapshotSha256": hashlib.sha256(raw).hexdigest(),
                "buildArticleCount": len(manifest), "liveOnlyRoutes": sorted(set(manifest) - local_urls),
                "localOnlyRoutes": sorted(local_urls - set(manifest)),
                "routes": [{"url": url, "assetHash": asset_hash} for url, asset_hash in sorted(manifest.items())]})
            row["routeInventoryMatches"] = not (row["liveOnlyRoutes"] or row["localOnlyRoutes"])
        except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
            row.update({"error": str(exc), "routeInventoryMatches": False})
        changed, unverifiable, evidence = [], [], []
        for record_index, article in records:
            url = article["url"]
            item = {"recordIndex": record_index, "url": url, "cache": article.get("cache"),
                    "bytesVerifiedAgainstRemote": False, "cacheEvidenceMatches": False}
            try:
                cache = checked_path(root, article.get("cache"))
                cache_raw = cache.read_bytes()
                html = cache_raw.decode("utf-8")
                item["rawHtmlSha256"] = hashlib.sha256(cache_raw).hexdigest()
                key = article_manifest_key(url, source)
                item["manifestKey"] = key
                prior = extract_manifest(html, source)
                if url not in prior:
                    raise ValueError("cached HTML does not list its own article route")
                if manifest is None:
                    raise ValueError("saved index is unavailable; build ID comparison not verified")
                if url not in manifest:
                    raise ValueError("article route absent from saved index")
                if prior[url] != manifest[url]:
                    changed.append({"recordIndex": record_index, "url": url, "cachedAssetHash": prior[url], "liveAssetHash": manifest[url]})
                identity = PageIdentity()
                identity.feed(html)
                item.update(canonical_evidence(identity.canonicals, url, source))
                migration = None
                if not item["canonicalIdentityMatches"]:
                    migration = retained_migration(identity, url, source, manifest, local_urls)
                    if migration is None:
                        item["headRefreshDirectives"] = identity.refresh
                        raise ValueError("cached page canonical identity missing, duplicated or different")
                parsed = sync_sources.parse_article(html, url)
                parsed_hash = hashlib.sha256(json.dumps(parsed["blocks"], ensure_ascii=False).encode()).hexdigest()
                item["parsedContentSha256"] = parsed_hash
                if article.get("contentHash") != parsed_hash:
                    raise ValueError("cached article body differs from local manifest contentHash")
                expected = source["base"] + "assets/" + key + "." + prior[url] + ".lean.js"
                modules = [urljoin(url, href) for href in identity.modules]
                item["expectedOwnModuleDeclaration"] = expected
                if expected not in modules:
                    raise ValueError("cached page does not preload its expected own module declaration")
                if migration is not None:
                    item["retainedMigration"] = migration
                item["cacheEvidenceMatches"] = True
            except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
                item["error"] = str(exc)
                unverifiable.append({"recordIndex": record_index, "url": url, "error": str(exc)})
            evidence.append(item)
        row.update({"changedBuildRoutes": changed, "unverifiableBuildRoutes": unverifiable,
                    "cacheRecords": evidence,
                    "articleBuildHashesMatch": bool(records) and manifest is not None and not (changed or unverifiable),
                    "canonicalAliasRecordCount": sum(e.get("canonicalAliasApplied", False) for e in evidence),
                    "retainedMigrationRecordCount": sum("retainedMigration" in e for e in evidence),
                    "cacheEvidenceMatches": all(e["cacheEvidenceMatches"] for e in evidence) and bool(evidence)})
        observations.append(row)
    return {"schema": "codebrick-source-catalog-audit", "version": 4,
            "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "snapshotDate": snapshot_date, "snapshotDateProvenance": "CLI label; fetching time not independently authenticated",
            "articlesSha256": hashlib.sha256(raw_articles).hexdigest(),
            "routeInventoryMatches": not (duplicate_urls or unknown_sources) and all(r["routeInventoryMatches"] for r in observations),
            "articleBuildHashesMatch": not (duplicate_urls or unknown_sources) and all(r["articleBuildHashesMatch"] for r in observations),
            "downloadedBuildModuleBytesVerified": False,
            "canonicalAliasPolicy": "Only OS extensionless article routes may equal their exact URL plus fixed .html.",
            "retainedMigrationPolicy": "Only the two enumerated CO routes qualify, with both exact canonical tags in the head, one exact meta refresh and the successor route present in the local and saved index inventories. Both article records remain in scope.",
            "duplicateArticleUrls": duplicate_urls, "unknownSourceArticles": unknown_sources,
            "localArticleCount": len(articles), "subjects": observations, "contentApproved": False,
            "limitations": ["Saved index HTML is a dated observation, not continuous monitoring or authenticated capture-time evidence.",
                "Routes are inferred from flattened keys using the synchronizer convention; an independent exhaustive link crawl was not performed.",
                "articleBuildHashesMatch compares embedded opaque build IDs, not downloaded module file bytes.",
                "Canonical URL, own preload declaration and parsed-body hash only establish local consistency; raw HTML digests record bytes without proving remote authenticity.",
                "A migration declaration records the page metadata. Successor knowledge coverage and browser redirect behavior require separate evidence.",
                "External images, interactive practice and linked resources remain separately unverified.",
                "Matching all routes and cache evidence does not establish knowledge-point correctness or complete extraction."]}


def markdown(report: dict) -> str:
    lines = ["# 指定日期保存的四站 posts 构建清单对照", "", f"快照日期：{report['snapshotDate']}；本地文章：{report['localArticleCount']}。", "",
             "| 科目 | 本地 | 构建清单 | 新增路由 | 本地独有 | 构建变化 | 无法比较 | 规范别名 | 保留迁移页 |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in report["subjects"]:
        lines.append(f"| {row['sourceId']} | {row['localArticleCount']} | {row.get('buildArticleCount', 'ERROR')} | {len(row.get('liveOnlyRoutes', []))} | {len(row.get('localOnlyRoutes', []))} | {len(row.get('changedBuildRoutes', []))} | {len(row.get('unverifiableBuildRoutes', []))} | {row.get('canonicalAliasRecordCount', 0)} | {row.get('retainedMigrationRecordCount', 0)} |")
    lines += ["", f"文章路由集合一致：{report['routeInventoryMatches']}。逐篇缓存证据及构建 ID 声明一致（articleBuildHashesMatch）：{report['articleBuildHashesMatch']}。", "",
              "该结果仅核对推断路由、缓存页面身份、正文哈希和内嵌构建ID，未下载验证构建模块字节，不能作为知识点完整或 408 内容通过的证明。外部图片、交互真题与答案须独立核对。",
              *["- " + item for item in report["limitations"]], "",
              "输入快照与 SHA-256、逐篇构建哈希和差异保存在同名 JSON。", ""]
    lines += ["", "观察结果：" + ("CONSISTENT" if report["routeInventoryMatches"] and report["articleBuildHashesMatch"] else "FAIL") + "；contentApproved=false，等待独立评审。",
              "", "Canonical 别名规则：" + report["canonicalAliasPolicy"],
              "", "保留迁移页规则：" + report["retainedMigrationPolicy"], "", "逐项诊断："]
    for row in report["subjects"]:
        for key in ("error", "inputError"):
            if key in row:
                lines.append(f"- {row['sourceId']}: {row[key]}")
        for item in row["cacheRecords"]:
            if "retainedMigration" in item:
                target = item["retainedMigration"]["targetUrl"]
                lines.append(f"- {row['sourceId']} record {item['recordIndex']} 保留迁移页 {item['url']} → {target}")
            if "error" in item:
                lines.append(f"- {row['sourceId']} record {item['recordIndex']} {item['url']}: {item['error']}; raw canonical="
                             + json.dumps(item.get("canonicalUrls"), ensure_ascii=False)
                             + "; normalized=" + json.dumps(item.get("normalizedCanonicalUrls"), ensure_ascii=False))
    return "\n".join(lines) + "\n"


def _report_directory(root: Path, create: bool = False) -> tuple[Path, tuple | None]:
    """Keep lexical output paths; never follow even an in-root output junction."""
    directory = root / "data" / "reports"
    identities = []
    for path in (root, root / "data", directory):
        try:
            info = path.lstat()
        except FileNotFoundError:
            if not create:
                return directory, None
            path.mkdir(exist_ok=True)
            info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError("report directory escapes or aliases project paths through a reparse point")
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError("report directory is not a real directory")
        identities.append((info.st_dev, info.st_ino))
    return directory, tuple(identities)


def _check_report_target(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if (stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
            or not stat.S_ISREG(info.st_mode)):
        raise ValueError("report target is not an ordinary non-reparse file: " + path.name)
    # A hardlink is safe only because publication replaces this directory entry;
    # never open or truncate the existing target inode.


def write_reports(root: Path, date: str, report: dict) -> None:
    root = root.resolve()
    if not re.fullmatch(r"\d{8}", date):
        raise ValueError("snapshot date must be YYYYMMDD")
    stem = "source-catalog-" + datetime.strptime(date, "%Y%m%d").strftime("%Y-%m-%d")
    # Validate/serialize everything before creating a directory or staging files.
    payloads = ((".json", json.dumps(report, ensure_ascii=False, indent=2) + "\n"), (".md", markdown(report)))
    directory, _ = _report_directory(root)
    paths = [directory / (stem + suffix) for suffix, _ in payloads]
    for path in paths:
        _check_report_target(path)
    directory, identity = _report_directory(root, create=True)

    def check_outputs():
        if _report_directory(root)[1] != identity:
            raise ValueError("report directory changed during publication")
        for path in paths:
            _check_report_target(path)

    temporary_paths = []
    try:
        # Stage both outputs before replacing either; replacement is atomic per
        # file, not a two-file transaction. An I/O failure may leave a mixed pair.
        for _, text in payloads:
            check_outputs()
            fd, temporary = tempfile.mkstemp(dir=directory, prefix=stem + ".", suffix=".tmp")
            temporary_paths.append(Path(temporary))
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(text)
            check_outputs()
        for temporary, path in zip(temporary_paths, paths):
            check_outputs()
            os.replace(temporary, path)
    finally:
        # Do not follow a subsequently redirected directory for cleanup.
        try:
            stable = _report_directory(root)[1] == identity
        except (OSError, ValueError):
            stable = False
        if stable:
            for temporary in temporary_paths:
                temporary.unlink(missing_ok=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--snapshot-date", required=True, help="YYYYMMDD; uses .cache/{subject}-index-live-{date}.html")
    parser.add_argument("--apply", action="store_true", help="write only the two catalog reports")
    args = parser.parse_args(argv)
    try:
        report = audit_catalog(args.root, args.snapshot_date)
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"error": str(exc), "contentApproved": False, "reportsWritten": False}, ensure_ascii=True))
        return 1
    if args.apply:
        try:
            write_reports(args.root.resolve(), args.snapshot_date, report)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(json.dumps({"error": str(exc), "contentApproved": False, "reportsWritten": False, "reportsMayBePartial": True}, ensure_ascii=True))
            return 1
    compact = {k: v for k, v in report.items() if k != "subjects"}
    compact["subjects"] = [{k: v for k, v in r.items() if k not in {"routes", "changedBuildRoutes", "unverifiableBuildRoutes", "cacheRecords"}} |
                           {"changedBuildRouteCount": len(r.get("changedBuildRoutes", [])), "unverifiableBuildRouteCount": len(r.get("unverifiableBuildRoutes", []))} for r in report["subjects"]]
    compact["reportsWritten"] = args.apply
    print(json.dumps(compact, ensure_ascii=True, indent=2))
    return 0 if report["routeInventoryMatches"] and report["articleBuildHashesMatch"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
