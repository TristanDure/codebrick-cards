"""Offline preparation regressions; real builds run only on temporary fixtures."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from scripts import prepare_workspace as prepare


class PrepareWorkspaceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.stderr = io.StringIO()

    def main(self, *args):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(self.stderr):
            return prepare.main(["--root", str(self.root), *args])

    def fixture(self):
        (self.root / "data").mkdir(exist_ok=True)
        (self.root / ".cache").mkdir(exist_ok=True)
        (self.root / ".cache/source.html").write_text(
            '<main class="vp-doc"><h1>自编测试</h1><h2 id="queue">队列</h2><p>队列按先进先出的顺序移除元素。</p></main>', encoding="utf-8")
        from scripts.sync_sources import parse_article
        from scripts.import_curated_articles import _hash_parsed_article
        url = "https://demo.invalid/ds/test"
        content_hash = _hash_parsed_article(parse_article(
            (self.root / ".cache/source.html").read_text(encoding="utf-8"), url))
        (self.root / "data/articles.json").write_text(json.dumps({"articles": [
            {"sourceId": "ds", "url": url, "title": "自编测试",
             "cache": ".cache/source.html", "contentHash": content_hash}]}), encoding="utf-8")

    def sentinel_files(self):
        paths = ["data/cards/cards.json", "data/knowledge-units.json", "data/progress.json",
                 "data/reviews.json", "exports/progress.json"]
        result = {}
        for name in paths:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'{"sentinel": "keep", "reviewCount": 17}')
            result[path] = path.read_bytes()
        return result

    def test_clean_clone_missing_manifest_is_actionable_and_never_runs_subprocess(self):
        with mock.patch.object(prepare.subprocess, "run") as run:
            self.assertEqual(self.main(), 1)
        run.assert_not_called()
        self.assertIn("data", self.stderr.getvalue())
        self.assertIn("--sync", self.stderr.getvalue())
        self.assertIn("--demo", self.stderr.getvalue())
        self.assertFalse((self.root / "data").exists())

    def test_missing_empty_or_malformed_inventory_fails_before_build(self):
        for manifest in ({"articles": []}, [], {"articles": "bad"}, {"articles": [None]}):
            with self.subTest(manifest=manifest):
                (self.root / "data").mkdir(exist_ok=True)
                (self.root / "data/articles.json").write_text(json.dumps(manifest), encoding="utf-8")
                with mock.patch.object(prepare.subprocess, "run") as run:
                    self.assertEqual(self.main(), 1)
                run.assert_not_called()
        (self.root / "data/articles.json").write_text("{broken", encoding="utf-8")
        self.assertEqual(self.main(), 1)

    def test_cache_path_allows_normalized_windows_long_short_path_forms(self):
        if self.root.drive != Path(tempfile.gettempdir()).resolve().drive:
            self.skipTest("temp and fixture must share a drive")
        self.fixture()
        self.assertIsNone(prepare.check_cache(self.root))

    def test_missing_html_and_escaping_cache_are_rejected(self):
        self.fixture()
        (self.root / ".cache/source.html").unlink()
        with mock.patch.object(prepare.subprocess, "run") as run:
            self.assertEqual(self.main(), 1)
        run.assert_not_called()
        self.assertIn("Missing HTML cache", self.stderr.getvalue())
        (self.root / "data/articles.json").write_text(
            json.dumps({"articles": [{"cache": "../outside.html"}]}), encoding="utf-8")
        self.assertEqual(self.main(), 1)
        self.assertIn("escapes project root", self.stderr.getvalue())

    def test_default_calls_only_builder_with_utf8_and_frozen_files(self):
        self.fixture()
        with mock.patch.object(prepare.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertEqual(self.main("--curated-file", "data/curated/one.json", "--curated-file", "data/curated/two.json"), 0)
        command = run.call_args.args[0]
        self.assertEqual(command[:3], [sys.executable, "-X", "utf8"])
        self.assertEqual(Path(command[3]).name, "build_study_workspace.py")
        self.assertIn("--apply", command)
        self.assertEqual(command[-4:], ["--curated-file", "data/curated/one.json", "--curated-file", "data/curated/two.json"])
        self.assertEqual(run.call_count, 1)

    def test_sync_failure_is_nonzero_without_fallback_build(self):
        self.fixture()
        with mock.patch.object(prepare.subprocess, "run", return_value=subprocess.CompletedProcess([], 7)) as run:
            self.assertEqual(self.main("--sync"), 7)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(Path(run.call_args.args[0][3]), self.root / "scripts/sync_sources.py")

    def test_sync_runs_before_preflight_and_build(self):
        def fake_run(command, **kwargs):
            if Path(command[3]).name == "sync_sources.py":
                self.fixture()
            return subprocess.CompletedProcess(command, 0)
        with mock.patch.object(prepare.subprocess, "run", side_effect=fake_run) as run:
            self.assertEqual(self.main("--sync"), 0)
        self.assertEqual([Path(c.args[0][3]).name for c in run.call_args_list],
                         ["sync_sources.py", "build_study_workspace.py"])

    def test_build_failure_and_spawn_error_return_nonzero(self):
        self.fixture()
        for outcome in (subprocess.CompletedProcess([], 9), OSError("cannot launch Python")):
            with self.subTest(outcome=outcome):
                with mock.patch.object(prepare.subprocess, "run", **(
                        {"side_effect": outcome} if isinstance(outcome, Exception) else {"return_value": outcome})):
                    self.assertNotEqual(self.main(), 0)
        self.assertIn("failed", self.stderr.getvalue())

    def test_real_offline_build_is_repeatable_and_preserves_data(self):
        self.fixture()
        before = self.sentinel_files()
        before[self.root / "data/articles.json"] = (self.root / "data/articles.json").read_bytes()
        for _ in range(2):
            self.assertEqual(self.main(), 0, self.stderr.getvalue())
        index = json.loads((self.root / "data/study/index.json").read_bytes())
        self.assertEqual(index["summary"]["articles"], 1)
        self.assertFalse(index["contentApproved"])
        for path, raw in before.items():
            self.assertEqual(path.read_bytes(), raw)

    def test_real_demo_publishes_four_original_subjects_without_source_data(self):
        before = self.sentinel_files()
        with contextlib.redirect_stdout(io.StringIO()):
            result = prepare.prepare_demo(self.root)
        self.assertEqual(result, 0, self.stderr.getvalue())
        index = json.loads((self.root / "data/study/index.json").read_bytes())
        self.assertEqual(index["summary"]["articles"], 4)
        self.assertFalse(index["contentApproved"])
        shards = [json.loads((self.root / "data/study" / article["file"]).read_bytes()) for article in index["articles"]]
        self.assertEqual({shard["article"]["sourceId"] for shard in shards}, {"os", "co", "cn", "ds"})
        for article in index["articles"]:
            raw = (self.root / "data/study" / article["file"]).read_text(encoding="utf-8")
            self.assertIn("demo.invalid", raw)
            self.assertNotIn("www.codebrick.tech", raw)
        for path, raw in before.items():
            self.assertEqual(path.read_bytes(), raw)
        self.assertFalse((self.root / "data/articles.json").exists())
        self.assertFalse((self.root / ".cache").exists())
        from scripts.verify_study_workspace import verify
        self.assertEqual(verify(self.root), 4)
        self.assertGreaterEqual(index["summary"]["atomicCandidates"], 4)
        self.assertTrue(all(shard["atomicCandidates"] for shard in shards))
        published = (self.root / "data/study/index.json").read_bytes()
        self.assertEqual(self.main("--demo"), 1)
        self.assertEqual((self.root / "data/study/index.json").read_bytes(), published)
        self.assertIn("different clean clone", self.stderr.getvalue())

    def test_existing_index_refuses_demo_before_any_build(self):
        index = self.root / "data/study/index.json"
        index.parent.mkdir(parents=True)
        index.write_bytes(b"existing real workspace")
        with mock.patch.object(prepare.subprocess, "run") as run:
            self.assertEqual(self.main("--demo"), 1)
        run.assert_not_called()
        self.assertEqual(index.read_bytes(), b"existing real workspace")

    def test_demo_build_failure_does_not_publish(self):
        with mock.patch.object(prepare.subprocess, "run", return_value=subprocess.CompletedProcess([], 5)):
            self.assertEqual(self.main("--demo"), 5)
        self.assertFalse((self.root / "data").exists())

    def test_sync_and_demo_are_mutually_exclusive(self):
        with self.assertRaises(SystemExit) as exit:
            self.main("--sync", "--demo")
        self.assertEqual(exit.exception.code, 2)

    def test_cli_works_outside_checkout_and_returns_missing_data_failure(self):
        result = subprocess.run([sys.executable, "-X", "utf8", str(prepare.SCRIPT_DIR / "prepare_workspace.py"),
                                 "--root", str(self.root)], cwd=self.root, capture_output=True, text=True,
                                encoding="utf-8")
        self.assertEqual(result.returncode, 1)
        self.assertIn("--demo", result.stderr)


if __name__ == "__main__":
    unittest.main()
