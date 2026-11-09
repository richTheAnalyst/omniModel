"""Fill a person's own proposal PDF for a new company, keeping its logos, images, tables and layout.

The PDF is never rebuilt. Each line of text that contains one of the sample's details (the old client's name, a city,
your own phone number) is removed from the page and written again with the new value in the same place, size and colour.
Everything else on the page is left exactly as it was, and the old text is really removed, not hidden under a box.

Limits worth knowing: the replacement is drawn in a standard font (Helvetica, Times or Courier, bold or italic to match),
a detail split across two separate pieces of text in the PDF is not found, and a replacement is one line (it shrinks a
little to fit rather than wrapping)."""
from __future__ import annotations

import ctypes
import gc
import io
import re

try:                        # a missing library must not stop the whole API from starting; only this feature is off
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw
except ImportError:         # pragma: no cover
    pdfium = raw = None

MIN_CONDENSE = 0.8        # a crowded line may be squeezed sideways to 80% before it is allowed to run on
MIN_SHRINK = 0.6          # a longer replacement may shrink to 60% of the original size before it is allowed to run on
_SERIF_NAMES = ("times", "serif", "caladea", "cambria", "georgia", "garamond", "palatino", "bookman", "century", "minion", "tinos", "charter", "baskerville", "didot")
_FLAG_FIXED, _FLAG_SERIF, _FLAG_ITALIC, _FLAG_FORCEBOLD = 1, 2, 64, 262144


def _utf16(buf, nbytes: int) -> str:
    return bytes(buf)[: max(0, nbytes - 2)].decode("utf-16-le", "ignore")


def _object_text(textpage, obj) -> str:
    n = raw.FPDFTextObj_GetText(obj, textpage.raw, None, 0)
    if n <= 2:
        return ""
    buf = (ctypes.c_ubyte * n)()
    raw.FPDFTextObj_GetText(obj, textpage.raw, ctypes.cast(buf, ctypes.POINTER(ctypes.c_ushort)), n)
    return _utf16(buf, n)


def _font_name(obj) -> tuple[str, bool, bool, bool]:
    """(standard font to use, bold, italic, found). Picks Helvetica, Times or Courier to match the original's look."""
    font = raw.FPDFTextObj_GetFont(obj)
    flags = raw.FPDFFont_GetFlags(font) if font else 0
    name = ""
    if font:
        n = raw.FPDFFont_GetBaseFontName(font, None, 0)
        if n:
            buf = ctypes.create_string_buffer(n)
            raw.FPDFFont_GetBaseFontName(font, buf, n)
            name = buf.value.decode("latin-1", "ignore").lower()
    bold = "bold" in name or "black" in name or "heavy" in name or bool(flags & _FLAG_FORCEBOLD) or (font and 100 <= raw.FPDFFont_GetWeight(font) <= 900 and raw.FPDFFont_GetWeight(font) >= 700)
    italic = "italic" in name or "oblique" in name or bool(flags & _FLAG_ITALIC)
    if "courier" in name or "mono" in name or "consolas" in name or flags & _FLAG_FIXED:
        fam = "Courier"
    elif any(w in name for w in _SERIF_NAMES) and "sans" not in name:
        fam = "Times"
    else:
        fam = "Helvetica"
    if fam == "Times":
        std = "Times-" + ("BoldItalic" if bold and italic else "Bold" if bold else "Italic" if italic else "Roman")
    else:
        std = fam + ("-BoldOblique" if bold and italic else "-Bold" if bold else "-Oblique" if italic else "")
    return std, bool(bold), italic, bool(font)


def _font_size(obj) -> float:
    v = ctypes.c_float()
    raw.FPDFTextObj_GetFontSize(obj, v)
    return v.value


def _font_key(obj) -> str:
    font = raw.FPDFTextObj_GetFont(obj)
    n = raw.FPDFFont_GetBaseFontName(font, None, 0) if font else 0
    if not n:
        return ""
    buf = ctypes.create_string_buffer(n)
    raw.FPDFFont_GetBaseFontName(font, buf, n)
    return buf.value.decode("latin-1", "ignore")


