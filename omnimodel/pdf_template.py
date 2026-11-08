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


_BULLET = re.compile(r"^(?:[•●▪◦‣·\-–—*]\s|\d{1,2}[.)]\s|[a-z][.)]\s)")


def _is_heading(line: str) -> bool:
    letters = [c for c in line if c.isalpha()]
    return 2 < len(line) < 80 and len(letters) >= 3 and all(c.isupper() for c in letters) and not line.rstrip().endswith((".", ","))


def reflow(lines: list[str]) -> str:
    """A PDF stores every printed line on its own. Join the lines of one paragraph back together so the text can be
    edited, keeping headings, bullets and short closing lines as their own lines."""
    lengths = sorted(len(x) for x in lines if len(x) > 20)
    full = (lengths[int(len(lengths) * 0.9)] if lengths else 0) * 0.82     # a line this long probably wrapped
    out: list[str] = []
    cur = ""
    prev = ""
    for line in lines:
        if not cur:
            cur = line
        elif (_is_heading(prev) or _is_heading(line) or _BULLET.match(line) or len(prev) < full
              or (line[:1].isupper() and prev.rstrip().endswith((".", ":", "?", "!")) and len(prev) < full * 1.1)):
            out.append(cur)
            cur = line
        else:
            cur = cur + ("" if cur.endswith("-") and line[:1].islower() else " ") + line
        prev = line
    if cur:
        out.append(cur)
    # headings and list items stay tight; ordinary paragraphs get a blank line between them
    parts: list[str] = []
    for i, para in enumerate(out):
        parts.append(para)
        if i + 1 < len(out):
            nxt = out[i + 1]
            tight = (_BULLET.match(para) and _BULLET.match(nxt)) or _is_heading(para)
            parts.append("\n" if tight else "\n\n")
    return "".join(parts)


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

    text = reflow([ln for page in _drop_repeats(pages) for ln in page]).strip()
    if len(text) < 40:
        raise PdfProblem("We found no text in that PDF. It may be a scan or a photo. Export it from Word or Google Docs instead.")
    return {"text": text, "pages": total, "truncated": total > MAX_PAGES}