"""Prepare the study workbench offline, with opt-in demo or source synchronization."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
RECOVERY = "Restore data/articles.json and its HTML cache from your own backup, or run --sync to download real sources. For an offline example, use --demo in a separate clean clone."
DEMO_ARTICLES = (
    ("os", "操作系统", "进程与线程", "进程拥有独立的地址空间。同一进程内的线程共享地址空间，但各自保存执行所需的寄存器状态和栈。"),
    ("co", "计算机组成原理", "缓存命中", "缓存命中表示所需数据已在缓存中。若命中耗时为1，未命中总耗时为11，命中率为0.9，则平均访问耗时为2。"),
    ("cn", "计算机网络", "分组转发", "路由器按目的地址查找转发表。多个前缀都能匹配时，选择匹配位数最多的前缀。"),
    ("ds", "数据结构", "队列", "队列遵循先进先出规则。例如依次入队甲和乙，再出队一次，得到甲，队首变为乙。"),
)


def run_step(command: list[str], root: Path, label: str) -> int:
    print(label, flush=True)
    try:
        result = subprocess.run(command, cwd=root, check=False)
    except OSError as exc:
        print(f"{label} failed: {exc}", file=sys.stderr)
        return 1
    if result.returncode:
        print(f"{label} failed (exit {result.returncode}); preparation stopped.", file=sys.stderr)
        return result.returncode if result.returncode > 0 else 1
    return 0


def check_cache(root: Path) -> None:
    manifest_path = root / "data/articles.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Missing or unreadable {manifest_path}: {exc}. {RECOVERY}") from exc
    articles = manifest.get("articles") if isinstance(manifest, dict) else None
    if not isinstance(articles, list) or not articles:
        raise ValueError(f"{manifest_path} needs a non-empty articles list. {RECOVERY}")
    for number, article in enumerate(articles, 1):
        value = article.get("cache") if isinstance(article, dict) else None
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Article {number} has no HTML cache path. {RECOVERY}")
        cache = (root / value).resolve()
        if not cache.is_relative_to(root) or cache == root:
            raise ValueError(f"Article {number} cache escapes project root: {value}")
        if not cache.is_file():
            raise ValueError(f"Missing HTML cache: {cache}. {RECOVERY}")


def build_command(root: Path, curated_files: list[str] | None = None) -> list[str]:
    command = [sys.executable, "-X", "utf8", str(SCRIPT_DIR / "build_study_workspace.py"),
               "--root", str(root), "--apply"]
    for value in curated_files or []:
        command.extend(["--curated-file", value])
    return command


def prepare_demo(root: Path) -> int:
    index = root / "data/study/index.json"
    if index.exists() or index.is_symlink():
        raise ValueError(f"Demo refuses to overwrite {index}. Use --demo in a different clean clone to preserve your study workspace and progress.")
    with tempfile.TemporaryDirectory(prefix="codebrick-demo-") as temporary:
        staging = Path(temporary)
        (staging / "data").mkdir()
        (staging / ".cache/demo").mkdir(parents=True)
        articles = []
        for subject, name, heading, text in DEMO_ARTICLES:
            relative = f".cache/demo/{subject}.html"
            raw = f'<main class="vp-doc"><h1>{name}：自编演示</h1><h2 id="example">{heading}</h2><p>{text}</p></main>'.encode("utf-8")
            (staging / relative).write_bytes(raw)
            sys.path.insert(0, str(SCRIPT_DIR))
            try:
                import sync_sources
                import import_curated_articles
                url = f"https://demo.invalid/{subject}/original-example"
                parsed = sync_sources.parse_article(raw.decode("utf-8"), url)
                content_hash = import_curated_articles._hash_parsed_article(parsed)
            finally:
                sys.path.pop(0)
            articles.append({"sourceId": subject, "title": f"{name}：自编演示",
                             "url": f"https://demo.invalid/{subject}/original-example", "cache": relative,
                             "contentHash": content_hash})
        (staging / "data/articles.json").write_text(
            json.dumps({"version": 1, "articles": articles}, ensure_ascii=False), encoding="utf-8")
        code = run_step(build_command(staging), staging, "Build original offline demo (contentApproved=false)")
        if code:
            return code
        study = staging / "data/study"
        # Reuse the builder's guarded publication, including symlink/reparse checks.
        sys.path.insert(0, str(SCRIPT_DIR))
        try:
            import build_study_workspace as builder
        finally:
            sys.path.pop(0)
        demo_index = json.loads((study / "index.json").read_text(encoding="utf-8"))
        if demo_index.get("contentApproved") is not False:
            raise ValueError("Demo build must have contentApproved=false")
        # The CLI already built the candidate set; publish its exact shards with
        # an exclusive index creation so an intervening workspace is not replaced.
        builder._publication_path(root, "", directory=True)
        index.parent.mkdir(parents=True, exist_ok=True)
        for item in demo_index["articles"]:
            target = builder._publication_path(root, item["file"])
            builder.write_atomic(target, (study / item["file"]).read_bytes(), publication_root=root)
        builder._publication_path(root, "index.json")
        with index.open("xb") as stream:
            stream.write((study / "index.json").read_bytes())
    print("Offline demo ready: four original examples; contentApproved=false. Open the study workbench.")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="project/cache root (default: this checkout)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--sync", action="store_true", help="explicitly allow downloading real CodeBrick sources")
    mode.add_argument("--demo", action="store_true", help="prepare four original offline examples in a clean clone")
    parser.add_argument("--curated-file", action="append", help="forward a frozen curated file selection to the build; repeatable")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.demo and args.curated_file:
        parser.error("--curated-file cannot be used with --demo")
    try:
        if not root.is_dir():
            raise ValueError(f"Project root does not exist: {root}")
        if args.demo:
            return prepare_demo(root)
        if args.sync:
            # sync_sources has no --root: its own checkout determines its data paths.
            code = run_step([sys.executable, "-X", "utf8", str(root / "scripts/sync_sources.py")], root,
                            "Synchronize real sources (network enabled)")
            if code:
                return code
        check_cache(root)
        code = run_step(build_command(root, args.curated_file), root, "Build offline study workspace")
        if not code:
            print("Study workspace ready: data/study/index.json; contentApproved=false. Existing study progress is preserved.")
        return code
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Preparation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
