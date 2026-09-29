"""Run a reviewed benchmark through an injected retriever, or inspect a draft."""
import argparse
import importlib
import json
from pathlib import Path

from evaluation import evaluate_retrieval, write_evaluation


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("cases")
    parser.add_argument("--split", choices=("dev", "heldout"))
    parser.add_argument("--retriever", help="module:function returning a configured retriever")
    parser.add_argument("--output")
    args = parser.parse_args()
    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    cases = [case for case in cases if args.split is None or case["split"] == args.split]
    if not args.retriever:
        print(json.dumps({"cases": len(cases), "families": sorted({case["family"] for case in cases}), "ready_for_measurement": all(case["reference_status"] == "reviewed" and case["relevant_article_ids"] for case in cases)}, ensure_ascii=False))
        return
    module, name = args.retriever.split(":", 1)
    retriever = getattr(importlib.import_module(module), name)()
    report = evaluate_retrieval(cases, retriever, {"benchmark": str(Path(args.cases)), "split": args.split or "all"})
    if not args.output:
        raise SystemExit("--output is required with --retriever")
    write_evaluation(report, args.output)


if __name__ == "__main__":
    main()