def _bounds(obj) -> tuple[float, float, float, float]:
    l, b, r, t = (ctypes.c_float() for _ in range(4))
    raw.FPDFPageObj_GetBounds(obj, l, b, r, t)
    return l.value, b.value, r.value, t.value


def _matrix(obj):
    m = raw.FS_MATRIX()
    raw.FPDFPageObj_GetMatrix(obj, m)
    return m


def _rgba(obj):
    r, g, b, a = (ctypes.c_uint() for _ in range(4))
    if not raw.FPDFPageObj_GetFillColor(obj, r, g, b, a):
        return 0, 0, 0, 255
    return r.value, g.value, b.value, a.value


def _wide(text: str):
    data = (text + "\0").encode("utf-16-le")
    arr = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    return arr, ctypes.cast(arr, ctypes.POINTER(ctypes.c_ushort))


def _pattern(pairs):
    finds = sorted({f.strip() for f, _ in pairs if f and f.strip()}, key=len, reverse=True)
    if not finds:
        return None, {}
    values = {f.strip().lower(): v for f, v in pairs if f and f.strip()}
    return re.compile("|".join(re.escape(f).replace(r"\ ", r"\s+") for f in finds), re.I), values


def _swap(text: str, rx, values, counts):
    def one(m):
        key = re.sub(r"\s+", " ", m.group(0)).lower()
        for k, v in values.items():
            if re.sub(r"\s+", " ", k) == key:
                counts[k] = counts.get(k, 0) + 1
                return v
        return m.group(0)
    return rx.sub(one, text)


def _unsupported(text: str) -> bool:
    return text.encode("cp1252", "replace").decode("cp1252") != text


