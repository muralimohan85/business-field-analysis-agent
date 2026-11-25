"""Outside-in frameworks: PESTLE, Porter's Five Forces, regulatory landscape, technology readiness, scenarios."""

from __future__ import annotations

import re
from collections import defaultdict

from bfa.frameworks.base import (
    Ctx,
    block,
    change_claim,
    confidence,
    dedupe,
    finish,
    judge,
    lower_name,
    quote,
    rank,
    series,
)
from bfa.schemas import Block, Fact, Section, Statement

PESTLE = [
    ("political", "Political"),
    ("economic", "Economic"),
    ("social", "Social"),
    ("technological", "Technological"),
    ("legal", "Legal"),
    ("environmental", "Environmental"),
]


def series_label(f: Fact) -> str:
    m = re.search(r"matching '(.+?)'", f.claim)
    term = m.group(1) if m else ""
    if f.metric == "papers_per_year":
        return f"PubMed papers per year matching '{term}'"
    if f.metric == "works_per_year":
        return f"OpenAlex works per year matching '{term}'"
    if f.metric == "patents_per_year":
        return "US patents granted per year " + f.claim.split(" granted in ")[-1].split(" ", 1)[-1].rstrip(".")
    if f.metric == "trials_started":
        return f"Retrieved studies matching '{term}' starting per year"
    if f.metric == "decisions_per_year":
        return f.claim.split(" in ")[0]
    if " was " in f.claim:
        return f.claim.split(" was ")[0]
    return f.claim.rsplit(" in ", 1)[0]


def summarise_series(ctx: Ctx, facts: list[Fact], topics: list[str]) -> tuple[list[Statement], set[str]]:
    """Replace a run of yearly values with one calculated change statement citing first and last values."""
    stmts, used = [], set()
    for (_metric, _key), run in series(facts).items():
        first, last = run[0], run[-1]
        calc = ctx.add_calc(
            change_claim(first, last, series_label(last), last.unit),
            last.value,
            last.unit,
            [first, last],
            f"change:{last.metric}",
            topics,
            last.year,
        )
        stmts.append(Statement(text=calc.claim, fact_ids=[calc.id, first.id, last.id]))
        used |= {f.id for f in run}
    return stmts, used


def pestle(ctx: Ctx) -> Section:
    sec = Section(framework="pestle", title="PESTLE")
    all_facts = []
    for key, title in PESTLE:
        facts = ctx.by_topic(f"pestle:{key}")
        all_facts += facts
        stmts, used = summarise_series(ctx, facts, [f"pestle:{key}"])
        rest = [f for f in facts if f.id not in used]
        tail = sum(1 for f in rest if f.direction == "tailwind")
        head = sum(1 for f in rest if f.direction == "headwind")
        rating = "Tailwind" if tail > head else "Headwind" if head > tail else ("Mixed" if tail else "")
        b = block(
            key,
            title,
            rest,
            ctx.min_facts,
            limit=5,
            extra=stmts or None,
            rating=rating,
            data={"tailwinds": tail, "headwinds": head},
            gap_hint="Open question for a secondary search or your own data.",
        )
        if not rest and not stmts:
            b.gap = "Not enough evidence: no fact in this run. Open question for a secondary search or your own data."
        sec.blocks.append(b)
    sec.confidence = confidence(all_facts)
    return finish(sec)


def _decisions_by_code(ctx: Ctx) -> dict[str, list[Fact]]:
    out = defaultdict(list)
    for f in ctx.by_metric("decision"):
        m = re.search(r"product code (\w+)", f.claim)
        if m:
            out[m.group(1)].append(f)
    return {k: sorted(v, key=lambda x: x.as_of) for k, v in out.items()}


def _stage_companies(ctx: Ctx) -> dict[str, set[str]]:
    """Companies holding FDA decisions at each value-chain stage, legal-name variants folded together."""
    from bfa.frameworks.base import group_entities

    by_stage = defaultdict(list)
    for f in ctx.by_metric("decision"):
        for t in f.topics:
            if t.startswith("stage:") and f.entity:
                by_stage[t[6:]].append(f)
    everyone = group_entities(ctx.by_metric("decision"), ctx.plan.companies)
    label = {f.id: name for name, fs in everyone.items() for f in fs}
    return {stage: {label.get(f.id, f.entity) for f in fs} for stage, fs in by_stage.items()}


