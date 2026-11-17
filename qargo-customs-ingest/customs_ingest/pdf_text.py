"""Extract text from a PDF (used as a fallback for finding the RXOE reference)."""
import io
import logging

from pypdf import PdfReader

log = logging.getLogger(__name__)


def is_pdf(name: str, content_type: str | None, data: bytes) -> bool:
    return data[:5] == b"%PDF-" or name.lower().endswith(".pdf") or (content_type or "").lower() == "application/pdf"


def extract_text(data: bytes, max_pages: int = 10) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages[:max_pages])
    except Exception as exc:  # corrupt / encrypted / scanned-only PDFs
        log.warning("Could not read PDF text: %s", exc)
        return ""
