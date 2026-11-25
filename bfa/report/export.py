"""Exports: Word (.docx), slides (.pptx), PDF, Markdown, and an Excel evidence pack.

All are written from the same document model (render.build_doc), so a statement carries
the same footnote numbers everywhere. Export is refused while a locked check fails.
"""

from __future__ import annotations

from pathlib import Path

from bfa.checks import locked_failures
from bfa.report.charts import make_charts
from bfa.report.render import Doc, build_doc, sup, to_markdown
from bfa.schemas import Report
from bfa.store import Store

INK = (0x19, 0x19, 0x19)
MUTED = (0x66, 0x66, 0x66)
ACCENT = (0x25, 0x7D, 0xE0)
GAP = (0xB4, 0x5F, 0x06)
FORMATS = ("docx", "pptx", "pdf", "md", "xlsx")


class ExportBlocked(RuntimeError):
    pass


def export(
    report: Report,
    store: Store,
    fmt: str,
    out: Path,
    scope: str = "full",
    sections: list[str] | None = None,
    confidential: str = "mark",
    flag_after: int = 3,
) -> Path:
    bad = locked_failures(report.checks)
    if bad:
        raise ExportBlocked("Export refused: locked check(s) failed: " + ", ".join(c.name for c in bad))
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = build_doc(report, store, scope, sections, confidential, flag_after)
    charts = make_charts(report.sections, out.parent / "charts") if fmt in ("docx", "pptx", "pdf") else {}
    if fmt == "md":
        out.write_text(to_markdown(doc))
    elif fmt == "docx":
        to_docx(doc, out, charts)
    elif fmt == "pptx":
        to_pptx(doc, out, charts)
    elif fmt == "pdf":
        to_pdf(doc, out, charts)
    elif fmt == "xlsx":
        to_xlsx(report, store, doc, out)
    else:
        raise ValueError(f"unknown format {fmt}; use one of {', '.join(FORMATS)}")
    return out


# --------------------------------------------------------------------------- Word
def to_docx(doc: Doc, path: Path, charts: dict) -> None:
    import docx
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Inches, Pt, RGBColor

    d = docx.Document()
    st = d.styles["Normal"]
    st.font.name, st.font.size = "Calibri", Pt(11)
    for sec in d.sections:
        sec.left_margin = sec.right_margin = Inches(0.9)

    def para(text, size=11, color=INK, bold=False, italic=False, style=None):
        p = d.add_paragraph(style=style)
        r = p.add_run(text)
        r.font.size, r.font.bold, r.font.italic = Pt(size), bold, italic
        r.font.color.rgb = RGBColor(*color)
        return p

    def line(ln, style="List Bullet"):
        p = d.add_paragraph(style=style)
        if ln.judgement:
            r = p.add_run("Judgement: ")
            r.italic = True
            r.font.color.rgb = RGBColor(*MUTED)
        p.add_run(ln.text + " ")
        r = p.add_run(sup(ln.refs))
        r.font.superscript = True
        r.font.color.rgb = RGBColor(*ACCENT)
        if ln.confidential:
            r = p.add_run(" (confidential)")
            r.font.size = Pt(9)
            r.font.color.rgb = RGBColor(*MUTED)

    d.add_heading(doc.title, 0)
    para(doc.subtitle, 10, MUTED, italic=True)
    for b in doc.banners:
        para(b, 9, MUTED)
    para(f"Verdict: {doc.verdict}", 13, ACCENT, bold=True)
    d.add_heading("Executive summary", 1)
    for ln in doc.summary:
        line(ln)
    for s in doc.sections:
        d.add_heading(s.title, 1)
        para(f"Confidence: {s.confidence}", 9, MUTED, italic=True)
        if s.key in charts:
            d.add_picture(str(charts[s.key]), width=Inches(5.8))
            d.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.LEFT
        for b in s.blocks:
            d.add_heading(b.title + (f" ({b.rating})" if b.rating else ""), 2)
            for ln in b.lines:
                line(ln)
            if b.gap:
                para("Gap: " + b.gap, 10, GAP, italic=True)
    if doc.open_questions:
        d.add_heading("Open questions", 1)
        for q in doc.open_questions:
            d.add_paragraph(q, style="List Bullet")
    d.add_heading("Checks", 1)
    t = d.add_table(rows=1, cols=4)
    t.style = "Light List Accent 1"
    for i, h in enumerate(("Rule", "Check", "Result", "Detail")):
        t.rows[0].cells[i].text = h
    for c in doc.checks:
        row = t.add_row().cells
        row[0].text, row[1].text = str(c["rule"]), c["name"]
        row[2].text, row[3].text = ("pass" if c["passed"] else "FAIL"), c["detail"]
    d.add_heading("Sources", 1)
    for r in doc.refs:
        p = d.add_paragraph()
        p.paragraph_format.space_after = Pt(2)
        run = p.add_run(f"{r.n}. ")
        run.bold = True
        p.add_run(f"{r.claim} ").font.size = Pt(9)
        meta = f"{r.source}; {r.publisher}; {r.date or 'undated'}; {r.basis}, tier {r.tier}"
        meta += (f"; {', '.join(r.flags)}" if r.flags else "") + (f"; {r.url}" if r.url.startswith("http") else "")
        m = p.add_run(meta)
        m.font.size = Pt(8)
        m.font.color.rgb = RGBColor(*MUTED)
    para(f"Run {doc.meta['run_id']} · {doc.meta['basis']} · scope {doc.meta['scope']}", 8, MUTED)
    d.core_properties.title = doc.title
    d.core_properties.comments = " ".join(doc.banners)
    d.save(str(path))


