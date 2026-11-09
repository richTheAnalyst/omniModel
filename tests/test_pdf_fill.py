"""Filling a proposal PDF. The first group needs no database; the storage tests need TEST_DATABASE_URL."""
import base64
import io
import zipfile

import pytest

pypdfium2 = pytest.importorskip("pypdfium2")
reportlab = pytest.importorskip("reportlab")
from reportlab.pdfgen import canvas

from omnimodel import pdf_fill


def sample() -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.setFont("Helvetica-Bold", 22)
    c.drawString(40, 780, "Proposal for Acme Ltd")
    c.setFont("Helvetica", 11)
    c.drawString(40, 740, "Prepared for Acme Ltd, Accra")
    c.drawString(40, 720, "Thank you. Shield Security will provide Manned guarding.")
    c.rect(40, 600, 200, 60)                                   # stands in for a table / logo
    c.drawString(50, 630, "Contact: 024 123 4567  hi@shield.example")
    c.showPage()
    c.save()
    return buf.getvalue()


def text_of(pdf: bytes) -> str:
    doc = pypdfium2.PdfDocument(pdf)
    try:
        page = doc[0]
        tp = page.get_textpage()
        out = tp.get_text_range()
        tp.close()
        page.close()
        return out
    finally:
        doc.close()


PAIRS = [("Acme Ltd", "Kofi Engineering"), ("Accra", "Kumasi"), ("Shield Security", "Guardian"), ("Manned guarding", "CCTV installation"),
         ("024 123 4567", "020 999 8888"), ("hi@shield.example", "a@guardian.example")]


def test_details_are_swapped_and_the_old_ones_are_really_gone():
    out, report = pdf_fill.fill(sample(), PAIRS)
    text = text_of(out)
    for old in ("Acme", "Accra", "Shield", "Manned", "024 123", "hi@shield"):
        assert old not in text                              # removed from the file, not just covered up
    for new in ("Kofi Engineering", "Kumasi", "Guardian", "CCTV installation", "020 999 8888", "a@guardian.example"):
        assert new in text
    assert report["missing"] == [] and report["found"]["acme ltd"] == 2


def test_the_rest_of_the_page_is_kept():
    out, _ = pdf_fill.fill(sample(), PAIRS)
    doc = pypdfium2.PdfDocument(out)
    try:
        page = doc[0]
        kinds = [o.type for o in page.get_objects()]
        assert pypdfium2.raw.FPDF_PAGEOBJ_PATH in kinds     # the drawn box is still there
        page.close()
    finally:
        doc.close()


def test_details_not_in_the_pdf_are_reported_missing():
    _, report = pdf_fill.fill(sample(), [("Nobody Inc", "X"), ("Acme Ltd", "Y")])
    assert report["missing"] == ["Nobody Inc"]


def test_matching_ignores_capitals_and_a_long_name_does_not_leave_the_page():
    out, report = pdf_fill.fill(sample(), [("ACME LTD", "A Very Long Company Name Of Ghana Engineering And Sons Limited")])
    assert "A Very Long Company Name" in text_of(out) and report["shrunk"] >= 1


def test_characters_a_standard_font_cannot_draw_are_flagged():
    _, report = pdf_fill.fill(sample(), [("Acme Ltd", "Ɛkow Ltd")])
    assert report["unsupported"] is True


def test_an_empty_value_removes_the_old_text():
    out, _ = pdf_fill.fill(sample(), [("Accra", "")])
    assert "Accra" not in text_of(out)


def test_no_pairs_changes_nothing():
    out, report = pdf_fill.fill(sample(), [])
    assert text_of(out).startswith("Proposal for Acme Ltd") and report["found"] == {}


# ------------------------------------------------------------------ with a database
from omnimodel import proposal_pdf, tracking
from omnimodel.proposal_pdf import RenderIn, TemplateIn

B64 = lambda b: base64.b64encode(b).decode()
REPS = [{"find": "Acme Ltd", "as": "company"}, {"find": "Accra", "as": "city"}, {"find": "Shield Security", "as": "our_name"}]


def upload(ctx, **kw):
    body = dict(filename="mine.pdf", data=B64(sample()), replacements=REPS)
    body.update(kw)
    return proposal_pdf.save_template(ctx, TemplateIn(**body))