def _replace_one(doc, page, obj, new: str, items, page_width: float, seen: dict) -> tuple[int, bool]:
    """Swap one piece of text for another on the same line, in the same place and style.
    Text that flows on after it moves to follow. If the line would run past its margin, the whole line is squeezed a
    little (down to 80% width), and a line that is just this one piece may shrink its size instead. Pieces beyond a gap
    (another table column) stay where they are. Returns (1 if anything had to be made smaller to fit, True if a character could not be drawn)."""
    l, b, r, t = _bounds(obj.raw)
    m = _matrix(obj.raw)
    size = _font_size(obj.raw) * abs(m.d or 1.0)        # the size it is actually drawn at on the page
    std, _, _, _ = _font_name(obj.raw)
    cr, cg, cb, ca = _rgba(obj.raw)
    old_width = r - l
    gap = size * 0.7
    original = raw.FPDFTextObj_GetFont(obj.raw)
    key = _font_key(obj.raw)

    same_line = []
    for other, otext in items:
        if other is obj or not otext.strip():
            continue
        try:
            ol, ob, orr, ot = _bounds(other.raw)
        except Exception:
            continue
        if abs(ob - b) < max(2.0, size * 0.4):
            same_line.append((ol, orr, other))
    same_line.sort(key=lambda x: x[0])
    right = [x for x in same_line if x[0] >= r - 1]
    left = [x for x in same_line if x[1] <= l + 1]

    after, edge = [], r                       # pieces flowing on to the right
    for ol, orr, other in right:
        if ol - edge <= gap:
            after.append(other)
            edge = max(edge, orr)
        else:
            break
    before, start = [], l                     # pieces flowing in from the left
    for ol, orr, other in reversed(left):
        if start - orr <= gap:
            before.append(other)
            start = min(start, ol)
        else:
            break
    wall = next((x[0] for x in right if x[2] not in after), None)

    # Use the PDF's own font when every letter of the new text already appears in it (a subset font has no others):
    # then the new words look exactly like the old ones. Otherwise a standard font that matches as well as possible.
    own_font = bool(original) and bool(key) and set(new) <= seen.get(key, set())
    flagged = False
    if own_font:
        safe = new
        new_obj = raw.FPDFPageObj_CreateTextObj(doc.raw, original, size)
    else:
        safe = new.encode("cp1252", "replace").decode("cp1252")
        flagged = safe != new
        new_obj = raw.FPDFPageObj_NewTextObj(doc.raw, std.encode(), size)
    keep, ptr = _wide(safe)
    raw.FPDFText_SetText(new_obj, ptr)
    raw.FPDFPageObj_SetFillColor(new_obj, cr, cg, cb, ca)
    nl, nb, nr, nt = _bounds(new_obj)
    width = nr - nl
    delta = width - old_width

    limit = max(edge, min(edge + page_width * 0.04, page_width - 28))
    if wall is not None:
        limit = min(limit, wall - 2)
    shrank = 0
    alone = not after and not before

    x = l
    squeeze_alone = False
    if alone and old_width < page_width * 0.5 and abs((l + r) / 2 - page_width / 2) < 2:
        x = page_width / 2 - width / 2        # a short, exactly centred line stays centred
    elif alone and delta > limit - edge and width > 0:
        if size >= 16:                        # headings shrink their type
            scale = max(MIN_SHRINK, (old_width + limit - edge) / width)
            if scale < 1:
                raw.FPDFTextObj_SetFontSize(new_obj, size * scale)
                nl, nb, nr, nt = _bounds(new_obj)
                width, delta = nr - nl, nr - nl - old_width
                shrank = 1
        else:                                 # body text is squeezed sideways, below
            squeeze_alone = True

    for follower in after:
        raw.FPDFPageObj_Transform(follower.raw, 1, 0, 0, 1, delta, 0)
    baseline = m.f if m.f and b - size <= m.f <= t + size else None
    dy = baseline if baseline is not None else b - nb
    raw.FPDFPageObj_Transform(new_obj, 1, 0, 0, 1, x - nl, dy)
    page.remove_obj(obj)
    raw.FPDFPage_InsertObject(page.raw, new_obj)

    new_edge = edge + delta
    if (not alone or squeeze_alone) and new_edge > limit:
        # squeeze the whole line sideways, anchored at its left end
        sx = max(MIN_CONDENSE, (limit - start) / (new_edge - start))
        if sx < 1:
            for piece in [*before, *after]:
                raw.FPDFPageObj_Transform(piece.raw, sx, 0, 0, 1, start * (1 - sx), 0)
            raw.FPDFPageObj_Transform(new_obj, sx, 0, 0, 1, start * (1 - sx), 0)
            shrank = 1
    del keep
    return shrank, flagged


