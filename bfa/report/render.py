"""Turn a report into a printable document model with numbered citations, then into Markdown.

Every statement carries footnote numbers; the numbers point to a sources list where each
entry shows the claim's source, its basis (primary or secondary), tier, date and age.
Exports (Word, slides, PDF) are written from this same model, so they cite identically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from bfa.frameworks import TITLES
from bfa.schemas import Report, Statement
from bfa.store import Store

SCOPES = {
    "one_page": ["findings", "market_size", "recommendations", "risks"],
    "decision_brief": [
        "findings",
        "market_size",
        "customers",
        "competitors",
        "opportunity",
        "recommendations",
        "risks",
    ],
    "full": None,
}
BASIS_LABEL = {"primary_only": "Primary only", "primary_secondary": "Primary + secondary"}


@dataclass
class Ref:
    n: int
    fact_id: str
    claim: str
    source: str
    url: str
    publisher: str
    date: str
    basis: str
    tier: str
    kind: str
    flags: list[str] = field(default_factory=list)


@dataclass
class Line:
    text: str
    refs: list[int]
    judgement: bool = False
    confidential: bool = False


@dataclass
class DocBlock:
    title: str
    rating: str = ""
    lines: list[Line] = field(default_factory=list)
    gap: str = ""


@dataclass
class DocSection:
    key: str
    title: str
    confidence: str
    blocks: list[DocBlock] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    data: dict = field(default_factory=dict)


@dataclass
class Doc:
    title: str
    subtitle: str
    banners: list[str]
    verdict: str
    summary: list[Line]
    sections: list[DocSection]
    open_questions: list[str]
    checks: list[dict]
    refs: list[Ref]
    meta: dict


class Cites:
    def __init__(self, store: Store, today: date, flag_after: int, confidential: str):
        self.store, self.today, self.flag_after, self.confidential = store, today, flag_after, confidential
        self.order: dict[str, int] = {}
        self.refs: list[Ref] = []

    def _ref(self, fid: str) -> int | None:
        if fid in self.order:
            return self.order[fid]
        f = self.store.fact(fid)
        if not f:
            return None
        if f.kind == "calculated":
            return None  # the calculator cites its inputs instead
        s = self.store.source(f.source_id)
        flags = []
        year = f.year or (int(f.as_of[:4]) if f.as_of[:4].isdigit() else None)
        if year and year < self.today.year - self.flag_after:
            flags.append(f"older than {self.flag_after} years")
        if f.kind == "upload":
            flags.append("your upload: confidential")
        if f.kind == "user":
            flags.append("your assumption")
        if s and s.fictional:
            flags.append("fictional sample")
        n = len(self.refs) + 1
        self.order[fid] = n
        self.refs.append(
            Ref(
                n=n,
                fact_id=fid,
                claim=f.claim,
                source=s.title if s else f.source_id,
                url=s.url if s else "",
                publisher=s.publisher if s else "",
                date=f.as_of or "",
                basis=f.basis,
                tier=f.tier,
                kind=f.kind,
                flags=flags,
            )
        )
        return n

    def line(self, st: Statement) -> Line | None:
        ids = []
        for fid in st.fact_ids:
            f = self.store.fact(fid)
            if f and f.kind == "calculated":
                ids += f.inputs[:4]
            else:
                ids.append(fid)
        facts = [self.store.fact(i) for i in ids if self.store.fact(i)]
        conf = any(f.kind == "upload" and f.basis == "primary" for f in facts)
        if conf and self.confidential == "remove":
            return None
        refs = sorted({n for i in dict.fromkeys(ids) if (n := self._ref(i))})
        return Line(text=st.text, refs=refs, judgement=st.judgement, confidential=conf)


def build_doc(
    report: Report,
    store: Store,
    scope: str = "full",
    sections: list[str] | None = None,
    confidential: str = "mark",
    flag_after: int = 3,
) -> Doc:
    """confidential: 'mark' keeps statements from your uploads and labels them; 'remove' leaves them out."""
    today = date.fromisoformat(report.created[:10])
    cites = Cites(store, today, flag_after, confidential)
    wanted = sections or SCOPES.get(scope) or list(report.sections)
    summary = [ln for s in report.summary if (ln := cites.line(s))]
    out_sections = []
    removed = 0
    for key in [k for k in report.sections if k in wanted]:
        sec = report.sections[key]
        ds = DocSection(
            key=key,
            title=sec.title or TITLES.get(key, key),
            confidence=sec.confidence,
            open_questions=list(sec.open_questions),
            data=sec.data,
        )
        for b in sec.blocks:
            lines = []
            for st in b.statements:
                ln = cites.line(st)
                if ln is None:
                    removed += 1
                    continue
                lines.append(ln)
            if scope == "one_page":
                lines = lines[:2]
            ds.blocks.append(DocBlock(title=b.title, rating=b.rating, lines=lines, gap=b.gap))
        if scope == "one_page":
            ds.blocks = [b for b in ds.blocks if b.lines][:3]
        out_sections.append(ds)
    banners = [f"Evidence basis: {BASIS_LABEL[report.evidence_basis]}. The model's own knowledge is never a source."]
    if any(store.source(s.id) and s.fictional for s in store.sources()):
        banners.append("Includes fictional sample uploads made for the demo; they are labelled wherever cited.")
    if any(r.kind == "upload" for r in cites.refs) and confidential == "mark":
        banners.append("Confidential: contains statements from your uploaded documents (marked).")
    if removed:
        banners.append(f"{removed} statement(s) from your uploads were left out of this export (confidential).")
    gaps = [q for s in out_sections for q in s.open_questions]
    return Doc(
        title=report.title,
        subtitle=_subtitle(report),
        banners=banners,
        verdict=report.verdict,
        summary=summary,
        sections=out_sections,
        open_questions=list(dict.fromkeys(gaps)),
        checks=[c.model_dump() for c in report.checks],
        refs=cites.refs,
        meta={
            "run_id": report.run_id,
            "created": report.created,
            "scope": scope,
            "geography": ", ".join(report.brief.geography),
            "horizon": report.brief.horizon_years,
            "position": report.brief.position.replace("_", " "),
            "company": report.brief.company,
            "basis": BASIS_LABEL[report.evidence_basis],
        },
    )


def _subtitle(report: Report) -> str:
    b = report.brief
    who = f"{b.company} ({b.position.replace('_', ' ')})" if b.company else b.position.replace("_", " ")
    return f"{', '.join(b.geography)} · {b.horizon_years}-year horizon · seen as {who} · {report.created[:10]}"


def sup(refs: list[int]) -> str:
    return "[" + ",".join(str(r) for r in refs) + "]" if refs else ""


def to_markdown(doc: Doc) -> str:
    md = [f"# {doc.title}", "", f"*{doc.subtitle}*", ""]
    for b in doc.banners:
        md.append(f"> {b}")
    md += ["", f"**Verdict: {doc.verdict}**", "", "## Executive summary", ""]
    md += [f"- {ln.text} {sup(ln.refs)}" for ln in doc.summary]
    for s in doc.sections:
        md += ["", f"## {s.title}", "", f"*Confidence: {s.confidence}*", ""]
        for b in s.blocks:
            head = f"### {b.title}" + (f" ({b.rating})" if b.rating else "")
            md += [head, ""]
            for ln in b.lines:
                tag = "*Judgement:* " if ln.judgement else ""
                conf = " *(confidential)*" if ln.confidential else ""
                md.append(f"- {tag}{ln.text} {sup(ln.refs)}{conf}")
            if b.gap:
                md.append(f"- **Gap:** {b.gap}")
            md.append("")
    if doc.open_questions:
        md += ["## Open questions", ""] + [f"- {q}" for q in doc.open_questions] + [""]
    md += ["## Checks", "", "| Rule | Check | Result | Detail |", "|---|---|---|---|"]
    for c in doc.checks:
        md.append(f"| {c['rule']} | {c['name']} | {'pass' if c['passed'] else 'FAIL'} | {c['detail']} |")
    md += ["", "## Sources", ""]
    for r in doc.refs:
        flags = f" — {', '.join(r.flags)}" if r.flags else ""
        link = f" <{r.url}>" if r.url.startswith("http") else ""
        md.append(
            f"{r.n}. {r.claim} — *{r.source}*, {r.publisher}, {r.date or 'undated'} "
            f"({r.basis}, tier {r.tier}){flags}{link}"
        )
    md += ["", f"Run {doc.meta['run_id']} · {doc.meta['basis']}", ""]
    return "\n".join(md)


__all__ = ["build_doc", "to_markdown", "Doc", "SCOPES", "sup"]