# --------------------------------------------------------------------------- Slides
def to_pptx(doc: Doc, path: Path, charts: dict) -> None:
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.util import Emu, Inches, Pt

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    blank = prs.slide_layouts[6]

    def box(slide, x, y, w, h, text, size=14, color=INK, bold=False):
        tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        tf = tb.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        r = p.add_run()
        r.text = text
        r.font.size, r.font.bold = Pt(size), bold
        r.font.color.rgb = RGBColor(*color)
        return tf

    def bullets(tf, lines, size=13, max_lines=6):
        for ln in lines[:max_lines]:
            p = tf.add_paragraph()
            p.space_before = Pt(6)
            r = p.add_run()
            text = ln.text if len(ln.text) < 230 else ln.text[:227] + "..."
            r.text = ("Judgement: " if ln.judgement else "") + text + " "
            r.font.size = Pt(size)
            r.font.color.rgb = RGBColor(*INK)
            c = p.add_run()
            c.text = sup(ln.refs)
            c.font.size = Pt(size - 3)
            c.font.color.rgb = RGBColor(*ACCENT)

    def slide(title, kicker=""):
        s = prs.slides.add_slide(blank)
        bar = s.shapes.add_shape(1, 0, 0, prs.slide_width, Emu(Inches(0.12)))
        bar.fill.solid()
        bar.fill.fore_color.rgb = RGBColor(*ACCENT)
        bar.line.fill.background()
        box(s, 0.6, 0.35, 12, 0.8, title, 28, INK, True)
        if kicker:
            box(s, 0.6, 1.05, 12, 0.5, kicker, 12, MUTED)
        foot = box(
            s,
            0.6,
            7.0,
            12.2,
            0.4,
            f"{doc.meta['basis']} · numbers in brackets are sources (last slides) · run {doc.meta['run_id']}",
            9,
            MUTED,
        )
        return s, foot

    s, _ = slide(doc.title, doc.subtitle)
    tf = box(s, 0.6, 1.8, 12, 1, f"Verdict: {doc.verdict}", 24, ACCENT, True)
    for b in doc.banners:
        p = tf.add_paragraph()
        r = p.add_run()
        r.text = b
        r.font.size = Pt(12)
        r.font.color.rgb = RGBColor(*MUTED)

    s, _ = slide("Executive summary")
    bullets(box(s, 0.6, 1.4, 12, 5.4, "", 4), doc.summary, 15, 7)

    for sec in doc.sections:
        blocks = [b for b in sec.blocks if b.lines]
        if not blocks and not any(b.gap for b in sec.blocks):
            continue
        s, _ = slide(sec.title, f"Confidence: {sec.confidence}")
        if sec.key in charts:
            s.shapes.add_picture(str(charts[sec.key]), Inches(7.2), Inches(1.6), width=Inches(5.6))
            width = 6.3
        else:
            width = 12
        tf = box(s, 0.6, 1.5, width, 5.3, "", 4)
        shown = 0
        for b in blocks[:4]:
            p = tf.add_paragraph()
            p.space_before = Pt(10)
            r = p.add_run()
            r.text = b.title + (f"  ·  {b.rating}" if b.rating else "")
            r.font.size, r.font.bold = Pt(14), True
            r.font.color.rgb = RGBColor(*INK)
            bullets(tf, b.lines, 12, 2 if len(blocks) > 2 else 3)
            shown += 1
        gaps = [b.title for b in sec.blocks if b.gap]
        if gaps:
            p = tf.add_paragraph()
            p.space_before = Pt(10)
            r = p.add_run()
            r.text = "Gaps (not enough evidence): " + ", ".join(gaps[:6])
            r.font.size = Pt(11)
            r.font.color.rgb = RGBColor(*GAP)

    s, _ = slide("Checks", "Ten rules, recorded for this run")
    tf = box(s, 0.6, 1.5, 12, 5.3, "", 4)
    for c in doc.checks:
        p = tf.add_paragraph()
        r = p.add_run()
        r.text = f"{'✓' if c['passed'] else '✗'}  Rule {c['rule']} · {c['name']}: {c['detail']}"
        r.font.size = Pt(12)
        r.font.color.rgb = RGBColor(*(INK if c["passed"] else GAP))

    per = 14
    for i in range(0, len(doc.refs), per):
        s, _ = slide("Sources" + (f" ({i // per + 1})" if len(doc.refs) > per else ""))
        tf = box(s, 0.6, 1.3, 12.2, 5.6, "", 4)
        for r_ in doc.refs[i : i + per]:
            p = tf.add_paragraph()
            r = p.add_run()
            claim = r_.claim if len(r_.claim) < 120 else r_.claim[:117] + "..."
            r.text = f"{r_.n}. {claim} — {r_.publisher}, {r_.date or 'undated'} ({r_.basis}, tier {r_.tier})" + (
                f"; {', '.join(r_.flags)}" if r_.flags else ""
            )
            r.font.size = Pt(10)
            r.font.color.rgb = RGBColor(*INK)
    prs.core_properties.title = doc.title
    prs.save(str(path))


