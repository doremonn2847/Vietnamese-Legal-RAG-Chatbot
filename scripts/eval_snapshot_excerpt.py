"""Offline quote-fidelity and frozen target-retrieval check with an injected span selector."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from core_app import create_core_app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

REVISION = "8977887f17be2defae4c5171d55562e1cde7d695"
CASES = (
    {"split": "development", "id": "contract_contents", "question": "Hợp đồng lao động cần có nội dung chính nào?", "article_id": "3f2b3e90-453c-527c-ade0-11e72029d715", "document_version_id": "8a5e1a1b-899c-5bab-8287-6b9754fcea5a"},
    {"split": "development", "id": "paid_working_time", "question": "Thời giờ nào được tính vào thời giờ làm việc hưởng lương?", "article_id": "368e060a-40a3-51cd-8134-27ce5b88e9b3", "document_version_id": "a550e557-9ade-502f-a86d-47bfa65e0b97"},
    {"split": "held_out", "id": "annual_leave_calculation", "question": "Cách tính ngày nghỉ hằng năm trong trường hợp đặc biệt thế nào?", "article_id": "a735c6cd-cd93-5f84-b950-2e1341d15c13", "document_version_id": "a550e557-9ade-502f-a86d-47bfa65e0b97"},
)


def main():
    class SpanSelector:
        calls = 0
        expected_id = None
        def answer(self, question, legal_date, evidence):
            self.calls += 1
            selected = evidence.get(self.expected_id)
            if selected is None:
                return {"state": "abstain_insufficient_evidence", "legal_date": None, "text": "",
                        "claims": [], "citations": [], "reason": "expected source not retrieved", "unanswered": ""}
            clipped = selected["canonical_text"][:300]
            quote = clipped.rsplit(" ", 1)[0] if len(selected["canonical_text"]) > 300 else clipped
            return {"state": "provisional", "legal_date": None, "text": quote,
                    "claims": [{"claim_id": "snapshot-excerpt", "text": quote, "evidence_ids": [self.expected_id]}],
                    "citations": [{"evidence_id": self.expected_id, "quote": quote, "span_start": 0,
                                   "span_end": len(quote), "document_version_id": selected["document_version_id"]}],
                    "reason": "", "unanswered": ""}

    selector = SpanSelector()
    client = TestClient(create_core_app(provider=selector, experimental_snapshot_excerpt_enabled=True))
    results = []
    for case in CASES:
        selector.expected_id = case["article_id"] + ":" + case["document_version_id"]
        response = client.post("/api/answer", json={"question": case["question"]})
        body = response.json()
        answer = body.get("answer", {})
        citations = answer.get("citations", [])
        citation = citations[0] if len(citations) == 1 else {}
        results.append({**case, "expected_evidence_id": selector.expected_id, "status_code": response.status_code,
                        "state": answer.get("state"), "citation_valid": body.get("validation", {}).get("valid"),
                        "retrieval_contains_reference": selector.expected_id in body.get("retrieval", {}).get("selected_evidence_ids", []),
                        "evidence_matches_reference": citation.get("evidence_id") == selector.expected_id,
                        "safe_abstention": answer.get("state") == "abstain_insufficient_evidence" and selector.expected_id not in body.get("retrieval", {}).get("selected_evidence_ids", []),
                        "quote_sha256": hashlib.sha256(citation.get("quote", "").encode("utf-8")).hexdigest(),
                        "quote_length_chars": len(citation.get("quote", "")),
                        "provider": "injected deterministic source-span selector"})
    passed = all(row["status_code"] == 200 and (row["state"] == "provisional" and row["citation_valid"]
                 and row["evidence_matches_reference"] or row["safe_abstention"]) for row in results)
    report = {"evaluation": "snapshot-excerpt-fidelity-v1", "dataset_revision": REVISION,
              "implementation_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                                         for name in ("scripts/app.py", "scripts/core_app.py", "scripts/provisional_policy.py",
                                                      "scripts/answer_contract.py", "scripts/core_retriever.py", "scripts/eval_snapshot_excerpt.py")},
              "interpretation": "Uses pinned corpus and local Qdrant retrieval plus an injected deterministic provider that selects only frozen reference evidence; checks target retrieval and exact citation fidelity, not model quality, legal correctness, or legal validity.",
              "provider_calls": selector.calls, "results": results,
              "coverage": {"cases": len(results), "passed": sum(row["citation_valid"] is True and row["evidence_matches_reference"] for row in results),
                           "safe_abstentions": sum(row["safe_abstention"] for row in results),
                           "reference_retrieval_hits": sum(row["retrieval_contains_reference"] for row in results),
                           "development": sum(row["split"] == "development" for row in results),
                           "held_out": sum(row["split"] == "held_out" for row in results)},
              "manual_relevance_review": "Article labels and frozen questions were inspected for topic match; excerpt selection is deterministic and cannot establish broader semantic relevance."}
    output = ROOT / "docs" / "snapshot-excerpt-fidelity-v1.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output.relative_to(ROOT)), "coverage": report["coverage"],
                      "provider_calls": selector.calls, "passed": passed}, ensure_ascii=False, indent=2))
    if not passed:
        raise SystemExit("snapshot excerpt fidelity check failed")


if __name__ == "__main__":
    main()
