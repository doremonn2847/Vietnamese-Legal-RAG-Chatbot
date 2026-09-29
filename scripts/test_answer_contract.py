import unittest
from datetime import date

from answer_contract import answer_state, validate_citations


class AnswerContractTest(unittest.TestCase):
    def test_citations_must_reference_known_evidence(self):
        evidence = {"E1": {"canonical_text": "Thời gian thử việc được giới hạn trong 60 ngày.", "source_start": 10, "source_end": 55, "reviewed_version_id": "v1", "reviewed_status": "reviewed", "central_eligible": True, "effective_from_day": date(2020, 1, 1).toordinal(), "effective_to_day": date(2030, 1, 1).toordinal(), "reviewed_through_day": date(2026, 1, 1).toordinal()}}
        answer = {"state": "answer", "legal_date": "2024-01-01", "claims": [{"claim_id": "C1", "text": "Thời gian thử việc được giới hạn trong 60 ngày.", "evidence_ids": ["E1"]}], "citations": [{"evidence_id": "E1", "quote": "Thời gian thử việc được giới hạn trong 60 ngày.", "span_start": 0, "span_end": 47, "reviewed_version_id": "v1"}], "text": "Thời gian thử việc được giới hạn trong 60 ngày."}
        result = validate_citations(answer, evidence, requested_legal_date="2024-01-01")
        self.assertTrue(result["valid"])
        self.assertEqual(validate_citations({"state": "answer", "claims": [{"claim_id": "C1", "text": "Kết luận", "evidence_ids": ["E9"]}], "citations": [], "text": "Kết luận"}, evidence, requested_legal_date="2024-01-01")["unknown_ids"], ["E9"])

    def test_missing_claim_citation_is_reported(self):
        result = validate_citations({"state": "answer", "claims": [{"claim_id": "C1", "text": "Thời gian thử việc được giới hạn.", "evidence_ids": []}], "citations": [], "text": "Thời gian thử việc được giới hạn."}, {"E1": {"canonical_text": "Điều 25", "source_start": 0, "source_end": 8, "reviewed_version_id": "v1", "reviewed_status": "reviewed", "central_eligible": True, "effective_from_day": 700000, "effective_to_day": 800000, "reviewed_through_day": 800000}}, requested_legal_date="2024-01-01")
        self.assertFalse(result["valid"])
        self.assertEqual(result["uncited_claims"], ["C1"])

    def test_quote_and_reviewed_version_are_required(self):
        evidence = {"E1": {"canonical_text": "Nội dung Điều 25", "source_start": 0, "source_end": 16, "reviewed_version_id": "v1", "reviewed_status": "reviewed", "central_eligible": True, "effective_from_day": 700000, "effective_to_day": 800000, "reviewed_through_day": 800000}}
        answer = {"state": "answer", "legal_date": "2024-01-01", "claims": [{"claim_id": "C1", "text": "Nội dung Điều 25", "evidence_ids": ["E1"]}], "citations": [{"evidence_id": "E1", "quote": "example", "span_start": 999, "span_end": 1006, "reviewed_version_id": "v2"}], "text": "Nội dung Điều 25"}
        result = validate_citations(answer, evidence, requested_legal_date="2024-01-01")
        self.assertFalse(result["valid"])
        self.assertTrue(result["invalid_citations"])

    def test_unreviewed_or_out_of_date_evidence_cannot_ground_answer(self):
        evidence = {"E1": {"canonical_text": "Nội dung", "source_start": 0, "source_end": 8, "reviewed_version_id": "v1", "reviewed_status": "unreviewed", "central_eligible": True, "effective_from_day": 700000, "effective_to_day": 800000, "reviewed_through_day": 700000}}
        answer = {"state": "answer", "legal_date": "2024-01-01", "claims": [{"claim_id": "C1", "text": "Nội dung", "evidence_ids": ["E1"]}], "citations": [{"evidence_id": "E1", "quote": "Nội dung", "span_start": 0, "span_end": 8, "reviewed_version_id": "v1"}], "text": "Nội dung"}
        self.assertFalse(validate_citations(answer, evidence, requested_legal_date="2024-01-01")["valid"])

    def test_server_date_is_required_and_schema_errors_are_controlled(self):
        evidence = {"E1": {"canonical_text": "Nội dung", "source_start": 0, "source_end": 8, "reviewed_version_id": "v1", "reviewed_status": "reviewed", "central_eligible": True, "effective_from_day": 700000, "effective_to_day": 800000, "reviewed_through_day": 800000}}
        answer = {"state": "answer", "claims": [{"claim_id": "C1", "text": "Nội dung", "evidence_ids": ["E1"]}], "citations": [{"evidence_id": "E1", "quote": "Nội dung", "span_start": 0, "span_end": 8, "reviewed_version_id": "v1"}], "text": "Nội dung"}
        self.assertFalse(validate_citations(answer, evidence)["valid"])
        self.assertFalse(validate_citations({"state": "answer", "claims": ["bad"], "citations": [], "text": "bad"}, evidence, requested_legal_date="2024-01-01")["valid"])
        self.assertFalse(validate_citations({"state": "answer"}, {}, requested_legal_date="2024-01-01")["valid"])
        self.assertFalse(validate_citations({"state": "partial", "claims": [{"claim_id": "C1", "text": "Nội dung", "evidence_ids": None}], "citations": [], "text": "Nội dung"}, evidence, requested_legal_date="2024-01-01")["valid"])
        self.assertFalse(validate_citations({"state": "clarify", "citations": [{"evidence_id": ["E1"]}]}, {}, requested_legal_date="2024-01-01")["valid"])

    def test_answer_state_prefers_clarification_then_abstention(self):
        self.assertEqual(answer_state(missing_facts=True, evidence_conflict=False, sufficient_evidence=True), "clarify")
        self.assertEqual(answer_state(missing_facts=False, evidence_conflict=True, sufficient_evidence=True), "abstain_conflict")
        self.assertEqual(answer_state(missing_facts=False, evidence_conflict=False, sufficient_evidence=False), "abstain_insufficient_evidence")
        self.assertEqual(answer_state(missing_facts=False, evidence_conflict=False, sufficient_evidence=True), "answer")


if __name__ == "__main__":
    unittest.main()
