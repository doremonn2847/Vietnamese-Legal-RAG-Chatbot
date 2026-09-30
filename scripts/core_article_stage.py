"""Stage article parses for the explicitly audited core corpus."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

import pyarrow.dataset as ds

from audit_corpus import REVISION, ROOT as RAW_ROOT, sha256
from corpus_stage import parse_articles
from curate_core_corpus import CORE_IDS, LABOR_CODE_PAIR, _read_audit, _read_parquet, select_core_records


def stage(output=None):
    audit_root = RAW_ROOT.parents[1] / "audit" / REVISION
    wanted = set(CORE_IDS) | set(LABOR_CODE_PAIR)
    metadata = _read_parquet(RAW_ROOT / "metadata.parquet", wanted)
    contents = {key: row["content_html"] for key, row in _read_parquet(RAW_ROOT / "content.parquet", wanted).items()}
    audit = _read_audit(audit_root / "document_decisions.csv", wanted)
    with (audit_root / "duplicate_groups.csv").open(encoding="utf-8-sig", newline="") as stream:
        duplicate_groups = list(csv.DictReader(stream))
    documents, _ = select_core_records(metadata, contents, audit, duplicate_groups)

    active_pointer = RAW_ROOT.parents[1] / "staging" / REVISION / "active_staging.json"
    active_articles, active_manifest_sha = {}, None
    if active_pointer.is_file():
        pointer = json.loads(active_pointer.read_text(encoding="utf-8"))
        active_dir = active_pointer.parent / pointer["build_dir"]
        stage_manifest = json.loads((active_dir / pointer["manifest"]).read_text(encoding="utf-8"))
        article_info = stage_manifest.get("outputs", {}).get("articles.jsonl", {})
        active_path = active_dir / "articles.jsonl"
        if stage_manifest.get("dataset_revision") == REVISION and active_path.is_file() and sha256(active_path) == article_info.get("sha256"):
            active_manifest_sha = sha256(active_dir / pointer["manifest"])
            with active_path.open(encoding="utf-8") as stream:
                for line in stream:
                    if not line.strip():
                        continue
                    article = json.loads(line)
                    if article.get("document_id") in CORE_IDS:
                        active_articles.setdefault(article["document_id"], []).append(article)

    records, reused, newly_parsed = [], [], []
    for document in documents:
        doc_id, raw = document["id"], document["content_html"]
        articles = active_articles.get(doc_id, [])
        if articles and all(article.get("content_sha256") == hashlib.sha256(raw.encode("utf-8")).hexdigest() for article in articles):
            reused.append(doc_id)
        else:
            articles = parse_articles(doc_id, raw)
            newly_parsed.append(doc_id)
        if not articles:
            raise ValueError(f"staging produced no articles for {doc_id}")
        content_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        for article in articles:
            if article.get("content_sha256") != content_hash or raw[article["source_start"]:article["source_end"]] != article["source_html"]:
                raise ValueError(f"staged article span/hash mismatch for {doc_id}:{article.get('label')}")
            records.append({"document_id": doc_id, "source_content_sha256": content_hash, "article": article})

    output = Path(output or RAW_ROOT.parents[1] / "staging" / REVISION / "core-employment-portfolio-v1")
    output.mkdir(parents=True, exist_ok=True)
    articles_path = output / "core_articles.jsonl"
    temporary = articles_path.with_suffix(".jsonl.part")
    temporary.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in records), encoding="utf-8")
    temporary.replace(articles_path)
    source_manifest = RAW_ROOT / "manifest.json"
    manifest = {
        "dataset_revision": REVISION,
        "source_manifest_sha256": sha256(source_manifest),
        "content_sha256": {doc["id"]: hashlib.sha256(doc["content_html"].encode("utf-8")).hexdigest() for doc in documents},
        "active_staging_manifest_sha256": active_manifest_sha,
        "reused_active_staging_document_ids": reused,
        "newly_parsed_document_ids": newly_parsed,
        "article_count": len(records),
        "parser_sha256": sha256(Path(__file__).with_name("corpus_stage.py")),
        "outputs": {articles_path.name: {"bytes": articles_path.stat().st_size, "sha256": sha256(articles_path)}},
    }
    manifest_path = output / "core_article_stage_manifest.json"
    temp_manifest = manifest_path.with_suffix(".json.part")
    temp_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_manifest.replace(manifest_path)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(json.dumps(stage(args.output), ensure_ascii=True, indent=2))
