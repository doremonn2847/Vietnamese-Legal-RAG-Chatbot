import unittest

from provisional_policy import decide_provisional_eligibility


class ProvisionalPolicyTest(unittest.TestCase):
    def setUp(self):
        self.evidence = {
            "article_id": "a1", "document_version_id": "v1", "canonical_text": "Điều 24. Thử việc tối đa sáu mươi ngày.",
            "pham_vi": "Trung ương", "retrieval_index_candidate": True, "answer_evidence_enabled": False,
            "current_validity": "unverified", "expiry_state": "unknown_expiry",
            "amendment_state": "not_verified", "reported_status_conflict": False,
            "source_dataset_revision": "revision-1", "content_sha256": "sha256-fixture",
        }

    def test_allows_snapshot_text_only_for_exact_central_unverified_evidence(self):
        decision = decide_provisional_eligibility("Điều 24 quy định gì về thử việc?", [self.evidence])
        self.assertTrue(decision["allowed"])
        self.assertEqual(decision["mode"], "provisional_snapshot")
        self.assertIn("chưa được xác minh", decision["caveat"].casefold())

    def test_explicit_as_of_date_abstains(self):
        decision = decide_provisional_eligibility("Thử việc vào ngày 2024-01-01 được quy định thế nào?", [self.evidence])
        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["reason"], "requested_date_unverified")

    def test_current_validity_question_abstains_and_conflict_is_named(self):
        conflicted = {**self.evidence, "reported_status_conflict": True}
        decision = decide_provisional_eligibility("Bộ luật hiện còn hiệu lực không?", [conflicted])
        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["reason"], "conflicting_status")

    def test_applicability_and_amendment_questions_abstain(self):
        applicability = decide_provisional_eligibility("Tôi có buộc phải tuân thủ Điều 24 hôm nay không?", [self.evidence])
        amendments = decide_provisional_eligibility("Cho tôi bản hợp nhất mới nhất của Điều 24", [self.evidence])
        self.assertEqual(applicability["reason"], "validity_unverified")
        self.assertEqual(amendments["reason"], "amendments_unverified")

    def test_rejects_noncentral_or_promoted_validity_metadata(self):
        for changed in ({"pham_vi": "Địa phương"}, {"current_validity": "current"}, {"retrieval_index_candidate": False}):
            with self.subTest(changed=changed):
                decision = decide_provisional_eligibility("Điều 24 nói gì?", [{**self.evidence, **changed}])
                self.assertFalse(decision["allowed"])
                self.assertEqual(decision["reason"], "evidence_not_provisional_eligible")

    def test_no_evidence_abstains(self):
        decision = decide_provisional_eligibility("Điều 24 nói gì?", [])
        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["reason"], "no_evidence")

    def test_explicit_as_of_request_is_classified_even_when_retrieval_is_empty(self):
        decision = decide_provisional_eligibility("Quy định năm 2024 áp dụng thế nào?", [])
        self.assertEqual(decision["reason"], "requested_date_unverified")


if __name__ == "__main__":
    unittest.main()