# --------------------------------------------------------------------------- PDF
def to_pdf(doc: Doc, path: Path, charts: dict) -> None:
    from xml.sax.saxutils import escape

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        Image,
        ListFlowable,
        ListItem,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    ss = getSampleStyleSheet()
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=10, leading=13.5)
    small = ParagraphStyle("s", parent=body, fontSize=8, leading=10.5, textColor=colors.HexColor("#666666"))
    gap = ParagraphStyle("g", parent=body, textColor=colors.HexColor("#b45f06"), fontName="Helvetica-Oblique")
    hex_accent = "#257de0"

    def ln_para(ln):
        tag = "<i>Judgement:</i> " if ln.judgement else ""
        conf = " <font size=7 color='#666666'>(confidential)</font>" if ln.confidential else ""
        return Paragraph(
            f"{tag}{escape(ln.text)} <super><font color='{hex_accent}'>{sup(ln.refs)}</font></super>{conf}", body
        )

    def items(lines):
        return ListFlowable(
            [ListItem(ln_para(x), leftIndent=10) for x in lines], bulletType="bullet", start="•", leftIndent=12
        )

    story = [Paragraph(escape(doc.title), ss["Title"]), Paragraph(escape(doc.subtitle), small), Spacer(1, 4)]
    story += [Paragraph(escape(b), small) for b in doc.banners]
    story += [
        Spacer(1, 6),
        Paragraph(f"<font color='{hex_accent}'><b>Verdict: {escape(doc.verdict)}</b></font>", ss["Heading2"]),
        Paragraph("Executive summary", ss["Heading1"]),
        items(doc.summary),
    ]
    for s in doc.sections:
        story += [Paragraph(escape(s.title), ss["Heading1"]), Paragraph(f"Confidence: {s.confidence}", small)]
        if s.key in charts:
            story.append(Image(str(charts[s.key]), width=160 * mm, height=160 * mm * _ratio(charts[s.key])))
        for b in s.blocks:
            story.append(Paragraph(escape(b.title + (f" ({b.rating})" if b.rating else "")), ss["Heading3"]))
            if b.lines:
                story.append(items(b.lines))
            if b.gap:
                story.append(Paragraph("Gap: " + escape(b.gap), gap))
    if doc.open_questions:
        story += [
            Paragraph("Open questions", ss["Heading1"]),
            ListFlowable([ListItem(Paragraph(escape(q), body)) for q in doc.open_questions], bulletType="bullet"),
        ]
    story.append(Paragraph("Checks", ss["Heading1"]))
    rows = [["Rule", "Check", "Result", "Detail"]] + [
        [str(c["rule"]), c["name"], "pass" if c["passed"] else "FAIL", Paragraph(escape(c["detail"]), small)]
        for c in doc.checks
    ]
    t = Table(rows, colWidths=[12 * mm, 25 * mm, 14 * mm, 120 * mm])
    t.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#666666")),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#cccccc")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story += [t, Paragraph("Sources", ss["Heading1"])]
    for r in doc.refs:
        meta = f"{r.source}; {r.publisher}; {r.date or 'undated'}; {r.basis}, tier {r.tier}"
        meta += (f"; {', '.join(r.flags)}" if r.flags else "") + (f"; {r.url}" if r.url.startswith("http") else "")
        story.append(Paragraph(f"<b>{r.n}.</b> {escape(r.claim)} <font color='#666666'>{escape(meta)}</font>", small))

    def footer(canvas, d):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#666666"))
        canvas.drawString(18 * mm, 10 * mm, f"{doc.meta['basis']} · run {doc.meta['run_id']}")
        canvas.drawRightString(192 * mm, 10 * mm, f"page {d.page}")
        canvas.restoreState()

    SimpleDocTemplate(
        str(path),
        pagesize=A4,
        title=doc.title,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
    ).build(story, onFirstPage=footer, onLaterPages=footer)


