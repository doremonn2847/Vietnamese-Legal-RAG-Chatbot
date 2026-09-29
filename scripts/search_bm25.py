"""Offline article-level BM25 query over staged articles."""
import argparse
import json
import sys
from pathlib import Path

from bm25 import BM25Index


def load_articles(path):
    documents = []
    for line in Path(path).read_text(encoding="utf-8").split("\n"):
        if not line:
            continue
        article = json.loads(line)
        documents.append({"article_id": article["article_id"], "document_id": article["document_id"], "text": article["canonical_text"]})
    return documents


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("articles")
    parser.add_argument("query")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    results = BM25Index(load_articles(args.articles)).search(args.query, args.limit)
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
