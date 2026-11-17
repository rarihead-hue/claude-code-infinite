"""Decides, for each email, which Qargo order each customs PDF belongs to, then uploads it."""
import logging
from dataclasses import dataclass, field

from .graph_client import Attachment, Message
from .pdf_text import extract_text, is_pdf
from .reference import find_references
from .state import State

log = logging.getLogger(__name__)


@dataclass
class FileResult:
    filename: str
    reference: str | None = None
    order_id: str | None = None
    status: str = "pending"  # uploaded | would_upload | already_uploaded | review
    reason: str = ""


@dataclass
class MessageResult:
    message_id: str
    subject: str
    files: list[FileResult] = field(default_factory=list)
    reason: str = ""

    @property
    def needs_review(self) -> bool:
        return bool(self.reason) or any(f.status == "review" for f in self.files)


def pick_reference(email_refs: list[str], att: Attachment) -> tuple[str | None, str]:
    """Return (reference, reason-if-none). The email subject/body is the primary source;
    the PDF filename and text are only used when the email is missing or ambiguous."""
    if len(email_refs) == 1:
        return email_refs[0], ""
    doc_refs = find_references(att.name) or find_references(extract_text(att.data))
    if email_refs:  # several refs in the email: the PDF must say which one it belongs to
        doc_refs = [r for r in doc_refs if r in email_refs]
    if len(doc_refs) == 1:
        return doc_refs[0], ""
    if not email_refs and not doc_refs:
        return None, "no RXOE reference found in email or PDF"
    return None, f"ambiguous RXOE reference (email: {email_refs or '-'}, PDF: {doc_refs or '-'})"


def upload_name(reference: str, original: str) -> str:
    name = original if original.lower().endswith(".pdf") else f"{original}.pdf"
    return name if reference.lower() in name.lower().replace(" ", "") else f"{reference}_{name}"


def process_message(msg: Message, qargo, state: State, document_type: str, dry_run: bool,
                    order_cache: dict[str, str | None] | None = None) -> MessageResult:
    result = MessageResult(msg.id, msg.subject)
    cache = order_cache if order_cache is not None else {}
    pdfs = [a for a in msg.attachments if is_pdf(a.name, a.content_type, a.data)]
    if not pdfs:
        result.reason = "no PDF attachments"
        return result

    email_refs = find_references(f"{msg.subject}\n{msg.body_text}")
    for att in pdfs:
        fr = FileResult(att.name)
        result.files.append(fr)

        fr.reference, why = pick_reference(email_refs, att)
        if not fr.reference:
            fr.status, fr.reason = "review", why
            continue

        if fr.reference not in cache:
            try:
                cache[fr.reference] = qargo.find_order_id(fr.reference)
            except Exception as exc:
                fr.status, fr.reason = "review", f"Qargo lookup error: {exc}"
                continue
        fr.order_id = cache[fr.reference]
        if not fr.order_id:
            fr.status, fr.reason = "review", f"{fr.reference} not found in Qargo"
            continue

        if state.already_uploaded(msg.id, att.id):
            fr.status = "already_uploaded"
            continue
        if dry_run:
            fr.status = "would_upload"
            continue
        name = upload_name(fr.reference, att.name)
        try:
            qargo.upload_document(fr.order_id, name, att.data, document_type)
        except Exception as exc:
            fr.status, fr.reason = "review", f"upload error: {exc}"
            continue
        state.record(msg.id, att.id, fr.reference, fr.order_id, name)
        fr.status = "uploaded"
        log.info("Uploaded %s to %s (order %s)", name, fr.reference, fr.order_id)
    return result
