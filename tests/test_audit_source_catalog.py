from __future__ import annotations
import json
import io
import os
import re
import subprocess
from contextlib import contextmanager, redirect_stdout
from unittest import mock
import tempfile
import unittest
from pathlib import Path
from scripts import audit_source_catalog as audit


class SourceCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "data").mkdir()
        (self.root / ".cache").mkdir()
        self.articles = []
        for source in audit.sync_sources.SOURCES:
            sid = source["id"]
            mapping = {"index.md": "index-hash", "posts_topic_intro.md": "intro-v1", "posts_topic_calc.md": "calc-v1"}
            raw = self.raw(mapping)
            (self.root / f".cache/{sid}-index-live-20261120.html").write_text(raw, encoding="utf-8")
            for route in ("intro", "calc"):
                cache = f".cache/{sid}-{route}.html"
                url = source["base"] + "posts/topic/" + route + source["extension"]
                own = source["base"] + "assets/posts_topic_" + route + ".md." + mapping["posts_topic_" + route + ".md"] + ".lean.js"
                page = raw + '<link rel="canonical" href="' + url + '"><link rel="modulepreload" href="' + own + '"><main class="vp-doc"><h1>' + route + '</h1><p>' + route + ' is a concept.</p></main>'
                (self.root / cache).write_text(page, encoding="utf-8")
                import hashlib
                body_hash = hashlib.sha256(json.dumps(audit.sync_sources.parse_article(page, url)["blocks"], ensure_ascii=False).encode()).hexdigest()
                self.articles.append({"sourceId": sid, "url": url, "cache": cache, "contentHash": body_hash})
        self.write_articles()

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def raw(mapping):
        return "<script>window.__VP_HASH_MAP__=JSON.parse(" + json.dumps(json.dumps(mapping)) + ")</script>"

    def write_articles(self):
        (self.root / "data/articles.json").write_text(json.dumps({"articles": self.articles}), encoding="utf-8")

    def test_all_subject_routes_and_article_builds_match_without_approval(self):
        report = audit.audit_catalog(self.root, "20261120")
        self.assertTrue(report["routeInventoryMatches"])
        self.assertTrue(report["articleBuildHashesMatch"])
        self.assertFalse(report["contentApproved"])
        self.assertEqual(report["localArticleCount"], 8)
        self.assertEqual(len(report["subjects"]), 4)
        self.assertTrue(all(row["buildArticleCount"] == 2 for row in report["subjects"]))
        self.assertIn("知识点", audit.markdown(report))

    def test_new_route_and_stale_build_are_distinct_findings(self):
        source = audit.sync_sources.SOURCES[0]
        path = self.root / f".cache/{source['id']}-index-live-20261120.html"
        path.write_text(self.raw({"posts_topic_intro.md": "intro-v2", "posts_topic_calc.md": "calc-v1", "posts_new.md": "new-v1"}), encoding="utf-8")
        report = audit.audit_catalog(self.root, "20261120")
        row = report["subjects"][0]
        self.assertFalse(report["routeInventoryMatches"])
        self.assertFalse(report["articleBuildHashesMatch"])
        self.assertEqual(len(row["liveOnlyRoutes"]), 1)
        self.assertEqual(len(row["changedBuildRoutes"]), 1)

    def test_local_only_and_duplicate_articles_are_not_silently_removed(self):
        self.articles.append(dict(self.articles[0]))
        self.articles.append(dict(self.articles[0], url="https://www.codebrick.tech/os-blog/posts/old"))
        self.write_articles()
        before = (self.root / "data/articles.json").read_bytes()
        report = audit.audit_catalog(self.root, "20261120")
        self.assertFalse(report["routeInventoryMatches"])
        self.assertTrue(report["duplicateArticleUrls"])
        self.assertEqual(before, (self.root / "data/articles.json").read_bytes())

    def test_missing_root_or_article_cache_is_explicit(self):
        sid = audit.sync_sources.SOURCES[0]["id"]
        (self.root / f".cache/{sid}-index-live-20261120.html").unlink()
        (self.root / self.articles[-1]["cache"]).unlink()
        report = audit.audit_catalog(self.root, "20261120")
        self.assertFalse(report["routeInventoryMatches"])
        self.assertFalse(report["articleBuildHashesMatch"])
        self.assertIn("error", report["subjects"][0])
        self.assertTrue(report["subjects"][-1]["unverifiableBuildRoutes"])

    def test_cache_path_escape_is_rejected(self):
        self.articles[0]["cache"] = "../outside.html"
        self.write_articles()
        report = audit.audit_catalog(self.root, "20261120")
        self.assertFalse(report["articleBuildHashesMatch"])
        self.assertIn("escapes", report["subjects"][0]["unverifiableBuildRoutes"][0]["error"])

    def test_manifest_missing_empty_and_invalid_hash_rejected(self):
        for raw in ("<html></html>", self.raw({"index.md": "x"}), self.raw({"posts_a.md": None})):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    audit.extract_manifest(raw, audit.sync_sources.SOURCES[0])

    def test_default_cli_does_not_write_reports(self):
        from contextlib import redirect_stdout
        import io
        with redirect_stdout(io.StringIO()) as out:
            result = audit.main(["--root", str(self.root), "--snapshot-date", "20261120"])
        self.assertEqual(result, 0)
        self.assertFalse(json.loads(out.getvalue())["reportsWritten"])
        self.assertFalse((self.root / "data/reports").exists())

    def test_invalid_snapshot_date_fails_closed(self):
        for date in ("../outside", "20260230", "2026-11-20"):
            with self.subTest(date=date):
                with self.assertRaises(ValueError):
                    audit.audit_catalog(self.root, date)


    def test_changed_body_does_not_pass_with_unchanged_global_map(self):
        path = self.root / self.articles[0]["cache"]
        path.write_text(path.read_text(encoding="utf-8").replace("is a concept", "changed content"), encoding="utf-8")
        report = audit.audit_catalog(self.root, "20261120")
        self.assertFalse(report["articleBuildHashesMatch"])
        self.assertIn("body differs", report["subjects"][0]["cacheRecords"][0]["error"])

    def test_wrong_article_identity_does_not_pass_shared_manifest(self):
        self.articles[0]["cache"] = self.articles[1]["cache"]
        self.write_articles()
        report = audit.audit_catalog(self.root, "20261120")
        self.assertFalse(report["articleBuildHashesMatch"])
        self.assertIn("canonical identity", report["subjects"][0]["cacheRecords"][0]["error"])

    def test_same_subject_index_and_cache_missing_both_diagnosed(self):
        sid = audit.sync_sources.SOURCES[0]["id"]
        (self.root / f".cache/{sid}-index-live-20261120.html").unlink()
        (self.root / self.articles[0]["cache"]).unlink()
        row = audit.audit_catalog(self.root, "20261120")["subjects"][0]
        self.assertIn("error", row)
        self.assertEqual(len(row["cacheRecords"]), 2)
        self.assertTrue(all("error" in item for item in row["cacheRecords"]))

    def test_duplicate_url_records_both_checked_even_if_earlier_cache_missing(self):
        original = self.articles[0]
        self.articles.append(dict(original))
        self.articles[0] = dict(original, cache=".cache/missing.html")
        self.write_articles()
        report = audit.audit_catalog(self.root, "20261120")
        row = report["subjects"][0]
        self.assertEqual(len(row["cacheRecords"]), 3)
        self.assertIn("error", row["cacheRecords"][0])
        self.assertFalse(report["articleBuildHashesMatch"])

    def test_noncanonical_flat_keys_rejected(self):
        for key in ("posts_.._escape.md", "posts__topic.md", "posts_topic/evil.md", "posts_topic_%2e%2e.md"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                audit.extract_manifest(self.raw({key: "id"}), audit.sync_sources.SOURCES[0])

    def test_missing_own_module_declaration_rejected(self):
        path = self.root / self.articles[0]["cache"]
        text = path.read_text(encoding="utf-8").replace('rel="modulepreload"', 'rel="other"')
        path.write_text(text, encoding="utf-8")
        report = audit.audit_catalog(self.root, "20261120")
        self.assertFalse(report["articleBuildHashesMatch"])
        self.assertIn("own module", report["subjects"][0]["cacheRecords"][0]["error"])

    def test_report_hardlink_does_not_modify_original(self):
        import os
        out = self.root / "data/reports"
        out.mkdir()
        source = self.root / "preserve.json"
        source.write_text("preserve", encoding="utf-8")
        os.link(source, out / "source-catalog-2026-11-20.json")
        audit.write_reports(self.root, "20261120", audit.audit_catalog(self.root, "20261120"))
        self.assertEqual(source.read_text(encoding="utf-8"), "preserve")

    def test_report_junction_outside_root_rejected(self):
        import os
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as outside:
            link = self.root / "data/reports"
            if os.name == "nt":
                process = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), outside], capture_output=True)
                if process.returncode:
                    self.skipTest("junction creation unavailable")
            else:
                link.symlink_to(outside, target_is_directory=True)
            try:
                with self.assertRaisesRegex(ValueError, "escapes"):
                    audit.write_reports(self.root, "20261120", audit.audit_catalog(self.root, "20261120"))
                self.assertEqual(list(Path(outside).iterdir()), [])
            finally:
                if os.name == "nt":
                    os.rmdir(link)
                else:
                    link.unlink()

    def test_limitations_and_per_record_byte_evidence_are_explicit(self):
        report = audit.audit_catalog(self.root, "20261120")
        self.assertFalse(report["downloadedBuildModuleBytesVerified"])
        self.assertEqual(len(report["subjects"][0]["cacheRecords"][0]["rawHtmlSha256"]), 64)
        self.assertIn("flattened", " ".join(report["limitations"]))
        self.assertNotIn("全站实时文章清单", audit.markdown(report))

    def set_canonicals(self, index, values):
        path = self.root / self.articles[index]["cache"]
        if not hasattr(self, "original_pages"):
            self.original_pages = {}
        original = self.original_pages.setdefault(index, path.read_text(encoding="utf-8"))
        text = re.sub(r'<link rel="canonical" href="[^"]*">',
                      "".join('<link rel="canonical" href="' + value + '">' for value in values),
                      original)
        path.write_text(text, encoding="utf-8")

    @contextmanager
    def directory_alias(self, path, target):
        if os.name == "nt":
            result = subprocess.run(["cmd", "/c", "mklink", "/J", str(path), str(target)], capture_output=True)
            if result.returncode:
                self.skipTest("junction creation unavailable")
        else:
            path.symlink_to(target, target_is_directory=True)
        try:
            yield
        finally:
            if os.name == "nt":
                os.rmdir(path)
            else:
                path.unlink()

    def test_os_fixed_html_alias_records_raw_and_normalized_identity(self):
        url = self.articles[0]["url"]
        self.set_canonicals(0, [url + ".html"])
        report = audit.audit_catalog(self.root, "20261120")
        row = report["subjects"][0]
        item = row["cacheRecords"][0]
        self.assertTrue(report["articleBuildHashesMatch"])
        self.assertEqual(item["canonicalUrls"], [url + ".html"])
        self.assertEqual(item["normalizedCanonicalUrls"], [url])
        self.assertEqual(item["canonicalIdentityRules"], ["os-same-article-fixed-html-suffix"])
        self.assertEqual(row["canonicalAliasRecordCount"], 1)
        self.assertFalse(report["contentApproved"])

    def test_os_alias_does_not_normalize_other_urls_or_extensions(self):
        url = self.articles[0]["url"]
        invalid = [url + suffix for suffix in (".md", ".htm", ".HTML", ".html.html", ".html?x=1", ".html#x", "/.html", "?x=.html", "#x.html", ".html?", ".html#")]
        invalid += [url.replace("https:", "http:") + ".html", url.replace("www.codebrick.tech", "example.org") + ".html",
                    url.replace("www.codebrick.tech", "www.codebrick.tech:443") + ".html",
                    url.replace("www.codebrick.tech", "user@www.codebrick.tech") + ".html",
                    url.replace("/topic/", "/other/") + ".html", url.replace("/topic/", "/topic/../topic/") + ".html",
                    url.replace("/topic/", "/topic%2F") + ".html", "/os-blog/posts/topic/intro.html", "./intro.html"]
        for canonical in invalid:
            with self.subTest(canonical=canonical):
                self.set_canonicals(0, [canonical])
                report = audit.audit_catalog(self.root, "20261120")
                item = report["subjects"][0]["cacheRecords"][0]
                self.assertFalse(report["articleBuildHashesMatch"])
                self.assertEqual(item["normalizedCanonicalUrls"], [canonical])
                self.assertFalse(item["canonicalAliasApplied"])

    def test_canonical_count_is_not_deduplicated_even_when_identities_match(self):
        url = self.articles[0]["url"]
        for values in ([], [url, url], [url + ".html", url], [url + ".html", url + ".html"]):
            with self.subTest(values=values):
                self.set_canonicals(0, values)
                row = audit.audit_catalog(self.root, "20261120")["subjects"][0]
                self.assertFalse(row["articleBuildHashesMatch"])
                self.assertEqual(row["cacheRecords"][0]["canonicalUrls"], values)
                self.assertFalse(row["cacheRecords"][0]["canonicalAliasApplied"])

    def test_co_different_article_dual_canonical_remains_unverifiable(self):
        index = next(i for i, a in enumerate(self.articles) if a["sourceId"] == "co")
        url = self.articles[index]["url"]
        values = [url.replace("intro.html", "another-article"), url]
        self.set_canonicals(index, values)
        report = audit.audit_catalog(self.root, "20261120")
        row = next(r for r in report["subjects"] if r["sourceId"] == "co")
        item = row["cacheRecords"][0]
        self.assertFalse(report["articleBuildHashesMatch"])
        self.assertTrue(report["routeInventoryMatches"])
        self.assertEqual(item["normalizedCanonicalUrls"], values)
        self.assertEqual(len(row["unverifiableBuildRoutes"]), 1)
        self.assertIn("FAIL", audit.markdown(report))
        self.assertIn("another-article", audit.markdown(report))

    def add_co_migration_fixture(self, *, refresh=None, target_in_index=True):
        import hashlib
        source = next(s for s in audit.sync_sources.SOURCES if s["id"] == "co")
        base = source["base"]
        url = base + "posts/storage/cache-comprehensive.html"
        target = base + "posts/storage/cache-mapping.html"
        # Preserve the migration URL and successor as separate route records.
        mapping = {"posts_storage_cache-comprehensive.md": "old-v1",
                   "posts_storage_cache-mapping.md": "target-v1"}
        if not target_in_index:
            live = {key: value for key, value in mapping.items() if "cache-mapping" not in key}
        else:
            live = mapping
        (self.root / ".cache/co-index-live-20261120.html").write_text(self.raw(live), encoding="utf-8")
        self.articles = [a for a in self.articles if a["sourceId"] != "co"]
        for address in (url, target):
            key = address[len(base):-5].replace("/", "_") + ".md"
            own = base + f"assets/{key}.{mapping[key]}.lean.js"
            redirect = refresh if address == url else ""
            canonical = f'<link rel="canonical" href="{target[:-5]}">' if address == url else ""
            page = ("<html><head>" + self.raw(mapping) + canonical + redirect
                    + f'<link rel="canonical" href="{address}"><link rel="modulepreload" href="{own}">'
                    + '</head><body><main class="vp-doc"><h1>Cache</h1><p>迁移范围</p></main></body></html>')
            cache = f".cache/{mapping[key]}.html"
            (self.root / cache).write_text(page, encoding="utf-8")
            parsed = audit.sync_sources.parse_article(page, address)
            body_hash = hashlib.sha256(json.dumps(parsed["blocks"], ensure_ascii=False).encode()).hexdigest()
            self.articles.append({"sourceId": "co", "url": address, "cache": cache, "contentHash": body_hash})
        self.write_articles()

    def test_observed_co_retained_migration_preserves_distinct_routes(self):
        self.add_co_migration_fixture(refresh='<meta http-equiv="refresh" content="0;url=/co-blog/posts/storage/cache-mapping">')
        report = audit.audit_catalog(self.root, "20261120")
        row = next(r for r in report["subjects"] if r["sourceId"] == "co")
        item = row["cacheRecords"][0]
        self.assertTrue(report["routeInventoryMatches"])
        self.assertTrue(report["articleBuildHashesMatch"])
        self.assertTrue(item["cacheEvidenceMatches"])
        self.assertFalse(item["canonicalIdentityMatches"])
        self.assertFalse(item["canonicalAliasApplied"])
        self.assertEqual(item["retainedMigration"]["targetUrl"], row["cacheRecords"][1]["url"])
        self.assertEqual(row["retainedMigrationRecordCount"], 1)
        self.assertFalse(report["contentApproved"])
        self.assertIn("保留迁移页", audit.markdown(report))

    def test_co_retained_migration_requires_exact_single_refresh_and_indexed_successor(self):
        correct = '<meta http-equiv="refresh" content="0;url=/co-blog/posts/storage/cache-mapping">'
        for refresh, target_in_index in (("", True), (correct + correct, True),
                                         (correct.replace("cache-mapping", "cache-concept"), True),
                                         (correct, False)):
            with self.subTest(refresh=refresh, target_in_index=target_in_index):
                self.add_co_migration_fixture(refresh=refresh, target_in_index=target_in_index)
                report = audit.audit_catalog(self.root, "20261120")
                row = next(r for r in report["subjects"] if r["sourceId"] == "co")
                self.assertFalse(report["articleBuildHashesMatch"])
                self.assertFalse(row["cacheRecords"][0]["cacheEvidenceMatches"])
                self.assertNotIn("retainedMigration", row["cacheRecords"][0])

    def test_non_os_canonical_suffix_mismatch_is_not_an_alias(self):
        for sid in ("co", "cn", "ds"):
            index = next(i for i, a in enumerate(self.articles) if a["sourceId"] == sid)
            url = self.articles[index]["url"]
            with self.subTest(source=sid):
                self.set_canonicals(index, [url[:-5]])
                report = audit.audit_catalog(self.root, "20261120")
                row = next(r for r in report["subjects"] if r["sourceId"] == sid)
                self.assertFalse(row["articleBuildHashesMatch"])
                self.assertEqual(row["cacheRecords"][0]["normalizedCanonicalUrls"], [url[:-5]])

    def test_article_route_validation_does_not_accept_url_syntax_aliases(self):
        os_source = audit.sync_sources.SOURCES[0]
        url = self.articles[0]["url"]
        for route in (url + ".html", url + "?q=1", url + "#fragment", url + "?", url + "#", url.replace("/topic/", "/topic/../"),
                      url.replace("/topic/", "/topic%2F"), url.replace("https:", "http:")):
            with self.subTest(route=route), self.assertRaises(ValueError):
                audit.canonical_evidence([route + ".html"], route, os_source)

    def test_empty_article_array_fails_before_apply_writes_any_report(self):
        self.articles = []
        self.write_articles()
        with redirect_stdout(io.StringIO()) as out:
            result = audit.main(["--root", str(self.root), "--snapshot-date", "20261120", "--apply"])
        data = json.loads(out.getvalue())
        self.assertEqual(result, 1)
        self.assertFalse(data["reportsWritten"])
        self.assertIn("nonempty", data["error"])
        self.assertFalse((self.root / "data/reports").exists())

    def test_blank_and_nonstring_article_urls_are_rejected(self):
        for value in ("", " ", "\t", None, 42, self.articles[0]["url"] + " "):
            with self.subTest(value=value):
                self.articles[0]["url"] = value
                self.write_articles()
                with self.assertRaisesRegex(ValueError, "URL strings"):
                    audit.audit_catalog(self.root, "20261120")

    def test_source_with_no_local_records_cannot_match_by_empty_all(self):
        self.articles = [a for a in self.articles if a["sourceId"] != "os"]
        self.write_articles()
        report = audit.audit_catalog(self.root, "20261120")
        row = report["subjects"][0]
        self.assertFalse(row["articleBuildHashesMatch"])
        self.assertFalse(row["cacheEvidenceMatches"])
        self.assertFalse(report["articleBuildHashesMatch"])
        self.assertIn("no local article records", row["inputError"])
        self.assertIn(row["inputError"], audit.markdown(report))

    def test_report_junction_inside_root_is_rejected(self):
        report = audit.audit_catalog(self.root, "20261120")
        target = self.root / "preserved-reports"
        target.mkdir()
        sentinel = target / "source-catalog-2026-11-20.json"
        sentinel.write_bytes(b"preserve")
        with self.directory_alias(self.root / "data/reports", target):
            with self.assertRaisesRegex(ValueError, "reparse"):
                audit.write_reports(self.root, "20261120", report)
        self.assertEqual(sentinel.read_bytes(), b"preserve")
        self.assertEqual(len(list(target.iterdir())), 1)

    def test_report_parent_junction_inside_root_is_rejected(self):
        report = audit.audit_catalog(self.root, "20261120")
        target = self.root / "saved-data"
        (self.root / "data").rename(target)
        before = (target / "articles.json").read_bytes()
        with self.directory_alias(self.root / "data", target):
            with self.assertRaisesRegex(ValueError, "reparse"):
                audit.write_reports(self.root, "20261120", report)
        self.assertEqual((target / "articles.json").read_bytes(), before)
        self.assertFalse((target / "reports").exists())

    def test_both_report_hardlinks_preserve_external_sentinels(self):
        report = audit.audit_catalog(self.root, "20261120")
        out = self.root / "data/reports"
        out.mkdir()
        with tempfile.TemporaryDirectory() as outside:
            sentinels = []
            for suffix in ("json", "md"):
                sentinel = Path(outside) / ("preserve." + suffix)
                sentinel.write_bytes(("preserve-" + suffix).encode())
                path = out / ("source-catalog-2026-11-20." + suffix)
                os.link(sentinel, path)
                sentinels.append((sentinel, path))
            audit.write_reports(self.root, "20261120", report)
            for sentinel, path in sentinels:
                self.assertEqual(sentinel.read_bytes(), ("preserve-" + sentinel.suffix[1:]).encode())
                self.assertFalse(os.path.samefile(sentinel, path))
                self.assertEqual(path.stat().st_nlink, 1)

    def test_unsafe_second_target_preflight_preserves_first_report(self):
        report = audit.audit_catalog(self.root, "20261120")
        out = self.root / "data/reports"
        out.mkdir()
        first = out / "source-catalog-2026-11-20.json"
        first.write_bytes(b"old-json")
        (out / "source-catalog-2026-11-20.md").mkdir()
        with self.assertRaisesRegex(ValueError, "ordinary"):
            audit.write_reports(self.root, "20261120", report)
        self.assertEqual(first.read_bytes(), b"old-json")
        self.assertFalse(list(out.glob("*.tmp")))

    def test_fixed_temporary_hardlink_collision_is_untouched(self):
        report = audit.audit_catalog(self.root, "20261120")
        out = self.root / "data/reports"
        out.mkdir()
        sentinel = self.root / "preserve.tmp"
        sentinel.write_bytes(b"preserve")
        collision = out / "source-catalog-2026-11-20.json.tmp"
        os.link(sentinel, collision)
        audit.write_reports(self.root, "20261120", report)
        self.assertEqual(sentinel.read_bytes(), b"preserve")
        self.assertTrue(os.path.samefile(sentinel, collision))
        self.assertEqual(list(out.glob("*.tmp")), [collision])

    def test_staging_failure_leaves_both_existing_reports_unchanged(self):
        report = audit.audit_catalog(self.root, "20261120")
        out = self.root / "data/reports"
        out.mkdir()
        paths = [out / ("source-catalog-2026-11-20." + suffix) for suffix in ("json", "md")]
        for path in paths:
            path.write_bytes(b"old")
        original = audit.tempfile.mkstemp
        calls = []
        def fail_second(**kwargs):
            calls.append(kwargs)
            if len(calls) == 2:
                raise OSError("injected staging failure")
            return original(**kwargs)
        with mock.patch.object(audit.tempfile, "mkstemp", side_effect=fail_second):
            with self.assertRaisesRegex(OSError, "injected"):
                audit.write_reports(self.root, "20261120", report)
        self.assertEqual([path.read_bytes() for path in paths], [b"old", b"old"])
        self.assertFalse(list(out.glob("*.tmp")))

    def test_replace_failure_never_reports_success_and_exposes_possible_partial_pair(self):
        out = self.root / "data/reports"
        out.mkdir()
        paths = [out / ("source-catalog-2026-11-20." + suffix) for suffix in ("json", "md")]
        original = audit.os.replace
        for failure_at in (1, 2):
            for path in paths:
                path.write_bytes(b"old")
            calls = []
            def fail_replace(source, target):
                calls.append(target)
                if len(calls) == failure_at:
                    raise OSError("injected publication failure")
                return original(source, target)
            with self.subTest(failure_at=failure_at), mock.patch.object(audit.os, "replace", side_effect=fail_replace):
                with redirect_stdout(io.StringIO()) as captured:
                    result = audit.main(["--root", str(self.root), "--snapshot-date", "20261120", "--apply"])
                data = json.loads(captured.getvalue())
                self.assertEqual(result, 1)
                self.assertFalse(data["reportsWritten"])
                self.assertTrue(data["reportsMayBePartial"])
                self.assertFalse(data["contentApproved"])
                self.assertEqual(paths[1].read_bytes(), b"old")
                if failure_at == 1:
                    self.assertEqual(paths[0].read_bytes(), b"old")
                self.assertFalse(list(out.glob("*.tmp")))

    def test_default_cli_preserves_all_fixture_files_and_never_fetches(self):
        before = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        with mock.patch.object(audit.sync_sources, "urlopen") as fetch, redirect_stdout(io.StringIO()):
            self.assertEqual(audit.main(["--root", str(self.root), "--snapshot-date", "20261120"]), 0)
        after = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        fetch.assert_not_called()

    def test_apply_publishes_failure_evidence_without_content_approval(self):
        self.set_canonicals(2, [self.articles[2]["url"], self.articles[3]["url"]])
        with redirect_stdout(io.StringIO()) as captured:
            result = audit.main(["--root", str(self.root), "--snapshot-date", "20261120", "--apply"])
        self.assertEqual(result, 1)
        self.assertTrue(json.loads(captured.getvalue())["reportsWritten"])
        report = json.loads((self.root / "data/reports/source-catalog-2026-11-20.json").read_text(encoding="utf-8"))
        self.assertFalse(report["articleBuildHashesMatch"])
        self.assertFalse(report["contentApproved"])
        self.assertIn("FAIL", (self.root / "data/reports/source-catalog-2026-11-20.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
