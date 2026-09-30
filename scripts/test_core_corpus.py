import unittest

from curate_core_corpus import classify_topic_candidates, select_core_records


class CoreCorpusTest(unittest.TestCase):
    def setUp(self):
        self.metadata = {
            "139264": {"id": "139264", "title": "Bộ Luật lao động số 45/2019/QH14", "so_ky_hieu": "45/2019/QH14", "ngay_ban_hanh": "20/11/2019", "loai_van_ban": "Bộ luật", "co_quan_ban_hanh": "Quốc hội", "pham_vi": "Trung ương"},
            "vbpqta_11135": {"id": "vbpqta_11135", "title": "Code 45/2019/QH14", "so_ky_hieu": "45/2019/QH14", "ngay_ban_hanh": "20/11/2019", "loai_van_ban": "Bản dịch văn bản", "co_quan_ban_hanh": "Quốc hội", "pham_vi": "Trung ương"},
            "152668": {"id": "152668", "title": "Nghị định số 145/2020/NĐ-CP", "so_ky_hieu": "145/2020/NĐ-CP", "ngay_ban_hanh": "14/12/2020", "loai_van_ban": "Nghị định", "co_quan_ban_hanh": "Chính phủ", "pham_vi": "Trung ương"},
            "146696": {"id": "146696", "title": "Thông tư số 10/2020/TT-BLĐTBXH", "so_ky_hieu": "10/2020/TT-BLĐTBXH", "ngay_ban_hanh": "12/11/2020", "loai_van_ban": "Thông tư", "co_quan_ban_hanh": "Bộ Lao động - Thương binh và Xã hội", "pham_vi": "Trung ương"},
        }
        self.content = {
            "139264": "<p>QUỐC HỘI</p><p>Bộ luật Lao động</p>",
            "vbpqta_11135": "<p>LABOR CODE</p><p>The National Assembly promulgates this Code.</p>",
            "152668": "<p>Nghị định</p>",
            "146696": "<p>Thông tư</p>",
        }
        self.decisions = {
            "139264": self._decision("139264", "quarantine_duplicate_bibliographic_identity", '["duplicate_bibliographic_identity"]', "Hết hiệu lực một phần"),
            "vbpqta_11135": self._decision("vbpqta_11135", "quarantine_duplicate_bibliographic_identity", '["duplicate_bibliographic_identity"]', "Còn hiệu lực"),
            "152668": self._decision("152668", "include_for_employment_review"),
            "146696": self._decision("146696", "include_for_employment_review"),
        }
        self.groups = [{"kind": "bibliographic_identity", "ids_json": '["139264", "vbpqta_11135"]'}]

    @staticmethod
    def _decision(doc_id, reason, flags="[]", status="Còn hiệu lực"):
        return {"id": doc_id, "scope_reason": "central_exact", "content_state": "present", "issuer_signal": "central_issuer_signal", "visible_characters": "100", "primary_reason": reason, "all_flags_json": flags, "current_validity": "unverified", "expiry_state": "unknown_expiry", "reported_expiry": "", "reported_status": status}

    def test_selects_only_named_central_core_and_keeps_translation_separate(self):
        docs, ledger = select_core_records(self.metadata, self.content, self.decisions, self.groups)
        self.assertEqual({row["id"] for row in docs}, {"139264", "152668", "146696"})
        self.assertEqual(next(row for row in docs if row["id"] == "139264")["content_html"], self.content["139264"])
        self.assertEqual(len(ledger), 1)
        self.assertEqual(ledger[0]["selected_id"], "139264")
        self.assertEqual(ledger[0]["suppressed_id"], "vbpqta_11135")
        self.assertEqual(ledger[0]["content_merged"], "false")
        labor_code = next(row for row in docs if row["id"] == "139264")
        self.assertTrue(labor_code["retrieval_index_candidate"])
        self.assertFalse(labor_code["answer_evidence_enabled"])
        self.assertTrue(labor_code["reported_status_conflict"])
        self.assertEqual(labor_code["corpus_disposition"], "retrieval_only_temporal_uncertainty")
        self.assertIn(labor_code["reported_expiry_date"], (None, ""))
        self.assertEqual(labor_code["expiry_state"], "unknown_expiry")
        self.assertEqual(labor_code["current_validity"], "unverified")

    def test_fails_closed_on_noncentral_core_record(self):
        self.decisions["152668"]["scope_reason"] = "quarantine_unrecognized_scope"
        with self.assertRaisesRegex(ValueError, "central-only"):
            select_core_records(self.metadata, self.content, self.decisions, self.groups)

    def test_topic_candidates_use_article_heading_not_body_mentions(self):
        self.assertEqual(classify_topic_candidates("Điều 24. Thử việc"), ["probation"])
        self.assertEqual(classify_topic_candidates("Điều 1. Phạm vi điều chỉnh"), [])


if __name__ == "__main__":
    unittest.main()
