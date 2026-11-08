"""Reading a proposal PDF into text. No database or network."""
import io

import pytest

pytest.importorskip("pypdf")
reportlab = pytest.importorskip("reportlab")

from reportlab.pdfgen import canvas

from omnimodel import pdf_template


def make_pdf(pages, encrypt=None):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, encrypt=encrypt) if encrypt else canvas.Canvas(buf)
    for lines in pages:
        y = 800
        for line in lines:
            c.drawString(50, y, line)
            y -= 16
        c.showPage()
    c.save()
    return buf.getvalue()


BODY = ["Proposal for Acme Ltd", "Prepared by Shield Security", "We will provide guarding for your site in Accra."]


def test_text_is_extracted_in_order():
    out = pdf_template.extract_text(make_pdf([BODY]))
    assert out["pages"] == 1 and not out["truncated"]
    assert out["text"].splitlines()[0] == "Proposal for Acme Ltd"
    assert "guarding for your site in Accra" in out["text"]


def test_letterhead_and_page_numbers_are_dropped():
    pages = [["SHIELD SECURITY LTD", f"Section {i}", f"Body text number {i} that is long enough to count.", f"Page {i + 1}"] for i in range(3)]
    text = pdf_template.extract_text(make_pdf(pages))["text"]
    assert "SHIELD SECURITY LTD" not in text and "Page 2" not in text
    assert "Section 1" in text


def test_not_a_pdf_and_empty_and_oversize():
    for bad in (b"", b"hello this is text, not a pdf at all", b"%PDF-" + b"0" * (pdf_template.MAX_BYTES + 1)):
        with pytest.raises(pdf_template.PdfProblem):
            pdf_template.extract_text(bad)


def test_pdf_with_no_text_is_explained():
    with pytest.raises(pdf_template.PdfProblem, match="no text"):
        pdf_template.extract_text(make_pdf([[]]))


def test_damaged_pdf_gives_a_plain_message():
    with pytest.raises(pdf_template.PdfProblem, match="damaged|could not read"):
        pdf_template.extract_text(b"%PDF-1.4\n1 0 obj\n<<garbage")


def test_password_protected_pdf_is_refused():
    from reportlab.lib import pdfencrypt
    locked = make_pdf([BODY], encrypt=pdfencrypt.StandardEncryption("secret", canPrint=1))
    with pytest.raises(pdf_template.PdfProblem, match="password"):
        pdf_template.extract_text(locked)


def test_wrapped_lines_are_joined_into_paragraphs_but_headings_and_bullets_stay_apart():
    full = "This is a long line of text that fills the whole width of the page and so it wraps on to the next"
    lines = ["ABOUT US", full, "line of the very same paragraph and then it ends here.", full, "second paragraph carries on a bit more.",
             "• First point is a list item that fits on one line only", "• Second point is another list item", "Thank you."]
    text = pdf_template.reflow(lines)
    assert text.startswith("ABOUT US\n" + full + " line of the very same paragraph")
    assert "\n\n" in text and "• First point is a list item that fits on one line only\n• Second point" in text
    assert text.endswith("Thank you.")