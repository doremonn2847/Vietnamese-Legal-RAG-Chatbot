"""Run with: .venv/Scripts/python.exe -m unittest discover -s scripts -p test_*.py"""
import unittest

from audit_corpus import duplicate_groups, expiry_state, issuer_signal, scope_reason, text_fingerprint


class AuditPolicyTest(unittest.TestCase):
    def test_strict_scope_issuer_and_validity(self):
        self.assertEqual(scope_reason("  TRUNG   ƯƠNG "), "central_exact")
        for value in ("Địa phương", "Huyện Yên Minh", "TỈNH BÌNH PHƯỚC", "Xã Đức Xuân", "Tuyên Quang"):
            self.assertEqual(scope_reason(value), "exclude_local_scope")
        self.assertEqual(scope_reason("Toàn quốc"), "quarantine_unrecognized_scope")
        self.assertEqual(scope_reason("Tuyên"), "quarantine_unrecognized_scope")
        self.assertEqual(scope_reason(None), "quarantine_missing_scope")
        self.assertEqual(issuer_signal("UỶ BAN NHÂN DÂN TỈNH QUẢNG TRỊ"), "local_issuer_signal")
        self.assertEqual(issuer_signal("Bộ Lao động - Thương binh và Xã hội"), "central_issuer_signal")
        self.assertEqual(issuer_signal("Bộ Tài chính, UBND tỉnh An Giang"), "local_issuer_signal")
        self.assertEqual(issuer_signal("Ngân hàng Nhà nước Việt Nam, Chưa xác định"), "missing_or_unknown_issuer")
        for status in ("Còn hiệu lực", "Hết hiệu lực toàn bộ", None):
            self.assertEqual(expiry_state({"ngay_het_hieu_luc": " ", "tinh_trang_hieu_luc": status}), "unknown_expiry")

    def test_content_and_duplicate_boundaries(self):
        self.assertEqual(text_fingerprint('<html><head><title>Document Content</title></head><body><img src="scan.png"></body></html>'), "")
        self.assertEqual(text_fingerprint("<p>&nbsp;</p><!-- junk --><script>x()</script>"), "")
        self.assertEqual(text_fingerprint("<p>Điều 1</p><p> A &amp; B </p>"), "Điều 1 A & B")
        self.assertEqual(duplicate_groups({"a": ["001", "uuid"], "b": ["002"]}), {"a": ["001", "uuid"]})


if __name__ == "__main__":
    unittest.main()