def porter(ctx: Ctx) -> Section:
    sec = Section(framework="porter", title="Porter's Five Forces")
    used: list[Fact] = []
    # threat of new entrants: is there a regulatory route others have already followed?
    entr_stmts, entr_facts = [], ctx.by_topic("porter:entrants")
    for code, decs in _decisions_by_code(ctx).items():
        denovo = next((d for d in decs if "De Novo" in d.claim), None)
        if not denovo:
            continue
        later = [d for d in decs if d.as_of > denovo.as_of]
        k = re.search(r"(DEN\d+)", denovo.claim)
        calc = ctx.add_calc(
            f"Under FDA product code {code}, {len(later)} later decision{'s' if len(later) != 1 else ''} "
            f"followed De Novo {k.group(1) if k else ''} ({denovo.as_of}).",
            float(len(later)),
            "decisions",
            [denovo] + later,
            "decisions_after_denovo",
            ["porter:entrants"],
        )
        entr_stmts.append(Statement(text=calc.claim, fact_ids=[calc.id, denovo.id] + [x.id for x in later[:3]]))
        entr_facts += [denovo] + later
    rating = ""
    if entr_stmts:
        followed = any("0 later" not in s.text for s in entr_stmts)
        rating = "High" if followed else "Medium"
        entr_stmts.insert(
            0,
            judge(
                "Threat of new entrants: device types created by De Novo decisions have been "
                + (
                    "followed by later 510(k) decisions, so later entrants have a predicate route."
                    if followed
                    else "not yet followed by later decisions in this run."
                ),
                [f for f in entr_facts if "De Novo" in f.claim][:3],
            ),
        )
    sec.blocks.append(
        block(
            "entrants",
            "Threat of new entrants",
            entr_facts,
            ctx.min_facts,
            limit=3,
            extra=entr_stmts or None,
            rating=rating,
        )
    )
    used += entr_facts
    # rivalry: how many companies hold decisions at each stage
    stage_names = {s["id"]: s["name"] for s in ctx.plan.stages}
    riv_stmts, riv_facts = [], []
    for stage, companies in sorted(_stage_companies(ctx).items()):
        inputs = [f for f in ctx.by_metric("decision") if f"stage:{stage}" in f.topics]
        names = sorted(companies)
        calc = ctx.add_calc(
            f"FDA decisions at the {lower_name(stage_names.get(stage, stage))} stage come from "
            f"{len(names)} compan{'ies' if len(names) != 1 else 'y'}: {', '.join(names[:8])}"
            f"{' and others' if len(names) > 8 else ''}.",
            float(len(names)),
            "companies",
            inputs,
            "companies_per_stage",
            ["porter:rivalry", f"stage:{stage}"],
        )
        riv_stmts.append(Statement(text=calc.claim, fact_ids=[calc.id] + [f.id for f in inputs[:4]]))
        riv_facts += inputs
    riv_facts += ctx.by_topic("porter:rivalry")
    n_ai = len(_stage_companies(ctx).get("ai", set()))
    riv_rating = ("High" if n_ai >= 6 else "Medium" if n_ai >= 3 else "Low") if riv_stmts else ""
    sec.blocks.append(
        block(
            "rivalry",
            "Rivalry among competitors",
            riv_facts,
            ctx.min_facts,
            limit=3,
            extra=riv_stmts or None,
            rating=riv_rating,
        )
    )
    used += riv_facts
    for key, title, hint in [
        ("buyers", "Bargaining power of buyers", "Needs evidence on lab and hospital buying."),
        ("suppliers", "Bargaining power of suppliers", "Needs evidence on scanner and compute supply."),
        ("substitutes", "Threat of substitutes", "Needs evidence on manual microscopy and other substitutes."),
    ]:
        facts = ctx.by_topic(f"porter:{key}")
        extra = None
        if key == "suppliers":
            scan = sorted(_stage_companies(ctx).get("scanning", set()))
            if scan:
                inputs = [f for f in ctx.by_metric("decision") if "stage:scanning" in f.topics]
                calc = ctx.add_calc(
                    f"{len(scan)} compan{'ies' if len(scan) != 1 else 'y'} hold FDA scanner decisions "
                    f"in this run: {', '.join(scan)}.",
                    float(len(scan)),
                    "companies",
                    inputs,
                    "scanner_makers",
                    ["porter:suppliers"],
                )
                extra = [Statement(text=calc.claim, fact_ids=[calc.id] + [f.id for f in inputs[:4]])]
                facts = facts + inputs
        tail = sum(1 for f in facts if f.direction == "tailwind")
        head = sum(1 for f in facts if f.direction == "headwind")
        r = "" if len(facts) < ctx.min_facts else ("High" if head > tail else "Medium")
        sec.blocks.append(block(key, title, facts, ctx.min_facts, limit=4, extra=extra, rating=r, gap_hint=hint))
        used += facts
    sec.confidence = confidence(used)
    return finish(sec)


