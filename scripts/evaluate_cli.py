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
    if not isinstance(cases, list):
        raise SystemExit("benchmark cases must be a JSON array")
    cases = [case for case in cases if args.split is None or case["split"] == args.split]
    if not cases:
        raise SystemExit("no benchmark cases selected")
    if not args.retriever:
        try:
            validate_measurement_cases(cases)
            ready = True
        except ValueError:
            ready = False
        print(json.dumps({"cases": len(cases), "families": sorted({case["family"] for case in cases}), "ready_for_measurement": ready}, ensure_ascii=False))
        return
    if not args.output:
        raise SystemExit("--output is required with --retriever")
    validate_measurement_cases(cases)
    if ":" not in args.retriever:
        raise SystemExit("--retriever must be module:function")
    module, name = args.retriever.split(":", 1)
    retriever = getattr(importlib.import_module(module), name)()
    report = evaluate_retrieval(cases, retriever, {"benchmark": str(Path(args.cases)), "split": args.split or "all"})
    write_evaluation(report, args.output)


def validate_measurement_cases(cases):
    required = {"case_id", "scenario_family_id", "family", "query", "legal_date", "reference_status", "expected_answer_state", "relevant_article_ids", "reference_required_fields"}
    for case in cases:
        if required - set(case) or case["reference_status"] != "reviewed":
            raise ValueError("all measured cases require a reviewed benchmark schema")
        positive = case["expected_answer_state"] in {"answer", "partial"}
        if positive and not case["relevant_article_ids"]:
            raise ValueError("reviewed answerable cases require reference article IDs")


if __name__ == "__main__":
    main()
