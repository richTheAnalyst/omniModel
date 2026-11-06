"""Read the text of a proposal PDF so it can become a template. Text only: layout, images and tables are not kept."""
from __future__ import annotations

import io
import re
from collections import Counter

MAX_BYTES = 5 * 1024 * 1024
MAX_PAGES = 40
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class PdfProblem(ValueError):
    """Something the person can fix (not a PDF, locked, scanned, too big). The message is safe to show them."""


def _drop_repeats(pages: list[list[str]]) -> list[list[str]]:
    """Remove lines printed on every page (letterheads, footers) and bare page numbers."""
    if len(pages) >= 3:
        seen = Counter(line for page in pages for line in set(page))
        repeated = {line for line, n in seen.items() if n == len(pages) and len(line) < 120}
    else:
        repeated = set()
    number = re.compile(r"^(page\s*)?\d{1,3}(\s*(of|/)\s*\d{1,3})?$", re.I)
    return [[ln for ln in page if ln not in repeated and not number.match(ln)] for page in pages]


def extract_text(data: bytes) -> dict:
    """Returns {"text", "pages", "truncated"}. Raises PdfProblem with a plain-language reason."""
    if not data:
        raise PdfProblem("The file is empty.")
    if len(data) > MAX_BYTES:
        raise PdfProblem(f"That PDF is larger than {MAX_BYTES // (1024 * 1024)} MB. Export a smaller copy and try again.")
    if not data.lstrip()[:5] == b"%PDF-":
        raise PdfProblem("That file is not a PDF.")
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise PdfProblem("That PDF is password protected. Save an unlocked copy and try again.")
        total = len(reader.pages)
        pages = []
        for page in list(reader.pages)[:MAX_PAGES]:
            raw = _CONTROL.sub("", page.extract_text() or "")
            pages.append([re.sub(r"[ \t]+", " ", ln).strip() for ln in raw.splitlines() if ln.strip()])
    except PdfProblem:
        raise
    except Exception as exc:  # a damaged file can fail in many ways inside the parser
        raise PdfProblem("We could not read that PDF. It may be damaged; try saving it again from the original.") from exc

    text = "\n".join("\n".join(page) + "\n" for page in _drop_repeats(pages))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) < 40:
        raise PdfProblem("We found no text in that PDF. It may be a scan or a photo. Export it from Word or Google Docs instead.")
    return {"text": text, "pages": total, "truncated": total > MAX_PAGES}