def _ratio(p: Path) -> float:
    from PIL import Image as PI

    with PI.open(p) as im:
        return im.height / im.width


# --------------------------------------------------------------------------- Excel evidence pack
def to_xlsx(report: Report, store: Store, doc: Doc, path: Path) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Statements"
    ws.append(["Section", "Block", "Statement", "Judgement", "Fact ids", "Source numbers"])
    for sec in report.sections.values():
        for b in sec.blocks:
            for s in b.statements:
                ws.append([sec.title, b.title, s.text, "yes" if s.judgement else "", ", ".join(s.fact_ids), ""])
            if b.gap:
                ws.append([sec.title, b.title, "GAP: " + b.gap, "", "", ""])
    fs = wb.create_sheet("Facts")
    fs.append(
        [
            "Fact id",
            "Claim",
            "Entity",
            "Metric",
            "Value",
            "Unit",
            "Year",
            "Basis",
            "Tier",
            "Kind",
            "Source id",
            "In scope",
            "Scope note",
            "Inputs (calculated)",
        ]
    )
    for f in store.facts(in_scope=None):
        fs.append(
            [
                f.id,
                f.claim,
                f.entity,
                f.metric,
                f.value,
                f.unit,
                f.year,
                f.basis,
                f.tier,
                f.kind,
                f.source_id,
                "yes" if f.in_scope else "set aside",
                f.scope_note,
                ", ".join(f.inputs),
            ]
        )
    ss = wb.create_sheet("Sources")
    ss.append(
        [
            "Source id",
            "Title",
            "Publisher",
            "URL",
            "Published",
            "Fetched",
            "Basis",
            "Tier",
            "Kind",
            "Quarantined sentences",
            "Fictional",
        ]
    )
    for s in store.sources():
        ss.append(
            [
                s.id,
                s.title,
                s.publisher,
                s.url,
                s.published,
                s.fetched,
                s.basis,
                s.tier,
                s.kind,
                " | ".join(s.quarantined),
                "yes" if s.fictional else "",
            ]
        )
    cs = wb.create_sheet("Checks")
    cs.append(["Rule", "Check", "Passed", "Detail"])
    for c in report.checks:
        cs.append([c.rule, c.name, c.passed, c.detail])
    bs = wb.create_sheet("Blocked queries")
    bs.append(["Connector", "Query", "Question", "Reason", "At"])
    for b in store.blocked():
        bs.append([b.connector, b.text, b.question_id, b.reason, b.at])
    for sheet in wb.worksheets:
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        sheet.freeze_panes = "A2"
        for col in sheet.columns:
            width = min(80, max(10, max(len(str(c.value or "")) for c in col[:200]) + 2))
            sheet.column_dimensions[col[0].column_letter].width = width
    wb.save(str(path))


__all__ = ["export", "ExportBlocked", "FORMATS"]
