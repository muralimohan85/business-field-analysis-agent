"""Your documents: PDF, Word, PowerPoint, Excel, CSV and text, read on your machine.

Each upload is marked by you as your own primary data (interviews, sales, surveys) or a
third-party report (secondary). Its sentences become candidate facts with the same
citation rules as any other source, tagged confidential, with instruction-like text
quarantined first.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

from bfa.governance.scope import mentions
from bfa.safety.sanitizer import clean, sentences
from bfa.schemas import Fact, Source, now_iso, short_hash
from bfa.taxonomy import market_metrics, tag

SUPPORTED = {".pdf", ".pptx", ".xlsx", ".xlsm", ".docx", ".csv", ".txt", ".md"}
_CUES = re.compile(
    r"market|revenue|growth|cagr|price|per slide|per case|labs?\b|laborator|pathologist|adoption|share|"
    r"segment|customer|hospital|reimburse|partner|channel|cost",
    re.I,
)


@dataclass
class Passage:
    where: str
    text: str


@dataclass
class Parsed:
    name: str
    passages: list[Passage] = field(default_factory=list)
    quarantined: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(p.text for p in self.passages)


def parse(path: str | Path) -> Parsed:
    p = Path(path)
    ext = p.suffix.lower()
    if ext not in SUPPORTED:
        raise ValueError(f"unsupported file type {ext}; use one of {', '.join(sorted(SUPPORTED))}")
    raw: list[Passage] = []
    if ext == ".pdf":
        import pdfplumber

        with pdfplumber.open(p) as pdf:
            raw = [Passage(f"page {i}", pg.extract_text() or "") for i, pg in enumerate(pdf.pages, 1)]
    elif ext == ".pptx":
        from pptx import Presentation

        for i, slide in enumerate(Presentation(p).slides, 1):
            txt = [sh.text_frame.text for sh in slide.shapes if getattr(sh, "has_text_frame", False)]
            raw.append(Passage(f"slide {i}", "\n".join(txt)))
    elif ext in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook

        wb = load_workbook(p, read_only=True, data_only=True)
        for ws in wb.worksheets:
            for r, row in enumerate(ws.iter_rows(values_only=True), 1):
                cells = [str(c) for c in row if c not in (None, "")]
                if cells:
                    raw.append(Passage(f"sheet {ws.title} row {r}", " | ".join(cells)))
    elif ext == ".docx":
        import docx

        raw = [
            Passage(f"paragraph {i}", para.text)
            for i, para in enumerate(docx.Document(p).paragraphs, 1)
            if para.text.strip()
        ]
    elif ext == ".csv":
        with open(p, newline="", encoding="utf-8", errors="replace") as fh:
            raw = [Passage(f"row {i}", " | ".join(row)) for i, row in enumerate(csv.reader(fh), 1) if any(row)]
    else:
        raw = [Passage("text", p.read_text(encoding="utf-8", errors="replace"))]
    out = Parsed(name=p.name)
    for ps in raw:
        c = clean(_join_lines(ps.text))
        out.quarantined += c.quarantined
        if c.text.strip():
            out.passages.append(Passage(ps.where, c.text))
    return out


def _join_lines(text: str) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    out: list[str] = []
    for i, ln in enumerate(lines):
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        heading = len(ln) < 60 and not re.search(r"[.!?:;,]$", ln) and (not nxt or nxt[:1].isupper())
        out.append(ln + ("." if heading and not ln.endswith(".") else ""))
    return " ".join(out)


def to_evidence(
    parsed: Parsed,
    basis: str,
    scope_terms: list[str],
    fictional: bool = False,
    extra_topics: dict[str, list[str]] | None = None,
) -> tuple[Source, list[Fact]]:
    """basis: 'primary' for your own data, 'secondary' for a third-party report."""
    sid = "upload-" + short_hash(parsed.name, 8)
    src = Source(
        id=sid,
        connector="uploads",
        basis=basis,
        tier="U",
        kind="upload",
        title=parsed.name,
        url=f"upload://{parsed.name}",
        publisher="your upload",
        fetched=now_iso(),
        text=parsed.text[:20000],
        quarantined=parsed.quarantined,
        fictional=fictional,
    )
    facts = []
    for ps in parsed.passages:
        for s in sentences(ps.text):
            if len(s) < 25 or len(s.split()) < 7 or not (_CUES.search(s) or mentions(s, scope_terms)):
                continue
            topics, direction = tag(s, extra_topics)
            m = market_metrics(s)
            facts.append(
                Fact(
                    id=f"UP-{short_hash([sid, s], 8)}",
                    source_id=sid,
                    claim=s,
                    basis=basis,
                    tier="U",
                    kind="upload",
                    location=ps.where,
                    topics=topics + ["upload"],
                    direction=direction,
                    as_of=src.fetched[:10],
                    **m,
                )
            )
    return src, facts