def fill(pdf_bytes: bytes, pairs: list[tuple[str, str]], overrides: dict[int, dict[int, str]] | None = None) -> tuple[bytes, dict]:
    """pairs: [(text as it appears in the sample, new text)]. Returns (new pdf, report).
    overrides: {page: {line number: the exact text that line should have}}, the person's own edits (see list_lines).
    report = {"found": {phrase: times}, "missing": [phrase], "shrunk": n, "unsupported": bool}"""
    if pdfium is None:
        raise RuntimeError("Proposal PDFs are not available on this server yet (the pypdfium2 package is missing).")
    rx, values = _pattern(pairs)
    counts: dict[str, int] = {}
    shrunk = 0
    unsupported = False
    doc = pdfium.PdfDocument(pdf_bytes)
    try:
        overrides = overrides or {}
        if rx is not None or overrides:
            seen: dict[str, set] = {}               # which characters each font in the PDF can draw
            for index in range(len(doc)):
                page = doc[index]
                tp0 = page.get_textpage()
                for ob in page.get_objects(filter=[raw.FPDF_PAGEOBJ_TEXT]):
                    k = _font_key(ob.raw)
                    if k:
                        seen.setdefault(k, set()).update(_object_text(tp0, ob.raw))
                tp0.close()
                ob = None
                page.close()
            for index in range(len(doc)):
                page = doc[index]
                tp = page.get_textpage()
                width = page.get_width()
                items = []
                for obj in page.get_objects(filter=[raw.FPDF_PAGEOBJ_TEXT]):
                    items.append((obj, _object_text(tp, obj.raw)))
                edits = []
                mine = overrides.get(index, {})
                for number, (obj, text) in enumerate(items):
                    if number in mine and mine[number] != text:
                        edits.append((obj, text, mine[number]))      # the person's own wording wins over a swap
                    elif text and rx is not None and rx.search(text):
                        edits.append((obj, text, _swap(text, rx, values, counts)))
                for obj, old, new in edits:
                    made_smaller, flagged = _replace_one(doc, page, obj, new, items, width, seen)
                    shrunk += made_smaller
                    unsupported = unsupported or flagged
                page.gen_content()
                items.clear()
                edits.clear()
                tp.close()
                page.close()
        out = io.BytesIO()
        doc.save(out)
    finally:
        obj = other = tp = page = ob = None   # let go of every page object before the document closes
        gc.collect()
        doc.close()
    found = {k: v for k, v in counts.items()}
    missing = [f.strip() for f, _ in pairs if f and f.strip() and f.strip().lower() not in found]
    return out.getvalue(), {"found": found, "missing": missing, "shrunk": shrunk, "unsupported": unsupported}


def count_phrases(pdf_bytes: bytes, phrases: list[str]) -> dict[str, int]:
    """How many times each phrase appears in the PDF's text (used when the PDF is first uploaded)."""
    _, report = fill(pdf_bytes, [(p, p) for p in phrases])
    return report["found"]


def list_lines(pdf_bytes: bytes, pairs: list[tuple[str, str]]) -> list[dict]:
    """Every piece of text on every page, as it would read after the swaps, so the person can change any of it.
    Returns [{"width", "height", "lines": [{"i": line number, "text", "box": [left, bottom, right, top]}]}].
    A line here is one piece of text in the PDF (usually one printed line); the numbers match fill()'s overrides."""
    if pdfium is None:
        raise RuntimeError("Proposal PDFs are not available on this server yet (the pypdfium2 package is missing).")
    rx, values = _pattern(pairs)
    doc = pdfium.PdfDocument(pdf_bytes)
    pages: list[dict] = []
    try:
        for index in range(len(doc)):
            page = doc[index]
            tp = page.get_textpage()
            lines = []
            for number, obj in enumerate(page.get_objects(filter=[raw.FPDF_PAGEOBJ_TEXT])):
                text = _object_text(tp, obj.raw)
                if not text.strip():
                    continue
                if rx is not None and rx.search(text):
                    text = _swap(text, rx, values, {})
                l, b, r, t = _bounds(obj.raw)
                lines.append({"i": number, "text": text.rstrip(), "box": [round(l, 1), round(b, 1), round(r, 1), round(t, 1)]})
            pages.append({"width": round(page.get_width(), 1), "height": round(page.get_height(), 1), "lines": lines})
            tp.close()
            obj = None
            page.close()
    finally:
        obj = tp = page = None
        gc.collect()
        doc.close()
    return pages


def page_jpeg(pdf_bytes: bytes, number: int, scale: float = 1.3) -> bytes:
    """One page as a picture, for the editor."""
    if pdfium is None:
        raise RuntimeError("Proposal PDFs are not available on this server yet (the pypdfium2 package is missing).")
    doc = pdfium.PdfDocument(pdf_bytes)
    try:
        if not 0 <= number < len(doc):
            raise IndexError("No such page.")
        page = doc[number]
        out = io.BytesIO()
        page.render(scale=scale).to_pil().convert("RGB").save(out, "JPEG", quality=74)
        page.close()
        return out.getvalue()
    finally:
        page = None
        gc.collect()
        doc.close()