def test_upload_then_fill_for_a_company(member):
    ctx = member("pt")
    assert proposal_pdf.get_template(ctx)["template"] is None
    res = upload(ctx)
    assert res["missing"] == [] and res["template"]["filename"] == "mine.pdf"
    out = proposal_pdf.render(ctx, RenderIn(company="Kofi Ltd", city="Tema", business={"our_name": "Guardian"}))
    text = text_of(out)
    assert "Kofi Ltd" in text and "Tema" in text and "Guardian" in text and "Acme" not in text


def test_uploading_again_replaces_it(member):
    ctx = member("pt2")
    upload(ctx)
    upload(ctx, filename="second.pdf")
    assert proposal_pdf.get_template(ctx)["template"]["filename"] == "second.pdf"


def test_a_pdf_with_none_of_the_details_is_refused(member):
    with pytest.raises(tracking.BadInput, match="nothing to fill in"):
        upload(member("pt3"), replacements=[{"find": "Not in here", "as": "company"}])


def test_not_a_pdf_is_refused(member):
    with pytest.raises(tracking.BadInput):
        upload(member("pt4"), data=B64(b"just text, not a pdf"))


def test_other_businesses_cannot_see_or_use_it(member):
    mine, theirs = member("pt5"), member("pt6")
    upload(mine)
    assert proposal_pdf.get_template(theirs)["template"] is None
    with pytest.raises(tracking.NotFound):
        proposal_pdf.render(theirs, RenderIn(company="X"))


def test_many_proposals_come_back_as_a_zip(member):
    ctx = member("pt7")
    upload(ctx)
    blob = proposal_pdf.render_many(ctx, [RenderIn(company="One Ltd"), RenderIn(company="One Ltd"), RenderIn(company="Two/Three")])
    names = zipfile.ZipFile(io.BytesIO(blob)).namelist()
    assert len(names) == 3 and len(set(names)) == 3 and all(n.endswith(".pdf") for n in names)
    with pytest.raises(tracking.BadInput):
        proposal_pdf.render_many(ctx, [])


def test_delete(member):
    ctx = member("pt8")
    upload(ctx)
    proposal_pdf.delete_template(ctx)
    assert proposal_pdf.get_template(ctx)["template"] is None


# ------------------------------------------------------------------ editing the design in the app
def test_lines_are_listed_as_they_will_read_and_an_edit_replaces_just_that_line():
    pages = pdf_fill.list_lines(sample(), PAIRS)
    lines = {ln["text"]: ln["i"] for ln in pages[0]["lines"]}
    assert "Proposal for Kofi Engineering" in lines                       # the swaps already show
    number = next(i for t, i in lines.items() if t.startswith("Prepared for"))
    out, _ = pdf_fill.fill(sample(), PAIRS, {0: {number: "Prepared for the board of Kofi Engineering"}})
    text = text_of(out)
    assert "Prepared for the board of Kofi Engineering" in text and "Prepared for Kofi Engineering," not in text
    assert "Proposal for Kofi Engineering" in text                         # other lines are untouched


def test_an_edit_can_clear_a_line_and_page_pictures_come_out():
    pages = pdf_fill.list_lines(sample(), [])
    number = next(ln["i"] for ln in pages[0]["lines"] if ln["text"].startswith("Thank you"))
    out, _ = pdf_fill.fill(sample(), [], {0: {number: ""}})
    assert "Thank you" not in text_of(out)
    assert pdf_fill.page_jpeg(sample(), 0)[:2] == b"\xff\xd8"
    with pytest.raises(IndexError):
        pdf_fill.page_jpeg(sample(), 5)


def test_edits_through_the_stored_template(member):
    ctx = member("ed1")
    upload(ctx)
    req = RenderIn(company="Kofi Ltd", city="Tema")
    pages = proposal_pdf.lines(ctx, req)["pages"]
    number = next(ln["i"] for ln in pages[0]["lines"] if ln["text"].startswith("Prepared for"))
    out = proposal_pdf.render(ctx, RenderIn(company="Kofi Ltd", city="Tema", overrides={"0": {str(number): "Prepared for Kofi Ltd (final)"}}))
    assert "Prepared for Kofi Ltd (final)" in text_of(out)
    img = proposal_pdf.page_image(ctx, proposal_pdf.PageIn(company="Kofi Ltd", page=0))
    assert img[:2] == b"\xff\xd8"
    with pytest.raises(tracking.NotFound):
        proposal_pdf.page_image(ctx, proposal_pdf.PageIn(page=9))
    with pytest.raises(tracking.BadInput):
        proposal_pdf.render(ctx, RenderIn(overrides={"x": {"1": "a"}}))