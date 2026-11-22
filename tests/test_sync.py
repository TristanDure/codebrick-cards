"""Offline contract tests for scripts.sync_sources.

The suite uses only local HTML and the standard library. It deliberately does
not fetch URLs from SOURCES.
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path
from unittest import mock

from scripts import sync_sources


ARTICLE_URL = "https://example.test/os-blog/offline-fixture"
ARTICLE_HTML = """<!doctype html>
<html>
  <head><title>Parser fixture</title></head>
  <body>
    <main class="vp-doc">
      <h1 id="offline-parsing-fixture">Offline parsing fixture</h1>
      <h2 id="first-topic">First topic</h2>
      <p>First answer has enough detail to become a useful card.</p>
      <h2 id="second-topic">Second topic</h2>
      <p>Second answer checks that extraction handles multiple sections.</p>
    </main>
  </body>
</html>
"""


def _as_items(value):
    """Normalize a list-like result or a mapping of records to an iterable."""
    if isinstance(value, Mapping):
        return list(value.values())
    if isinstance(value, (str, bytes)):
        return [value]
    return list(value)


def _get_field(record, *names):
    if isinstance(record, Mapping):
        for name in names:
            value = record.get(name)
            if value not in (None, ""):
                return value
    else:
        for name in names:
            value = getattr(record, name, None)
            if value not in (None, ""):
                return value
    return None


def _source_records(sources):
    """Keep mapping keys as source IDs when SOURCES is keyed by ID."""
    if not isinstance(sources, Mapping):
        return _as_items(sources)

    records = []
    for source_id, source in sources.items():
        if isinstance(source, Mapping):
            record = dict(source)
            record.setdefault("id", source_id)
        elif isinstance(source, str):
            record = {"id": source_id, "url": source}
        else:
            record = source
        records.append(record)
    return records


class SyncSourcesContractTests(unittest.TestCase):
    def _run_failed_sync(self, article_body, expect_failure=True):
        source = {
            "id": "os",
            "name": "Operating systems",
            "prefix": "os-blog",
            "base": "https://example.test/os-blog/",
            "extension": "",
        }
        article_url = source["base"] + "posts/offline-fixture"
        list_body = (
            '<script>self.__VP_HASH_MAP__ = JSON.parse('
            + json.dumps(json.dumps({"posts_offline-fixture.md": "hash"}))
            + ")</script>"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / ".cache" / "html"
            data_root = root / "data"
            cache_path = cache_root / "os" / f"{sync_sources.stable_id(article_url)}.html"
            cache_path.parent.mkdir(parents=True)
            cache_path.write_text(ARTICLE_HTML, encoding="utf-8")
            (data_root / "cards").mkdir(parents=True)
            (data_root / "articles.json").write_text(
                json.dumps({"articles": [{"sourceId": "os", "url": article_url, "etag": '"old"'}]}),
                encoding="utf-8",
            )
            previous_card = {
                "id": "user-card",
                "sourceId": "os",
                "articleUrl": article_url + "#first-topic",
                "question": "Preserve me",
                "answer": "User answer",
                "status": "approved",
            }
            (data_root / "cards" / "cards.json").write_text(
                json.dumps({"cards": [previous_card]}), encoding="utf-8"
            )

            def fake_fetch(url, headers=None):
                if url == source["base"]:
                    return list_body, {}, 200
                return article_body, {"ETag": '"new"'}, 200

            with (
                mock.patch.object(sync_sources, "CACHE", cache_root),
                mock.patch.object(sync_sources, "DATA", data_root),
                mock.patch.object(sync_sources, "ROOT", root),
                mock.patch.object(sync_sources, "SOURCES", [source]),
                mock.patch.object(sync_sources, "fetch", side_effect=fake_fetch),
                mock.patch.object(sync_sources.time, "sleep"),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                if expect_failure:
                    with self.assertRaisesRegex(RuntimeError, "同步不完整"):
                        sync_sources.sync(delay=0)
                else:
                    sync_sources.sync(delay=0)

            return {
                "cached": cache_path.read_text(encoding="utf-8"),
                "sources": json.loads((data_root / "sources.json").read_text(encoding="utf-8")),
                "articles": json.loads((data_root / "articles.json").read_text(encoding="utf-8")),
                "cards": json.loads((data_root / "cards" / "cards.json").read_text(encoding="utf-8")),
                "url": article_url,
            }

    def test_invalid_http_200_does_not_replace_cache_and_marks_sync_incomplete(self):
        result = self._run_failed_sync("<html><body>temporary error page</body></html>")
        self.assertEqual(result["cached"], ARTICLE_HTML)
        self.assertEqual(result["sources"]["syncStatus"], "incomplete")
        self.assertEqual(result["sources"]["failedArticles"][0]["url"], result["url"])
        self.assertEqual(result["articles"]["articles"][0]["url"], result["url"])
        self.assertEqual(result["cards"]["cards"][0]["status"], "approved")
        self.assertNotIn("sourceSectionRemoved", result["cards"]["cards"][0])

    def test_title_only_article_gets_explicit_manual_review_card(self):
        title_only = '<main class="vp-doc"><h1>Title only</h1></main>'
        result = self._run_failed_sync(title_only, expect_failure=False)
        self.assertEqual(result["cached"], title_only)
        self.assertEqual(result["sources"]["syncStatus"], "ok")
        cards = result["cards"]["cards"]
        manual_cards = [card for card in cards if card.get("reviewReason")=="source-extraction-incomplete"]
        self.assertTrue(manual_cards)
        self.assertTrue(all(card["status"]=="needs-review" for card in manual_cards))
        self.assertTrue(any(card.get("sourceSectionRemoved") for card in cards if card["id"]=="user-card"))

    def test_retry_failed_does_not_treat_unretried_articles_as_removed(self):
        source = {
            "id": "os", "name": "Operating systems", "prefix": "os-blog",
            "base": "https://example.test/os-blog/", "extension": "",
        }
        retried_url = source["base"] + "posts/offline-fixture"
        untouched_url = source["base"] + "posts/untouched"
        list_body = (
            "<script>self.__VP_HASH_MAP__ = JSON.parse("
            + json.dumps(json.dumps({
                "posts_offline-fixture.md": "a", "posts_untouched.md": "b"
            }))
            + ")</script>"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_root = root / ".cache" / "html"
            data_root = root / "data"
            (data_root / "cards").mkdir(parents=True)
            records = [
                {"sourceId": "os", "url": retried_url},
                {"sourceId": "os", "url": untouched_url},
            ]
            (data_root / "articles.json").write_text(
                json.dumps({"articles": records}), encoding="utf-8"
            )
            untouched_card = {
                "id": "untouched-card", "sourceId": "os",
                "articleUrl": untouched_url + "#topic", "status": "approved",
                "question": "Keep this card", "answer": "Keep this answer",
            }
            (data_root / "cards" / "cards.json").write_text(
                json.dumps({"cards": [untouched_card]}), encoding="utf-8"
            )
            (data_root / "sources.json").write_text(json.dumps({
                "syncScope": "all",
                "failedArticles": [{"sourceId": "os", "url": retried_url}],
            }), encoding="utf-8")

            def fake_fetch(url, headers=None):
                if url == source["base"]:
                    return list_body, {}, 200
                return ARTICLE_HTML, {"ETag": "new"}, 200

            with (
                mock.patch.object(sync_sources, "CACHE", cache_root),
                mock.patch.object(sync_sources, "DATA", data_root),
                mock.patch.object(sync_sources, "ROOT", root),
                mock.patch.object(sync_sources, "SOURCES", [source]),
                mock.patch.object(sync_sources, "fetch", side_effect=fake_fetch),
                mock.patch.object(sync_sources.time, "sleep"),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                sync_sources.sync(delay=0, retry_failed=True)

            articles = json.loads((data_root / "articles.json").read_text(encoding="utf-8"))["articles"]
            cards = json.loads((data_root / "cards" / "cards.json").read_text(encoding="utf-8"))["cards"]
            untouched_article = next(item for item in articles if item["url"] == untouched_url)
            self.assertNotIn("sourceArticleMissing", untouched_article)
            self.assertFalse(untouched_article.get("sourceArticleMissing", False))
            untouched = next(item for item in cards if item["id"] == "untouched-card")
            self.assertNotIn("sourceArticleMissing", untouched)
            self.assertEqual(untouched["status"], "approved")

    def test_parse_article_reads_local_html(self):
        article = sync_sources.parse_article(ARTICLE_HTML, ARTICLE_URL)
        self.assertEqual(article["url"], ARTICLE_URL)
        block_text = " ".join(block["text"] for block in article["blocks"])
        self.assertIn("Offline parsing fixture", block_text)
        self.assertIn("First answer", block_text)
        self.assertIn("Second answer", block_text)

    def test_sections_and_cards_extract_topics_with_stable_schema(self):
        article = sync_sources.parse_article(ARTICLE_HTML, ARTICLE_URL)
        extracted_sections = _as_items(sync_sources.sections(article))
        self.assertEqual(len(extracted_sections), 2)
        self.assertEqual(
            [_get_field(item, "heading", "title") for item in extracted_sections],
            ["First topic", "Second topic"],
        )

        source = _source_records(sync_sources.SOURCES)[0]
        cards = _as_items(sync_sources.make_cards(source, article, "offline-fixture"))
        repeated_cards = _as_items(
            sync_sources.make_cards(
                source,
                sync_sources.parse_article(ARTICLE_HTML, ARTICLE_URL),
                "offline-fixture",
            )
        )
        self.assertEqual(len(cards), 2, "each substantive heading should produce a card")
        self.assertEqual(len(cards), len(repeated_cards))

        for card in cards:
            self.assertTrue(_get_field(card, "id"), f"card is missing id: {card!r}")
            self.assertTrue(
                _get_field(card, "question", "front", "prompt"),
                f"card is missing question/front: {card!r}",
            )
            self.assertTrue(
                _get_field(card, "answer", "back", "response"),
                f"card is missing answer/back: {card!r}",
            )

        card_ids = [str(_get_field(card, "id")) for card in cards]
        repeated_ids = [str(_get_field(card, "id")) for card in repeated_cards]
        self.assertEqual(card_ids, repeated_ids, "rebuilding the same cards must preserve IDs")

    def test_long_sections_are_split_without_truncation(self):
        long_text = "第一句说明定义和适用范围。" * 180
        article = sync_sources.parse_article(
            f'''<main class="vp-doc"><h1>Long article</h1><h2 id="long">Long topic</h2><p>{long_text}</p></main>''',
            ARTICLE_URL,
        )
        source = _source_records(sync_sources.SOURCES)[0]
        cards = _as_items(sync_sources.make_cards(source, article, "long-fixture"))
        self.assertGreater(len(cards), 1)
        rebuilt = "".join(str(_get_field(card, "answer", "back")) for card in cards)
        self.assertEqual(rebuilt.replace(" ", ""), long_text)
        self.assertEqual([card["part"] for card in cards], list(range(1, len(cards) + 1)))
        self.assertTrue(all(card["partCount"] == len(cards) for card in cards))

    def test_changed_source_preserves_user_answer_and_creates_review_suggestion(self):
        article = sync_sources.parse_article(ARTICLE_HTML, ARTICLE_URL)
        source = _source_records(sync_sources.SOURCES)[0]
        generated = _as_items(sync_sources.make_cards(source, article, "offline-fixture"))[0]
        old = {
            **generated,
            "question": "我的问题",
            "answer": "我的答案",
            "evidence": "我的证据",
            "tags": ["自定义"],
            "note": "保留这条笔记",
            "status": "approved",
        }
        merged = sync_sources.merge_card(generated, old, source_changed=True)
        self.assertEqual(merged["question"], "我的问题")
        self.assertEqual(merged["answer"], "我的答案")
        self.assertEqual(merged["evidence"], "我的证据")
        self.assertEqual(merged["tags"], ["自定义"])
        self.assertEqual(merged["note"], "保留这条笔记")
        self.assertEqual(merged["status"], "needs-review")
        self.assertEqual(merged["previousAnswer"], "我的答案")
        self.assertEqual(merged["suggestedAnswer"], generated["answer"])

    def test_legacy_generated_card_is_upgraded_to_full_answer(self):
        article = sync_sources.parse_article(ARTICLE_HTML, ARTICLE_URL)
        source = _source_records(sync_sources.SOURCES)[0]
        generated = _as_items(sync_sources.make_cards(source, article, "offline-fixture"))[0]
        legacy = {
            "id": generated["id"],
            "origin": "source-summary",
            "status": "inbox",
            "section": generated["section"],
            "question": f'回忆「{generated["section"]}」的核心定义、机制与易错点。',
            "answer": "旧版截断…",
            "evidence": "旧版截断…",
        }
        upgraded = sync_sources.merge_card(generated, legacy, source_changed=False)
        self.assertEqual(upgraded["answer"], generated["answer"])
        self.assertEqual(upgraded["evidence"], generated["evidence"])
        self.assertEqual(upgraded["generatorVersion"], 4)

    def test_stable_id_is_repeatable_and_nonempty(self):
        first = sync_sources.stable_id("os", "offline-fixture", "First topic", "first-topic")
        second = sync_sources.stable_id("os", "offline-fixture", "First topic", "first-topic")
        different = sync_sources.stable_id("os", "offline-fixture", "Second topic", "second-topic")
        self.assertTrue(first)
        self.assertEqual(first, second)
        self.assertNotEqual(first, different)

    def test_source_configuration_has_unique_ids_and_bases(self):
        configured_sources = _source_records(sync_sources.SOURCES)
        self.assertTrue(configured_sources, "SOURCES must contain at least one source")

        seen_ids = set()
        seen_bases = set()
        for source in configured_sources:
            source_id = _get_field(source, "id", "key", "name", "slug")
            source_url = _get_field(source, "url", "base", "source_url")
            self.assertTrue(source_id, f"source is missing an id/name: {source!r}")
            self.assertTrue(source_url, f"source is missing a URL/base: {source!r}")
            self.assertNotIn(str(source_id), seen_ids, "source identifiers must be unique")
            self.assertNotIn(str(source_url), seen_bases, "source URLs/bases must be unique")
            seen_ids.add(str(source_id))
            seen_bases.add(str(source_url))


    def test_short_and_empty_sections_are_explicitly_covered(self):
        article = sync_sources.parse_article(
            '<main class="vp-doc"><h1>Shorts</h1><h2 id="short">Short point</h2><p>FIFO</p><h2 id="empty">Empty topic</h2></main>',
            ARTICLE_URL,
        )
        source = _source_records(sync_sources.SOURCES)[0]
        cards = _as_items(sync_sources.make_cards(source, article, "short-fixture"))
        self.assertEqual(len(cards), 2)
        by_section = {card["sectionAnchor"]: card for card in cards}
        self.assertEqual(by_section["short"]["answer"], "FIFO")
        self.assertEqual(by_section["short"]["status"], "needs-review")
        self.assertEqual(by_section["empty"]["status"], "needs-review")
        self.assertIn("人工核对", by_section["empty"]["answer"])

    def test_vitepress_header_anchor_is_not_in_article_or_section_text(self):
        article = sync_sources.parse_article(
            '''<main class="vp-doc"><h1>Fixture<a class="header-anchor" href="#fixture" aria-hidden="true">#</a></h1>
            <h2 id="topic">Topic<a class="header-anchor" href="#topic" aria-hidden="true">Permalink to "Topic"</a></h2>
            <p>Body text.</p></main>''',
            ARTICLE_URL,
        )
        self.assertEqual(article["title"], "Fixture")
        section = sync_sources.sections(article)[0]
        self.assertEqual(section["heading"], "Topic")
        self.assertEqual(section["headingPath"], "Topic")
        self.assertNotIn("Permalink", " ".join(section["content"]))

    def test_practice_link_only_section_is_blocked_as_unextracted_content(self):
        article = sync_sources.parse_article(
            '''<main class="vp-doc"><h1>Fixture</h1><h2 id="practice">真题练习</h2>
            <a class="exam-tile" href="/practice/q/os-2020-28" title="2020 年第 28 题"><span>2020</span><span>Q28</span></a>
            </main>''',
            ARTICLE_URL,
        )
        card = sync_sources.make_cards(_source_records(sync_sources.SOURCES)[0], article, "practice")[0]
        self.assertEqual(card["reviewReason"], "source-extraction-incomplete")
        self.assertIn("linked-question-index-not-question-content", card["auditFlags"])

    def test_article_without_headings_gets_manual_review_card(self):
        article = sync_sources.parse_article(
            '<main class="vp-doc"><p>Unstructured content</p></main>', ARTICLE_URL
        )
        source = _source_records(sync_sources.SOURCES)[0]
        cards = _as_items(sync_sources.make_cards(source, article, "unstructured"))
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["status"], "needs-review")
        self.assertIn("Unstructured content", cards[0]["answer"])

    def test_lists_tables_math_and_nested_images_keep_visible_structure(self):
        article = sync_sources.parse_article(
            '''<main class="vp-doc"><h1>Structure</h1><h2 id="detail">Detail</h2>
            <ul><li>栈顶<sup>2</sup><ul><li>嵌套项</li></ul></li><li><img src="x.png"></li></ul>
            <table><tr><th>算法</th><th>复杂度</th></tr><tr><td>查找</td><td>O(n)</td></tr></table>
            <svg aria-label="状态转移图"></svg></main>''',
            ARTICLE_URL,
        )
        source = _source_records(sync_sources.SOURCES)[0]
        cards = _as_items(sync_sources.make_cards(source, article, "structure"))
        answer = cards[0]["answer"]
        self.assertIn("栈顶", answer)
        self.assertIn("嵌套项", answer)
        self.assertIn("图片需人工核对", answer)
        self.assertIn("表头：算法 | 复杂度", answer)
        self.assertIn("行2：查找 | O(n)", answer)
        self.assertIn("SVG公式/图示：状态转移图", answer)


    def test_exam_tiles_mathml_and_knowledge_unit_provenance_are_preserved(self):
        article = sync_sources.parse_article(
            """<main class="vp-doc"><h1>Exam component</h1><h2 id="practice">真题练习</h2>
            <div class="exam-topic"><h3>选择题</h3><div><a class="exam-tile" href="/practice/q/os-2020-28" title="2020 年第 28 题"><span>2020</span><span>Q28</span><span>5 分</span></a></div></div>
            <p>调度等待时间满足 <math><mfrac><mn>1</mn><mn>2</mn></mfrac><annotation encoding="application/x-tex">\\frac{1}{2}</annotation></math>。</p>
            </main>""",
            ARTICLE_URL,
        )
        sections = sync_sources.sections(article)
        section = next(item for item in sections if item["heading"] == "选择题")
        rendered = " ".join(value for item in sections for value in item["content"])
        self.assertIn("2020", rendered)
        self.assertIn("Q28", rendered)
        self.assertIn("/practice/q/os-2020-28", rendered)
        self.assertIn("\\frac{1}{2}", rendered)
        source_units = [unit for block in section["sourceUnits"] for unit in block["units"]]
        self.assertTrue(source_units)
        source = _source_records(sync_sources.SOURCES)[0]
        cards = sync_sources.make_cards(source, article, "exam-component", "fixture-hash")
        linked = [card for card in cards if "linked-question-index-not-question-content" in card["auditFlags"]]
        self.assertTrue(linked)
        self.assertEqual(linked[0]["status"], "needs-review")
        self.assertTrue(linked[0]["knowledgeUnitIds"])
        self.assertEqual(linked[0]["provenance"]["verificationStatus"], "not-reviewed")
        self.assertNotEqual(linked[0]["answer"], linked[0]["evidence"])

    def test_unmapped_or_unreviewed_source_content_is_not_approved(self):
        article = sync_sources.parse_article(
            "<main class='vp-doc'><h1>Candidate</h1><h2 id='t'>Topic</h2><p>Definition with a condition.</p></main>",
            ARTICLE_URL,
        )
        card = sync_sources.make_cards(_source_records(sync_sources.SOURCES)[0], article, "candidate")[0]
        self.assertEqual(card["status"], "needs-review")
        self.assertEqual(card["knowledgeUnitReviewStatus"], "candidate-unreviewed")
        self.assertIn("408-syllabus-mapping-pending", card["auditFlags"])
        self.assertEqual(card["examPoints"], [])

    def test_sections_retain_parent_heading_path_and_unique_section_index(self):
        article = sync_sources.parse_article(
            '<main class="vp-doc"><h1>Hierarchy</h1><h2 id="parent">Parent</h2>'
            '<p>Parent definition.</p><h3 id="child">Child</h3><p>Child definition.</p></main>',
            ARTICLE_URL,
        )
        parsed = sync_sources.sections(article)
        self.assertEqual([item["sectionIndex"] for item in parsed], [1, 2])
        self.assertEqual(parsed[1]["headingPath"], "Parent / Child")


if __name__ == "__main__":
    unittest.main()
