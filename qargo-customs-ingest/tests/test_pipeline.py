import io

from pypdf import PdfWriter

from customs_ingest.graph_client import Attachment, Message
from customs_ingest.pipeline import process_message, upload_name
from customs_ingest.reference import find_references
from customs_ingest.state import State


def blank_pdf() -> bytes:
    w = PdfWriter()
    w.add_blank_page(100, 100)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


PDF = blank_pdf()


class FakeQargo:
    def __init__(self, orders):
        self.orders, self.uploads = orders, []

    def find_order_id(self, ref):
        return self.orders.get(ref)

    def upload_document(self, order_id, filename, data, document_type):
        self.uploads.append((order_id, filename, document_type))


def msg(subject, body="", atts=None):
    return Message("m1", subject, body, "broker@example.com", "2026-11-17", atts or [Attachment("a1", "EAD.pdf", "application/pdf", PDF)])


def test_find_references_variants():
    assert find_references("Re: RXOE123456 export") == ["RXOE123456"]
    assert find_references("rxoe-123456 and RXOE 123456") == ["RXOE123456"]
    assert find_references("XRXOE123456 / RXOE12") == []
    assert find_references("RXOE111111, RXOE222222") == ["RXOE111111", "RXOE222222"]


def test_uploads_to_order_from_subject(tmp_path):
    q = FakeQargo({"RXOE123456": "ord-1"})
    res = process_message(msg("Clearance RXOE123456"), q, State(str(tmp_path / "s.db")), "Customs Document", dry_run=False)
    assert not res.needs_review
    assert q.uploads == [("ord-1", "RXOE123456_EAD.pdf", "Customs Document")]


def test_rerun_does_not_double_upload(tmp_path):
    q, st = FakeQargo({"RXOE123456": "ord-1"}), State(str(tmp_path / "s.db"))
    process_message(msg("RXOE123456"), q, st, "Customs Document", dry_run=False)
    res = process_message(msg("RXOE123456"), q, st, "Customs Document", dry_run=False)
    assert len(q.uploads) == 1 and res.files[0].status == "already_uploaded"


def test_dry_run_uploads_nothing(tmp_path):
    q = FakeQargo({"RXOE123456": "ord-1"})
    res = process_message(msg("RXOE123456"), q, State(str(tmp_path / "s.db")), "Customs Document", dry_run=True)
    assert q.uploads == [] and res.files[0].status == "would_upload"


def test_unknown_order_goes_to_review(tmp_path):
    res = process_message(msg("RXOE999999"), FakeQargo({}), State(str(tmp_path / "s.db")), "Customs Document", False)
    assert res.needs_review and "not found" in res.files[0].reason


def test_no_reference_goes_to_review(tmp_path):
    res = process_message(msg("Customs docs attached"), FakeQargo({}), State(str(tmp_path / "s.db")), "Customs Document", False)
    assert res.needs_review and "no RXOE" in res.files[0].reason


def test_multiple_refs_resolved_by_filename(tmp_path):
    atts = [Attachment("a1", "RXOE111111 EAD.pdf", None, PDF), Attachment("a2", "RXOE222222_T1.pdf", None, PDF)]
    q = FakeQargo({"RXOE111111": "o1", "RXOE222222": "o2"})
    res = process_message(msg("RXOE111111 / RXOE222222", atts=atts), q, State(str(tmp_path / "s.db")), "Customs Document", False)
    assert not res.needs_review
    assert sorted(u[0] for u in q.uploads) == ["o1", "o2"]


def test_multiple_refs_unresolved_goes_to_review(tmp_path):
    q = FakeQargo({"RXOE111111": "o1", "RXOE222222": "o2"})
    res = process_message(msg("RXOE111111 / RXOE222222"), q, State(str(tmp_path / "s.db")), "Customs Document", False)
    assert res.needs_review and "ambiguous" in res.files[0].reason and q.uploads == []


def test_non_pdf_only_goes_to_review(tmp_path):
    atts = [Attachment("a1", "logo.png", "image/png", b"\x89PNG")]
    res = process_message(msg("RXOE123456", atts=atts), FakeQargo({}), State(str(tmp_path / "s.db")), "Customs Document", False)
    assert res.needs_review and res.reason == "no PDF attachments"


def test_upload_name_keeps_existing_reference():
    assert upload_name("RXOE123456", "RXOE 123456 MRN.pdf") == "RXOE 123456 MRN.pdf"
    assert upload_name("RXOE123456", "RXOE123456_MRN.pdf") == "RXOE123456_MRN.pdf"
    assert upload_name("RXOE123456", "scan") == "RXOE123456_scan.pdf"
