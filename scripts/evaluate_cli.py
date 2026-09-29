"""Run a reviewed benchmark through an injected retriever, or inspect a draft."""
import argparse
import hashlib
import importlib
import json
from datetime import date
from pathlib import Path

from evaluation import evaluate_retrieval, write_evaluation


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("cases")
    parser.add_argument("--split", choices=("dev", "heldout"))
    parser.add_argument("--retriever", help="module:function returning a configured retriever")
    parser.add_argument("--output")
    args = parser.parse_args()
    source = Path(args.cases)
    source_bytes = source.read_bytes()
    cases = json.loads(source_bytes.decode("utf-8"))
    if not isinstance(cases, list):
        raise SystemExit("benchmark cases must be a JSON array")
    validate_split_separation(cases)
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
    report = evaluate_retrieval(cases, retriever, {"benchmark": str(source), "benchmark_sha256": hashlib.sha256(source_bytes).hexdigest(), "split": args.split or "all"})
    write_evaluation(report, args.output)


def validate_measurement_cases(cases):
    allowed_states = {"answer", "partial", "clarify", "unavailable", "abstain_conflict", "abstain_insufficient_evidence"}
    reference_fields = {"document_version_id", "article_id", "quote", "span_start", "span_end", "applicable_on_requested_date"}
    required = {"case_id", "scenario_family_id", "family", "query", "legal_date", "reference_status", "expected_answer_state", "relevant_article_ids", "references"}
    for case in cases:
        if required - set(case) or not all(isinstance(case[field], str) and case[field].strip() for field in ("case_id", "scenario_family_id", "family", "query")) or case["reference_status"] != "reviewed" or case["expected_answer_state"] not in allowed_states or not isinstance(case["relevant_article_ids"], list) or len(set(case["relevant_article_ids"])) != len(case["relevant_article_ids"]) or any(not isinstance(value, str) or not value.strip() for value in case["relevant_article_ids"]) or not isinstance(case["references"], list):
            raise ValueError("all measured cases require a reviewed benchmark schema")
        try:
            date.fromisoformat(case["legal_date"])
        except (TypeError, ValueError) as error:
            raise ValueError("benchmark legal_date must be ISO YYYY-MM-DD") from error
        positive = case["expected_answer_state"] in {"answer", "partial"}
        if positive and (not case["relevant_article_ids"] or not case["references"]):
            raise ValueError("reviewed answerable cases require reference article IDs")
        reference_article_ids = set()
        for reference in case["references"]:
            if not isinstance(reference, dict) or reference_fields - set(reference) or not isinstance(reference.get("document_version_id"), str) or not isinstance(reference.get("article_id"), str) or reference.get("article_id") not in case["relevant_article_ids"] or not isinstance(reference.get("quote"), str) or not reference["quote"].strip() or type(reference.get("span_start")) is not int or type(reference.get("span_end")) is not int or reference["span_start"] < 0 or reference["span_end"] <= reference["span_start"] or reference.get("applicable_on_requested_date") is not True:
                raise ValueError("reviewed reference is incomplete")
            reference_article_ids.add(reference["article_id"])
        if positive and reference_article_ids != set(case["relevant_article_ids"]):
            raise ValueError("every relevant article requires a reference")


def validate_split_separation(cases):
    splits = {}
    case_ids = set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("case_id"), str) or not case["case_id"].strip() or case["case_id"] in case_ids or not isinstance(case.get("scenario_family_id"), str) or case.get("split") not in {"dev", "heldout"}:
            raise ValueError("benchmark split schema is invalid")
        case_ids.add(case["case_id"])
        splits.setdefault(case["scenario_family_id"], set()).add(case["split"])
    if any(len(values) > 1 for values in splits.values()):
        raise ValueError("scenario families cannot cross dev and heldout")


if __name__ == "__main__":
    main()
