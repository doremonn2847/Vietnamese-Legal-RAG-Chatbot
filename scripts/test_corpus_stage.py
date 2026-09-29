import unittest

from corpus_stage import (
    EMPLOYMENT_TERMS,
    collect_dependency_ids,
    is_employment_candidate,
    parse_articles,
    layout_anomalies,
    _canonical_with_map,
    _common_structure_path,
    _visible,
)
from stage_corpus import activate_build
from bm25 import BM25Index
from search_bm25 import load_articles


class CorpusStageTest(unittest.TestCase):
    def test_employment_gate_is_narrow_and_provisional(self):
        row = {"title": "Nghị định quy định hợp đồng lao động và thử việc", "nganh": "Lao động", "linh_vuc": "Lao động"}
        self.assertTrue(is_employment_candidate(row))
        self.assertFalse(is_employment_candidate({"title": "Quy định phí sử dụng đất", "nganh": "Tài chính", "linh_vuc": "Đất đai"}))
        self.assertFalse(is_employment_candidate({"title": "Hợp đồng mua bán nhà ở", "nganh": "Xây dựng", "linh_vuc": "Nhà ở"}))
        self.assertIn("hợp đồng lao động", EMPLOYMENT_TERMS)

    def test_dependency_ids_are_one_hop_and_keep_dangling_targets(self):
        ids = collect_dependency_ids({"a", "b"}, [("a", "b"), ("a", "missing"), ("x", "y")])
        self.assertEqual(ids, {"a", "b", "missing"})
        self.assertEqual(collect_dependency_ids({"a"}, [("b", "c"), ("a", "b")]), {"a", "b"})

    def test_article_parser_preserves_raw_spans_and_children(self):
        html = "<head><title>Document Content</title><script>Điều 99. Không phải điều</script></head><p>CHƯƠNG I</p><p>Mục I</p><p>Điều 1. Hợp đồng</p><p>1. Nội dung thử việc.</p><p>2. Nội dung tiền lương.</p><p>Áp dụng theo Điều 5 của văn bản này.</p><p>CHƯƠNG II</p><p>Điều 2. Nghỉ phép</p><p>Được nghỉ hằng năm.</p>"
        articles = parse_articles("doc-1", html, max_chars=40)
        self.assertEqual([a["label"] for a in articles], ["Điều 1", "Điều 2"])
        self.assertEqual(articles[0]["section"], "Mục I")
        self.assertIsNone(articles[1]["section"])
        self.assertIn("Điều 5", articles[0]["cross_references"])
        self.assertTrue(articles[0]["hierarchy"])
        self.assertLess(articles[0]["source_start"], articles[0]["source_end"])
        self.assertEqual(html[articles[0]["source_start"]:articles[0]["source_end"]], articles[0]["source_html"])
        self.assertTrue(articles[0]["children"])
        self.assertEqual(articles[0]["children"][0]["parent_article_id"], articles[0]["article_id"])
        self.assertEqual("".join(child["source_html"] for child in articles[0]["children"]), articles[0]["source_html"])
        long_html = "<p>Điều 9. " + ("x" * 101) + "</p>"
        long_article = parse_articles("doc-2", long_html, max_chars=40)[0]
        self.assertEqual("".join(child["source_html"] for child in long_article["children"]), long_article["source_html"])
        self.assertTrue(all(len(child["canonical_text"]) <= 40 for child in long_article["children"]))
        huge = "<p>Điều 10. A</p><p>1. " + ("word " * 2000) + "</p>"
        huge_article = parse_articles("doc-3", huge, max_chars=6000)[0]
        self.assertTrue(all(len(child["canonical_text"]) <= 6000 for child in huge_article["children"]))
        self.assertEqual("".join(child["source_html"] for child in huge_article["children"]), huge_article["source_html"])
        self.assertTrue(any("khoản 1" in node["structure_path"] for node in huge_article["hierarchy"]))
        grouped = parse_articles("doc-grouped", "<p>Điều 11. A</p>" + "".join(f"<p>{i}. {'x' * 30}</p>" for i in range(1, 8)), max_chars=80)[0]
        self.assertGreater(len(grouped["children"]), 1)
        self.assertTrue(all(len(child["canonical_text"]) <= 80 for child in grouped["children"]))
        tail = parse_articles("doc-tail", "<p>Điều 12. A</p><div>" + ("tail word " * 2000) + "</div>", max_chars=6000)[0]
        self.assertTrue(all(len(child["canonical_text"]) <= 6000 for child in tail["children"]))
        self.assertEqual("".join(child["source_html"] for child in tail["children"]), tail["source_html"])
        owned = parse_articles("doc-owner", "<p>Điều 1. A</p><p>1. " + ("x " * 30) + "</p><p>2. " + ("y " * 30) + "</p>", max_chars=40)[0]
        self.assertTrue(all(child["structure_path"][-1] != "khoản 2" for child in owned["children"][:1]))
        self.assertEqual(_canonical_with_map("<p>A</p><p>B</p>")[0], _visible("<p>A</p><p>B</p>"))

    def test_article_references_do_not_become_headings_and_content_versions_change_ids(self):
        html = "<p>Điều 1. Phạm vi</p><p>Áp dụng theo Điều 5 của văn bản này.</p><p>Điều 2. Đối tượng</p>"
        articles = parse_articles("doc-ref", html)
        self.assertEqual([a["label"] for a in articles], ["Điều 1", "Điều 2"])
        first = parse_articles("doc-version", "<p>Điều 1. A</p>")[0]
        second = parse_articles("doc-version", "<p>Điều 1. B</p>")[0]
        self.assertNotEqual(first["article_id"], second["article_id"])
        self.assertNotEqual(first["document_version_id"], second["document_version_id"])
        nested = parse_articles("doc-nested", "<div><p>Điều 1. A</p><p>1. X</p><p>Điều 2. B</p></div>")
        self.assertEqual([a["label"] for a in nested], ["Điều 1", "Điều 2"])
        hierarchy = parse_articles("doc-hierarchy", "<p>Điều 1. A</p><p>1. X</p><p>a) Y</p>")[0]["hierarchy"]
        self.assertIn(["Điều 1", "khoản 1", "điểm a)"], [node["structure_path"] for node in hierarchy])
        exact = parse_articles("doc-exact", "<p>Điều 1. A</p><p>Điều 5 của văn bản này được áp dụng.</p><p>Điều 2. B</p>")
        self.assertEqual([a["label"] for a in exact], ["Điều 1", "Điều 2"])
        mixed = parse_articles("doc-mixed", "<p>Điều 1. A</p><div>Điều 2. B</div><p>Điều 3. C</p>")
        self.assertEqual([a["label"] for a in mixed], ["Điều 1", "Điều 2", "Điều 3"])
        self.assertIn("mixed_block_content", [item["reason"] for item in layout_anomalies("<div>Điều 1. A<p>1. Nội dung</p></div><p>Điều 2. B</p>")])
        inline = "<p>la<span>o</span> động &amp; nghỉ</p>"
        self.assertEqual(_visible(inline), "lao động & nghỉ")
        grouped = parse_articles("doc-grouped-clauses", "<p>Điều 1. A</p><p>1. " + ("x " * 8) + "</p><p>2. " + ("y " * 8) + "</p><p>3. " + ("z " * 40) + "</p>", max_chars=80)[0]
        self.assertNotEqual(grouped["children"][0]["structure_path"][-1], "khoản 2")
        self.assertTrue(any(len(child["covered_structure_paths"]) > 1 for child in grouped["children"]))
        self.assertEqual(grouped["children"][0]["structure_path"], ["Điều 1"])
        self.assertTrue(all(len(child["canonical_text"]) <= 80 for child in grouped["children"]))
        self.assertEqual(_common_structure_path([["Điều 1", "khoản 1"], ["Điều 1", "khoản 2"]]), ["Điều 1"])

    def test_bm25_ranks_unique_articles(self):
        index = BM25Index([{"article_id": "a", "text": "hợp đồng lao động thử việc"}, {"article_id": "b", "text": "nghỉ hằng năm"}])
        self.assertEqual(index.search("hợp đồng thử việc", 2)[0]["article_id"], "a")

    def test_jsonl_loader_keeps_unicode_line_separators_inside_records(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as stream:
            stream.write('{"article_id":"a","document_id":"d","canonical_text":"x\\u2028y"}\n')
            path = stream.name
        self.assertEqual(load_articles(path)[0]["text"], "x\u2028y")

    def test_failed_activation_keeps_previous_pointer(self):
        import json
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            out, build = Path(directory), Path(directory) / "build-new"
            build.mkdir()
            (out / "active_staging.json").write_text('{"build_dir":"build-old"}', encoding="utf-8")
            manifest = {"dataset_revision": "r", "outputs": {"articles.jsonl": {"bytes": 1, "sha256": "bad"}}}
            with self.assertRaises(ValueError):
                activate_build(out, build, manifest)
            self.assertEqual(json.loads((out / "active_staging.json").read_text())["build_dir"], "build-old")


if __name__ == "__main__":
    unittest.main()