def regulatory(ctx: Ctx) -> Section:
    sec = Section(framework="regulatory", title="Regulatory landscape")
    classes = ctx.by_metric("device_class")
    sec.blocks.append(block("device_types", "US device types", classes, 1, limit=10))
    by_code = _decisions_by_code(ctx)
    stmts, facts = [], []
    timeline = []
    for code, decs in sorted(by_code.items()):
        total = next((f for f in ctx.by_metric("decisions_total") if f"code {code}." in f.claim), None)
        if total:
            stmts.append(quote(total))
            facts.append(total)
        stmts.append(quote(decs[0]))
        facts.append(decs[0])
        for d in decs:
            timeline.append({"date": d.as_of, "code": code, "claim": d.claim, "fact": d.id, "company": d.entity})
    sec.blocks.append(
        Block(
            key="decisions",
            title="Decisions by product code",
            statements=stmts,
            data={"timeline": sorted(timeline, key=lambda x: x["date"])},
        )
    )
    totals = ctx.by_metric("recalls_total")
    zero = [f for f in totals if f.value == 0]
    rec = [f for f in totals if f.value] + ctx.by_metric("recall")
    extra = None
    if zero:
        codes = sorted(
            {
                re.search(r"product code (\w+)", f.claim).group(1)
                for f in zero
                if re.search(r"product code (\w+)", f.claim)
            }
        )
        c = ctx.add_calc(
            f"No recall records under FDA product code{'s' if len(codes) > 1 else ''} {', '.join(codes)}.",
            0.0,
            "recalls",
            zero,
            "no_recalls",
            ["regulatory"],
        )
        extra = [Statement(text=c.claim, fact_ids=[c.id] + [f.id for f in zero])]
    rb = block("recalls", "Recalls", rec, 1, limit=6, extra=extra)
    rb.statements = [quote(f) for f in rank(rec)[:6]] + (extra or [])
    sec.blocks.append(rb)
    rec += zero
    other = [f for f in ctx.by_topic("pestle:legal") if not f.source_id.startswith("fda-")]
    sec.blocks.append(
        block(
            "eu_india",
            "EU and India",
            other,
            ctx.min_facts,
            limit=5,
            gap_hint="No primary source on EU IVDR or India CDSCO rules in this run.",
        )
    )
    sec.confidence = confidence(classes + facts + rec + other)
    sec.data["timeline"] = sorted(timeline, key=lambda x: x["date"])
    return finish(sec)


def technology(ctx: Ctx) -> Section:
    sec = Section(framework="technology", title="Technology readiness")
    facts = ctx.by_topic("trend:papers") + ctx.by_topic("trend:patents") + ctx.by_topic("trend:trials")
    stmts, _ = summarise_series(ctx, facts, ["technology"])
    cleared = ctx.by_metric("decision")
    if cleared:
        stmts.append(
            judge(
                f"Products are past research: FDA records in this run include {len(cleared)} market authorisations.",
                cleared[:5],
            )
        )
        ctx.add_calc(
            f"FDA records in this run include {len(cleared)} market authorisations.",
            float(len(cleared)),
            "decisions",
            cleared,
            "authorisations",
            ["technology"],
        )
    b = Block(key="readiness", title="Readiness signals", statements=stmts)
    if not stmts:
        b.gap = "Not enough evidence: no papers, patents, trials or clearances in this run."
    sec.blocks.append(b)
    sec.confidence = confidence(facts + cleared)
    return finish(sec)


def scenarios(ctx: Ctx) -> Section:
    sec = Section(framework="scenarios", title="Scenarios")
    sec.blocks.append(
        Block(
            key="futures",
            title="Four futures",
            gap=(
                "Scenarios need two critical uncertainties chosen from the evidence; the deterministic engine does not "
                "invent them. Run the Claude engine, or name the two uncertainties in your brief."
            ),
        )
    )
    return finish(sec)


def stmt_fact_ids(stmts: list[Statement]) -> list[str]:
    return [i for s in stmts for i in s.fact_ids]


__all__ = [
    "pestle",
    "porter",
    "regulatory",
    "technology",
    "scenarios",
    "summarise_series",
    "series_label",
    "dedupe",
    "rank",
]
