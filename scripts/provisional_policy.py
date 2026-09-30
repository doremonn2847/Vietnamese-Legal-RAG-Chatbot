"""Fail-closed policy for quoting text from the inactive dataset snapshot."""
import re


PROVISIONAL_CAVEAT = (
    "Trả lời này chỉ mô tả nội dung trong bản dữ liệu đã thu thập; "
    "hiệu lực hiện tại, sửa đổi và tình trạng áp dụng chưa được xác minh."
)
_VALIDITY_QUERY = re.compile(r"\b(hiện nay|hiện tại|hiện hành|hôm nay|today|còn hiệu lực|hết hiệu lực|tình trạng hiệu lực|hiệu lực|đang có hiệu lực|đang áp dụng|còn áp dụng|áp dụng hiện tại|buộc phải tuân thủ|phải tuân thủ|có bắt buộc|có nghĩa vụ|must comply|applicable|validity|currently|in force|currently applicable)\b", re.IGNORECASE)
_AS_OF_QUERY = re.compile(r"\b(?:tính đến ngày|vào ngày|as of)\b|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/(?:19|20)\d{2}\b|\bnăm\s+(?:19|20)\d{2}\b", re.IGNORECASE)
_AMENDMENT_QUERY = re.compile(r"\b(sửa đổi|bổ sung|bản hợp nhất|hợp nhất|mới nhất|đã sửa đổi|amendment|consolidated|latest version)\b", re.IGNORECASE)
_SOURCE_TEXT_REQUEST = re.compile(r"\b(?:điều\s+\d+\s+(?:quy định|nói|ghi)\s+gì|nội dung\s+(?:của\s+)?điều\s+\d+|trích\s+(?:nguyên văn\s+)?(?:điều\s+)?\d+|what does article\s+\d+\s+say|(?:show|quote)\s+(?:me\s+)?(?:the\s+)?(?:exact\s+)?(?:text|quote)\s+(?:of\s+)?article\s+\d+|exact text of article\s+\d+)\b", re.IGNORECASE)
_MESSAGES = {
    "conflicting_status": "Tình trạng hiệu lực trong các bản ghi xung đột; chưa thể xác nhận câu trả lời theo thời điểm yêu cầu.",
    "validity_unverified": "Bản dữ liệu chưa xác minh hiệu lực hiện tại hoặc tình trạng áp dụng.",
    "requested_date_unverified": "Bản dữ liệu chưa đủ thông tin để xác nhận quy định áp dụng vào ngày yêu cầu.",
    "amendments_unverified": "Các quan hệ sửa đổi/hợp nhất chưa được xác minh; bản trích chỉ thể hiện nội dung của nguồn đã ghim.",
    "source_text_request_required": "Chỉ có thể trích nội dung nguồn khi câu hỏi yêu cầu rõ văn bản; câu hỏi áp dụng pháp luật cần được xác minh riêng.",
    "no_evidence": "Không tìm thấy đoạn văn bản phù hợp trong phạm vi dữ liệu này.",
    "evidence_not_provisional_eligible": "Đoạn văn bản không đạt điều kiện để trích dẫn tạm thời.",
}


def decide_provisional_eligibility(question, evidence, *, requested_as_of_date=False):
    """Allow only snapshot-text questions; never assert an unverified legal date/status."""
    rows = evidence if isinstance(evidence, list) else []
    conflict = any(isinstance(row, dict) and row.get("reported_status_conflict") is True for row in rows)
    query = question if isinstance(question, str) else ""
    if _VALIDITY_QUERY.search(query):
        return _deny("conflicting_status" if conflict else "validity_unverified")
    if requested_as_of_date or _AS_OF_QUERY.search(query):
        return _deny("conflicting_status" if conflict else "requested_date_unverified")
    if _AMENDMENT_QUERY.search(query):
        return _deny("amendments_unverified")
    if not _SOURCE_TEXT_REQUEST.search(query):
        return _deny("source_text_request_required")
    if not rows:
        return _deny("no_evidence")

    for row in rows:
        if not isinstance(row, dict) or row.get("pham_vi") != "Trung ương" or row.get("retrieval_index_candidate") is not True or row.get("current_validity") != "unverified" or row.get("expiry_state") != "unknown_expiry" or type(row.get("reported_status_conflict")) is not bool or not isinstance(row.get("source_dataset_revision"), str) or not row["source_dataset_revision"].strip() or not isinstance(row.get("content_sha256"), str) or not row["content_sha256"].strip() or not isinstance(row.get("document_version_id"), str) or not row["document_version_id"].strip() or not isinstance(row.get("canonical_text"), str) or not row["canonical_text"].strip():
            return _deny("evidence_not_provisional_eligible")
    return {"allowed": True, "mode": "provisional_snapshot", "reason": "snapshot_text_only", "message": "Có thể mô tả nội dung trong bản dữ liệu.", "caveat": PROVISIONAL_CAVEAT}


def _deny(reason):
    return {"allowed": False, "mode": "abstain", "reason": reason, "message": _MESSAGES[reason], "caveat": PROVISIONAL_CAVEAT}
