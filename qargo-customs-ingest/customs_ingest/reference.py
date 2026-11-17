"""Find RXOE order references in text."""
import re

# RXOE followed by digits, tolerating a space/dash/underscore between (e.g. "RXOE 123456", "rxoe-123456").
# Lookarounds stop us matching inside a longer token.
_RXOE = re.compile(r"(?<![A-Z0-9])RXOE[\s\-_]?(\d{4,12})(?!\d)", re.IGNORECASE)


def find_references(text: str | None) -> list[str]:
    """Return distinct normalised references (e.g. 'RXOE123456') in order of first appearance."""
    if not text:
        return []
    seen: dict[str, None] = {}
    for m in _RXOE.finditer(text):
        seen.setdefault(f"RXOE{m.group(1)}", None)
    return list(seen)
