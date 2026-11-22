import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from scripts import build_study_workspace as builder


class StudyWorkspaceTests(unittest.TestCase):
    def project(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        (root / "data").mkdir()
        (root / ".cache").mkdir()
        raw = '<main class="vp-doc"><h1>系统</h1><h2 id="tlb">TLB</h2><p>TLB是用于缓存近期页表项的高速缓冲存储器。</p><h2 id="empty">交互演示</h2></main>'
        (root / ".cache/source.html").write_text(raw, encoding="utf-8")
        parsed = builder.atomic.sync_sources.parse_article(raw, "https://example.test/os/tlb")
        manifest = {"version": 1, "articles": [{"sourceId": "os", "title": "系统", "url": "https://example.test/os/tlb",
            "cache": ".cache/source.html", "contentHash": builder.curated._hash_parsed_article(parsed)}]}
        (root / "data/articles.json").write_text(json.dumps(manifest), encoding="utf-8")
        return root, manifest

    def test_all_sections_and_fragment_candidates_survive_without_approval(self):
        root, _ = self.project()
        result = builder.build_workspace(root)
        index = result["index"]
        self.assertEqual(index["summary"]["articles"], 1)
        self.assertEqual(index["summary"]["sections"], 2)
        self.assertEqual(index["summary"]["emptySections"], 1)
        self.assertGreater(index["summary"]["atomicCandidates"], 0)
        shard = json.loads(next(iter(result["shards"].values())))
        self.assertIn("#tlb", shard["atomicCandidates"][0]["articleUrl"])
        self.assertFalse(index["contentApproved"])
        self.assertFalse(index["claimsFullKnowledgeCoverage"])
        self.assertEqual(index["summary"]["approvedCards"], 0)
        self.assertFalse(shard["contentApproved"])
        self.assertFalse((root / "data/study").exists())

    def test_published_checksums_and_versioned_paths_match_exact_bytes(self):
        root, _ = self.project()
        result = builder.build_workspace(root)
        builder.publish(root, result)
        index = json.loads((root / "data/study/index.json").read_bytes())
        item = index["articles"][0]
        self.assertRegex(item["file"], r"^snapshots/[a-f0-9]{20}/articles/os-[a-f0-9]{16}\.json$")
        raw = (root / "data/study" / item["file"]).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), item["sha256"])
        self.assertEqual(len(raw), item["bytes"])
        builder.publish(root, result)
        self.assertEqual(index, json.loads((root / "data/study/index.json").read_bytes()))

    def test_formal_cards_and_reviews_remain_untouched(self):
        root, _ = self.project()
        sentinels = [root / "data/cards/cards.json", root / "data/knowledge-units.json"]
        for path in sentinels:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'{"sentinel": "preserve"}')
        before = [p.read_bytes() for p in sentinels]
        builder.publish(root, builder.build_workspace(root))
        self.assertEqual(before, [p.read_bytes() for p in sentinels])

    def test_new_snapshot_preserves_old_shards_for_open_tabs(self):
        root, _ = self.project()
        result = builder.build_workspace(root)
        builder.publish(root, result)
        old_index = json.loads((root / "data/study/index.json").read_bytes())
        old_path = root / "data/study" / old_index["articles"][0]["file"]
        old_bytes = old_path.read_bytes()
        next_result = copy.deepcopy(result)
        next_result["index"]["notice"] = "updated boundary"
        builder.publish(root, next_result)
        new_index = json.loads((root / "data/study/index.json").read_bytes())
        self.assertNotEqual(new_index["articles"][0]["file"], old_index["articles"][0]["file"])
        self.assertEqual(old_bytes, old_path.read_bytes())

    def test_stale_cache_and_path_escape_fail_closed(self):
        root, manifest = self.project()
        (root / ".cache/source.html").write_text('<main class="vp-doc"><p>changed</p></main>', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "differs from manifest"):
            builder.build_workspace(root)
        manifest["articles"][0]["cache"] = "../../outside.html"
        (root / "data/articles.json").write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "article errors|escapes"):
            builder.build_workspace(root)
        self.assertFalse((root / "data/study").exists())

    def test_duplicate_articles_rejected(self):
        root, manifest = self.project()
        manifest["articles"].append(manifest["articles"][0])
        (root / "data/articles.json").write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "duplicate article"):
            builder.build_workspace(root)

    def test_generation_error_and_unknown_candidate_rejected(self):
        root, _ = self.project()
        with self.assertRaisesRegex(ValueError, "article errors"):
            builder.build_workspace(root, {"articleErrors": [{"reason": "missing"}]})
        with self.assertRaisesRegex(ValueError, "unknown article"):
            builder.build_workspace(root, {"articleErrors": [], "candidates": [{"articleUrl": "https://other.test/"}]})

    def test_curated_changes_during_validation_rejected(self):
        root, _ = self.project()
        (root / "data/curated").mkdir()
        path = root / "data/curated/draft.json"
        path.write_text('{}', encoding="utf-8")
        with mock.patch.object(builder.curated, "audit_article", return_value={"structuralOk": True, "candidateSha256": "0" * 64}):
            with self.assertRaisesRegex(ValueError, "changed during build"):
                builder.build_workspace(root)

    def test_invalid_curated_not_silently_omitted(self):
        root, _ = self.project()
        (root / "data/curated").mkdir()
        path = root / "data/curated/draft.json"
        raw = b'{}'
        path.write_bytes(raw)
        with mock.patch.object(builder.curated, "audit_article", return_value={"structuralOk": False, "candidateSha256": hashlib.sha256(raw).hexdigest(), "errors": ["fixture error"]}):
            with self.assertRaisesRegex(ValueError, "invalid curated"):
                builder.build_workspace(root)

    def test_explicit_empty_frozen_selection_ignores_in_progress_draft(self):
        root, _ = self.project()
        (root / "data/curated").mkdir()
        (root / "data/curated/in-progress.json").write_text("{", encoding="utf-8")
        result = builder.build_workspace(root, curated_files=[])
        self.assertEqual(result["index"]["summary"]["articles"], 1)
        self.assertEqual(result["index"]["summary"]["curatedCandidates"], 0)

    def test_explicit_selection_rejects_escape_and_duplicate(self):
        root, _ = self.project()
        for files in (["data/other.json"], ["../escape.json"],
                      ["data/curated/a.json", "data/curated/a.json"]):
            with self.subTest(files=files), self.assertRaises(ValueError):
                builder.build_workspace(root, curated_files=files)

    def test_explicit_selection_never_silently_omits_missing_file(self):
        root, _ = self.project()
        with self.assertRaises(OSError):
            builder.build_workspace(root, curated_files=["data/curated/missing.json"])

    def test_cli_default_read_only_and_json_summary(self):
        root, _ = self.project()
        script = Path(builder.__file__).resolve()
        process = subprocess.run([sys.executable, "-X", "utf8", str(script), "--root", str(root)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout)["mode"], "dry-run")
        self.assertFalse((root / "data/study").exists())

    def test_atomic_replacement_does_not_follow_existing_hardlink(self):
        import os
        root, _ = self.project()
        source = root / "keep.txt"
        source.write_bytes(b"keep")
        linked = root / "alias.txt"
        os.link(source, linked)
        builder.write_atomic(linked, b"new")
        self.assertEqual(source.read_bytes(), b"keep")
        self.assertEqual(linked.read_bytes(), b"new")

    def add_curated_draft(self, root, manifest, authored):
        record = manifest["articles"][0]
        parsed = builder.atomic.sync_sources.parse_article(
            (root / record["cache"]).read_text(encoding="utf-8"), record["url"])
        units = []
        for section in builder.atomic.sync_sources.sections(parsed):
            for block in section.get("sourceUnits", []):
                for unit in block["units"]:
                    units.append({"knowledgeUnitId": unit["id"], "sourceId": record["sourceId"],
                        "articleUrl": record["url"], "articleTitle": record["title"],
                        "sectionIndex": section["sectionIndex"], "sectionHeadingPath": section["headingPath"],
                        "sectionAnchor": section["anchor"], "blockIndex": unit["blockIndex"],
                        "unitIndex": unit["unitIndex"], "tag": unit["tag"], "text": unit["text"],
                        "href": unit.get("href", ""), "title": unit.get("title", ""),
                        "src": unit.get("src", ""), "alt": unit.get("alt", ""), "cardIds": []})
        uid = units[0]["knowledgeUnitId"]
        cid = builder.curated.stable_card_id(record["url"], [uid])
        if authored:
            document = {"schema": builder.curated.SCHEMA, "version": builder.curated.VERSION,
                "sourceId": record["sourceId"], "articleUrl": record["url"],
                "articleContentHash": record["contentHash"], "author": {"kind": "ai", "agent": "fixture"},
                "cards": [{"id": cid, "question": "TLB缓存什么？", "answer": "近期使用的页表项。", "unitIds": [uid],
                           "assumptions": ["页式虚拟存储"], "sourceNotes": ["仅作候选，待独立核查"]}],
                "unitDisposition": [{"unitId": uid, "action": "card", "cardIds": [cid]}], "issues": []}
        else:
            document = {"schema": builder.curated.SCHEMA, "version": builder.curated.VERSION,
                "article": dict(record),
                "sourceUnits": [{"knowledgeUnitId": uid, "disposition": "card", "cardId": cid}],
                "cards": [{"cardId": cid, "articleUrl": record["url"], "front": "TLB缓存什么？",
                           "back": "近期使用的页表项。", "knowledgeUnitIds": [uid]}]}
        for relative, value in (("data/knowledge-units.json", {"version": 2, "units": units}),
                                ("data/cards/cards.json", {"version": 1, "cards": []}),
                                ("data/curated/draft.json", document)):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return document

    def test_both_curated_schemas_export_display_dto_and_preserve_document(self):
        for authored in (False, True):
            with self.subTest(authored=authored):
                root, manifest = self.project()
                original = self.add_curated_draft(root, manifest, authored)
                path = root / "data/curated/draft.json"
                before = path.read_bytes()
                audit = builder.curated.audit_article(path, root)
                self.assertTrue(audit["structuralOk"], audit["errors"])
                result = builder.build_workspace(root)
                shard = json.loads(next(iter(result["shards"].values())))
                draft = shard["curated"][0]
                card = original["cards"][0]
                self.assertEqual(draft["document"], original)
                self.assertEqual(draft["sha256"], hashlib.sha256(before).hexdigest())
                self.assertEqual(draft["displayCards"], [{
                    "id": card.get("id", card.get("cardId")),
                    "question": "TLB缓存什么？", "answer": "近期使用的页表项。",
                    "unitIds": card.get("unitIds", card.get("knowledgeUnitIds")),
                    "assumptions": card.get("assumptions", []), "sourceNotes": card.get("sourceNotes", [])}])
                self.assertFalse(draft["validation"]["contentApproved"])
                self.assertEqual(path.read_bytes(), before)

    def test_unit_backlog_preserves_every_record_separately_from_section_backlog(self):
        root, manifest = self.project()
        # Include an inline link in a section which also has an atomic candidate.
        cache = root / ".cache/source.html"
        raw = cache.read_text(encoding="utf-8").replace("。</p>", '。<a href="https://example.test/reference">参考材料</a></p>')
        cache.write_text(raw, encoding="utf-8")
        manifest["articles"][0]["contentHash"] = builder.curated._hash_parsed_article(
            builder.atomic.sync_sources.parse_article(raw, manifest["articles"][0]["url"]))
        (root / "data/articles.json").write_text(json.dumps(manifest), encoding="utf-8")
        report = builder.atomic.build_candidate_set(root)
        result = builder.build_workspace(root, report)
        shard = json.loads(next(iter(result["shards"].values())))
        self.assertEqual(shard["unitBacklog"], report["backlog"])
        self.assertEqual(shard["sectionBacklog"], report["sectionBacklog"])
        for summary in (shard["article"]["summary"], result["index"]["summary"]):
            self.assertEqual(summary["unitBacklog"], len(report["backlog"]))
            self.assertEqual(summary["sectionBacklog"], len(report["sectionBacklog"]))
        self.assertTrue(any(b["reason"] == "inline-link-needs-review" and b["sectionIndex"] == 1
                            for b in shard["unitBacklog"]))
        self.assertTrue(any(c["sectionIndex"] == 1 for c in shard["atomicCandidates"]))

    def test_backlog_unknown_article_is_not_silently_dropped(self):
        root, _ = self.project()
        for field in ("backlog", "sectionBacklog"):
            with self.subTest(field=field):
                report = builder.atomic.build_candidate_set(root)
                report[field].append({"articleUrl": "https://other.test/", "reason": "needs-review"})
                with self.assertRaisesRegex(ValueError, "unknown article"):
                    builder.build_workspace(root, report)

    def make_redirect(self, path, target, junction):
        path.parent.mkdir(parents=True, exist_ok=True)
        if junction:
            process = subprocess.run(["cmd", "/c", "mklink", "/J", str(path), str(target)],
                                     capture_output=True, text=True)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            self.addCleanup(lambda: path.rmdir() if path.exists() else None)
        else:
            try:
                path.symlink_to(target, target_is_directory=True)
            except OSError as exc:
                self.skipTest("directory symlinks unavailable: " + str(exc))
            self.addCleanup(lambda: path.unlink() if path.is_symlink() else None)

    def assert_redirect_components_rejected(self, junction, empty):
        # Exercise every fixed publication directory, including empty inventories.
        for component in ("data", "study", "snapshots", "generation", "articles"):
            with self.subTest(component=component, junction=junction, empty=empty):
                root, manifest = self.project()
                if empty:
                    manifest["articles"] = []
                    (root / "data/articles.json").write_text(json.dumps(manifest), encoding="utf-8")
                result = builder.build_workspace(root)
                snapshot = builder.digest(json.dumps(result["index"], sort_keys=True, ensure_ascii=False).encode())[:20]
                generation = root / "data/study/snapshots" / snapshot
                path = {"data": root / "data", "study": root / "data/study",
                        "snapshots": root / "data/study/snapshots", "generation": generation,
                        "articles": generation / "articles"}[component]
                target = root / "protected"
                if path.exists():
                    path.rename(target)
                else:
                    target.mkdir()
                sentinel = target / "KEEP-UNRELATED"
                sentinel.write_bytes(b"keep")
                if not empty and component == "articles":
                    sentinel = target / next(iter(result["shards"])).split("/")[-1]
                    sentinel.write_bytes(b"keep")
                before = {p.relative_to(target).as_posix(): p.read_bytes() for p in target.rglob("*") if p.is_file()}
                self.make_redirect(path, target, junction)
                with self.assertRaisesRegex(ValueError, "reparse|symlink|namespace"):
                    builder.publish(root, result)
                self.assertEqual(before, {p.relative_to(target).as_posix(): p.read_bytes()
                                         for p in target.rglob("*") if p.is_file()})

    @unittest.skipUnless(os.name == "nt", "NTFS junction regression")
    def test_junction_components_rejected_nonempty(self):
        self.assert_redirect_components_rejected(junction=True, empty=False)

    @unittest.skipUnless(os.name == "nt", "NTFS junction regression")
    def test_junction_components_rejected_empty_inventory(self):
        self.assert_redirect_components_rejected(junction=True, empty=True)

    def test_symlink_components_rejected_nonempty(self):
        self.assert_redirect_components_rejected(junction=False, empty=False)

    def test_symlink_components_rejected_empty_inventory(self):
        self.assert_redirect_components_rejected(junction=False, empty=True)

    @unittest.skipUnless(os.name == "nt", "NTFS junction regression")
    def test_empty_inventory_study_junction_cannot_write_index_outside_root(self):
        root, manifest = self.project()
        manifest["articles"] = []
        (root / "data/articles.json").write_text(json.dumps(manifest), encoding="utf-8")
        result = builder.build_workspace(root)
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        target = Path(outside.name)
        self.make_redirect(root / "data/study", target, junction=True)
        with self.assertRaisesRegex(ValueError, "reparse|symlink|namespace"):
            builder.publish(root, result)
        self.assertEqual(list(target.iterdir()), [])

    def test_publication_rejects_escaping_shard_before_writing_any_shard(self):
        root, _ = self.project()
        result = builder.build_workspace(root)
        result["shards"]["../../../../protected.json"] = b"overwrite"
        with self.assertRaisesRegex(ValueError, "namespace|shard path"):
            builder.publish(root, result)
        self.assertFalse((root / "data/study").exists())

    def test_symlink_lstat_mode_rejected_without_windows_attributes(self):
        root, _ = self.project()
        result = builder.build_workspace(root)
        snapshot = builder.digest(json.dumps(result["index"], sort_keys=True, ensure_ascii=False).encode())[:20]
        generation = root / "data/study/snapshots" / snapshot
        original_lstat = Path.lstat
        for redirected in (root / "data", root / "data/study", root / "data/study/snapshots",
                           generation, generation / "articles", root / "data/study/index.json",
                           generation / next(iter(result["shards"]))):
            with self.subTest(path=redirected.relative_to(root).as_posix()):
                def lstat(path, *args, **kwargs):
                    if path == redirected:
                        return os.stat_result((builder.stat.S_IFLNK | 0o777, 0, 0, 0, 0, 0, 0, 0, 0, 0))
                    return original_lstat(path, *args, **kwargs)
                with mock.patch.object(Path, "lstat", lstat):
                    with self.assertRaisesRegex(ValueError, "symlink/reparse"):
                        builder.publish(root, result)
                self.assertFalse((root / "data/study").exists())

if __name__ == "__main__":
    unittest.main()
