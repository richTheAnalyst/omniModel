"""A business's own proposal PDF, kept as a template and filled in for each new company (see pdf_fill.py)."""
from __future__ import annotations

import base64
import binascii
import io
import re
import zipfile
from typing import Literal

from pydantic import BaseModel, Field

from . import db, pdf_fill, pdf_template
from .tracking import BadInput, Ctx, Forbidden, NotFound, _jsonb

Placeholder = Literal["company", "city", "offering_label", "our_name", "our_email", "our_phone", "our_title"]
MAX_BATCH = 50


class Replace(BaseModel):
    find: str = Field(min_length=2, max_length=200)          # the text as it appears in the sample PDF
    as_: Placeholder = Field(alias="as")                     # what it stands for

    model_config = {"populate_by_name": True}


class TemplateIn(BaseModel):
    filename: str = Field(default="proposal.pdf", max_length=200)
    data: str = Field(min_length=1, max_length=8_000_000)    # the PDF, base64 encoded
    replacements: list[Replace] = Field(min_length=1, max_length=20)


class RenderIn(BaseModel):
    company: str = Field(default="", max_length=300)
    city: str = Field(default="", max_length=200)
    offering_label: str = Field(default="", max_length=200)
    business: dict[str, str] = Field(default_factory=dict)   # our_name, our_email, our_phone, our_title
    # The person's own edits to the design: {page number: {line number: new text}} (see pdf_fill.list_lines).
    overrides: dict[str, dict[str, str]] = Field(default_factory=dict)


class PageIn(RenderIn):
    page: int = Field(default=0, ge=0, le=200)


def _decode(data: str) -> bytes:
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        raise BadInput("The file could not be read. Try again.")
    if len(raw) > pdf_template.MAX_BYTES:
        raise BadInput(f"That PDF is larger than {pdf_template.MAX_BYTES // (1024 * 1024)} MB. Export a smaller copy.")
    if raw.lstrip()[:5] != b"%PDF-":
        raise BadInput("That file is not a PDF.")
    return raw


def _pairs(replacements: list[dict], req: RenderIn) -> list[tuple[str, str]]:
    values = {"company": req.company, "city": req.city, "offering_label": req.offering_label}
    for key in ("our_name", "our_email", "our_phone", "our_title"):
        values[key] = str(req.business.get(key, "") or "")
    # An empty value removes the old text rather than leaving a previous client's details in the new proposal.
    return [(r["find"], values.get(r["as"], "")) for r in replacements]


def _overrides(req: RenderIn) -> dict[int, dict[int, str]]:
    out: dict[int, dict[int, str]] = {}
    total = 0
    for page, lines in req.overrides.items():
        try:
            p = int(page)
        except ValueError:
            raise BadInput("An edit refers to a page that does not exist.")
        for number, text in lines.items():
            try:
                n = int(number)
            except ValueError:
                raise BadInput("An edit refers to a line that does not exist.")
            if len(text) > 2000:
                raise BadInput("One edited line is too long.")
            out.setdefault(p, {})[n] = text
            total += 1
    if total > 800:
        raise BadInput("Too many edited lines.")
    return out


def save_template(ctx: Ctx, body: TemplateIn) -> dict:
    if ctx.role not in ("owner", "admin"):
        raise Forbidden("Only an owner or admin can change the proposal template.")
    raw = _decode(body.data)
    finds = [r.find.strip() for r in body.replacements]
    try:
        found = pdf_fill.count_phrases(raw, finds)
    except Exception:
        raise BadInput("We could not read that PDF. It may be damaged; try saving it again from the original.")
    if not found:
        raise BadInput("None of those details appear as text in the PDF, so there is nothing to fill in. "
                       "Check the spelling, or export the PDF from Word or Google Docs instead of scanning it.")
    reps = [{"find": r.find.strip(), "as": r.as_} for r in body.replacements]
    with db.connection() as conn:
        conn.execute(
            """insert into proposal_templates (workspace_id, filename, pdf, size_bytes, replacements, uploaded_by)
               values (%s::uuid, %s, %s, %s, %s::jsonb, %s::uuid)
               on conflict (workspace_id) do update set filename = excluded.filename, pdf = excluded.pdf,
                 size_bytes = excluded.size_bytes, replacements = excluded.replacements,
                 uploaded_by = excluded.uploaded_by, uploaded_at = now()""",
            (ctx.workspace_id, body.filename.strip() or "proposal.pdf", raw, len(raw), _jsonb(reps), ctx.user_id),
        )
    try:                                            # the same words as editable text, for the Proposal tab in Create outreach
        text = pdf_template.extract_text(raw)["text"]
    except Exception:                               # an image-only PDF has none; the designed PDF still works
        text = None
    return {"template": get_template(ctx)["template"], "text": text,
            "found": {f: found.get(f.lower(), 0) for f in finds},
            "missing": [f for f in finds if f.lower() not in found]}


def get_template(ctx: Ctx) -> dict:
    with db.connection() as conn:
        row = conn.execute(
            "select filename, size_bytes, replacements, uploaded_at from proposal_templates where workspace_id = %s::uuid",
            (ctx.workspace_id,),
        ).fetchone()
    if not row:
        return {"template": None}
    return {"template": {"filename": row["filename"], "size_bytes": row["size_bytes"],
                         "replacements": row["replacements"], "uploaded_at": row["uploaded_at"].isoformat()}}


def delete_template(ctx: Ctx) -> dict:
    if ctx.role not in ("owner", "admin"):
        raise Forbidden("Only an owner or admin can change the proposal template.")
    with db.connection() as conn:
        conn.execute("delete from proposal_templates where workspace_id = %s::uuid", (ctx.workspace_id,))
    return {"ok": True}


def _stored(ctx: Ctx) -> tuple[bytes, list[dict]]:
    with db.connection() as conn:
        row = conn.execute("select pdf, replacements from proposal_templates where workspace_id = %s::uuid",
                           (ctx.workspace_id,)).fetchone()
    if not row:
        raise NotFound("No proposal template has been uploaded yet.")
    return bytes(row["pdf"]), row["replacements"]


def render(ctx: Ctx, req: RenderIn) -> bytes:
    pdf, reps = _stored(ctx)
    out, _ = pdf_fill.fill(pdf, _pairs(reps, req), _overrides(req))
    return out


def lines(ctx: Ctx, req: RenderIn) -> dict:
    """The text on every page, as it will read for this company, for the editor."""
    pdf, reps = _stored(ctx)
    return {"pages": pdf_fill.list_lines(pdf, _pairs(reps, req))}


def page_image(ctx: Ctx, req: PageIn) -> bytes:
    """One page as it will look for this company, with the person's edits so far."""
    pdf, reps = _stored(ctx)
    out, _ = pdf_fill.fill(pdf, _pairs(reps, req), _overrides(req))
    try:
        return pdf_fill.page_jpeg(out, req.page)
    except IndexError:
        raise NotFound("That page does not exist.")


def _safe_name(text: str, used: set[str]) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._") or "proposal"
    base = base[:60]
    name, n = base, 2
    while name.lower() in used:
        name, n = f"{base}_{n}", n + 1
    used.add(name.lower())
    return name + ".pdf"


def render_many(ctx: Ctx, items: list[RenderIn]) -> bytes:
    if not items:
        raise BadInput("Choose at least one company.")
    if len(items) > MAX_BATCH:
        raise BadInput(f"Up to {MAX_BATCH} proposals at a time.")
    pdf, reps = _stored(ctx)
    buf, used = io.BytesIO(), set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for req in items:
            out, _ = pdf_fill.fill(pdf, _pairs(reps, req))
            z.writestr(_safe_name(f"Proposal_{req.company}", used), out)
    return buf.getvalue()