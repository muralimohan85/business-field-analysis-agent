"""Market size and growth, and trends and signals.

Market size is shown as ranges, never averaged (rule 3). With a primary-only evidence
policy, research-firm estimates (secondary) are left out and the market is sized
bottom-up from primary facts and your stated assumptions, and the report says so.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from bfa.calc import fmt_num, product, value_range
from bfa.frameworks.base import Ctx, block, confidence, dedupe, finish, judge, quote, rank, series
from bfa.frameworks.environment import series_label, summarise_series
from bfa.schemas import Block, Fact, Section, Statement


def assumption_facts(ctx: Ctx) -> dict[str, Fact]:
    """Your assumptions, stored as user facts at the start of the run, keyed by metric."""
    out = {}
    for f in ctx.facts:
        if f.kind == "user" and "assumption" in f.topics and f.metric:
            out[f.metric] = f
    return out


def market_size(ctx: Ctx) -> Section:
    sec = Section(framework="market_size", title="Market size and growth")
    est = [f for f in ctx.by_metric("market_size") if f.value]
    growth = [f for f in ctx.by_metric("growth_rate") if f.value is not None]
    est_stmts = [quote(f) for f in rank(est)[:6]]
    rng = value_range([f.value for f in est])
    if rng and len(est) >= 2:
        c = ctx.add_calc(
            f"Published estimates in this run range from {fmt_num(rng[0], 'USD')} to {fmt_num(rng[1], 'USD')}; "
            f"they are shown side by side, not averaged.",
            rng[1],
            "USD",
            est,
            "estimate_range",
            ["market:estimate"],
        )
        est_stmts.insert(0, Statement(text=c.claim, fact_ids=[c.id] + [f.id for f in est]))
    tam = Block(
        key="tam",
        title="Published estimates (TAM)",
        statements=est_stmts,
        data={
            "estimates": [
                {
                    "fact": f.id,
                    "value": f.value,
                    "year": f.year,
                    "basis": f.basis,
                    "tier": f.tier,
                    "source": f.source_id,
                    "claim": f.claim,
                }
                for f in est
            ]
        },
    )
    if not est:
        tam.gap = (
            (
                "No market-size estimate in this run's evidence. Research-firm estimates are secondary sources: "
                "run a secondary search to see them, labelled."
            )
            if not ctx.include_secondary
            else "No market-size estimate found, even with secondary sources."
        )
    sec.blocks.append(tam)
    # bottom-up check
    a = assumption_facts(ctx)
    labs = rank(ctx.by_metric("labs_count"))
    slides = rank(ctx.by_metric("slides_per_lab"))
    inputs = {
        "Labs in scope": labs[0] if labs else None,
        "Slides per lab per year": slides[0] if slides else None,
        "Share digitised (A1)": a.get("share_digitised"),
        "Share analysed by AI (A2)": a.get("share_ai"),
        "Price per slide (A3)": a.get("price_per_slide"),
    }
    rows = [
        {
            "label": k,
            "fact": v.id if v else "",
            "value": v.value if v else None,
            "unit": v.unit if v else "",
            "assumption": bool(v and v.kind == "user"),
        }
        for k, v in inputs.items()
    ]
    bu = Block(key="bottom_up", title="Bottom-up check (SAM)", data={"inputs": rows})
    missing = [k for k, v in inputs.items() if v is None]
    if missing:
        bu.gap = f"Bottom-up figure not computed: no fact for {', '.join(missing)}."
    else:
        vals = [
            inputs["Labs in scope"].value,
            inputs["Slides per lab per year"].value,
            inputs["Share digitised (A1)"].value / 100,
            inputs["Share analysed by AI (A2)"].value / 100,
            inputs["Price per slide (A3)"].value,
        ]
        sam = product(vals)
        used = list(inputs.values())
        c = ctx.add_calc(
            f"Bottom-up SAM: {fmt_num(vals[0])} labs × {fmt_num(vals[1])} slides × "
            f"{fmt_num(inputs['Share digitised (A1)'].value)}% digitised × "
            f"{fmt_num(inputs['Share analysed by AI (A2)'].value)}% analysed by AI × "
            f"{fmt_num(vals[4], 'USD')} per slide = {fmt_num(sam, 'USD')} a year.",
            sam,
            "USD",
            used,
            "sam_bottom_up",
            ["market:bottom_up"],
        )
        bu.statements.append(Statement(text=c.claim, fact_ids=[c.id] + [f.id for f in used]))
        bu.data["sam"] = sam
        if a.get("reachable_share"):
            som = sam * a["reachable_share"].value / 100
            c2 = ctx.add_calc(
                f"SOM at a reachable share of {fmt_num(a['reachable_share'].value)}% (assumption A4) "
                f"is {fmt_num(som, 'USD')} a year.",
                som,
                "USD",
                [c, a["reachable_share"]],
                "som",
                ["market:bottom_up"],
            )
            bu.statements.append(Statement(text=c2.claim, fact_ids=[c2.id, c.id, a["reachable_share"].id]))
            bu.data["som"] = som
    sec.blocks.append(bu)
    # growth
    g_stmts = [quote(f) for f in rank(growth)[:4]]
    grng = value_range([f.value for f in growth])
    if grng and len(growth) >= 2:
        c = ctx.add_calc(
            f"Stated growth rates in this run range from {grng[0]:.1f}% to {grng[1]:.1f}% a year.",
            grng[1],
            "%",
            growth,
            "growth_range",
            ["market:growth"],
        )
        g_stmts.insert(0, Statement(text=c.claim, fact_ids=[c.id] + [f.id for f in growth]))
    gb = Block(key="growth", title="Growth", statements=g_stmts)
    if not growth:
        gb.gap = "No stated growth rate in this run; see Trends for counted momentum."
    sec.blocks.append(gb)
    rev = ctx.by_metric("company_revenue")
    sec.blocks.append(
        block(
            "filings",
            "Listed players' revenue (company level, not the segment)",
            rev,
            1,
            limit=6,
            gap_hint="No filings in this run.",
        )
    )
    # drivers and brakes from other evidence
    tail = rank([f for f in ctx.facts if f.direction == "tailwind" and any(t.startswith("pestle:") for t in f.topics)])
    head = rank([f for f in ctx.facts if f.direction == "headwind"])
    sec.blocks.append(block("drivers", "Drivers", tail, 1, limit=4, gap_hint="No tailwind evidence."))
    sec.blocks.append(block("brakes", "Brakes", head, 1, limit=4, gap_hint="No headwind evidence."))
    sec.data["basis"] = "primary_secondary" if ctx.include_secondary else "primary_only"
    sec.confidence = confidence(est + growth + rev + [v for v in inputs.values() if v])
    if not est and missing:
        sec.confidence = "low"
    return finish(sec)


def decisions_per_year(ctx: Ctx) -> list[Fact]:
    decs = ctx.by_metric("decision")
    by_year = defaultdict(list)
    for d in decs:
        if d.year:
            by_year[d.year].append(d)
    out = []
    for y in sorted(by_year):
        if y >= ctx.today.year:  # a year in progress is not compared with full years
            ctx.add_calc(
                f"FDA decisions in this run's product codes in {y} to date ({ctx.today.isoformat()}): "
                f"{len(by_year[y])}.",
                float(len(by_year[y])),
                "decisions",
                by_year[y],
                "decisions_ytd",
                ["trend:decisions"],
                y,
            )
            continue
        out.append(
            ctx.add_calc(
                f"FDA decisions in this run's product codes in {y}: {len(by_year[y])}.",
                float(len(by_year[y])),
                "decisions",
                by_year[y],
                "decisions_per_year",
                ["trend:decisions"],
                y,
            )
        )
    return out


def trends(ctx: Ctx) -> Section:
    sec = Section(framework="trends", title="Trends and signals")
    groups = [
        ("papers", "Papers", ctx.by_topic("trend:papers")),
        ("patents", "Patents", ctx.by_topic("trend:patents")),
        ("trials", "Trials", [f for f in ctx.by_topic("trend:trials") if f.year]),
        ("decisions", "Regulatory decisions", decisions_per_year(ctx)),
        ("news", "News", ctx.by_topic("trend:news")),
    ]
    chart = {}
    used = []
    for key, title, facts in groups:
        stmts, _ = summarise_series(ctx, [f for f in facts if f.metric != "works_by_institution"], [f"trend:{key}"])
        for (_m, _k), run in series(facts).items():
            chart[series_label(run[-1])] = [{"year": f.year, "value": f.value, "fact": f.id} for f in run]
            if len(run) >= 3:
                jumps = [(run[i].value - run[i - 1].value, run[i]) for i in range(1, len(run))]
                best = max(jumps, key=lambda x: x[0])
                if best[0] > 0:
                    prev = run[run.index(best[1]) - 1]
                    lab = series_label(best[1])
                    lab = lab if lab[1:2].isupper() else lab[:1].lower() + lab[1:]
                    c = ctx.add_calc(
                        f"The largest one-year rise in {lab} "
                        f"was in {best[1].year}: from {fmt_num(prev.value)} to {fmt_num(best[1].value)}.",
                        best[0],
                        best[1].unit,
                        [prev, best[1]],
                        "largest_rise",
                        [f"trend:{key}"],
                        best[1].year,
                    )
                    stmts.append(Statement(text=c.claim, fact_ids=[c.id, prev.id, best[1].id]))
        if key == "decisions":
            ytd = [f for f in ctx.by_metric("decisions_ytd")]
            stmts += [quote(f) for f in ytd]
        extra_facts = [f for f in facts if f.year is None and f.metric not in ("decisions_total",)]
        if key == "news":
            extra_facts = facts
        b = block(
            key,
            title,
            extra_facts,
            ctx.min_facts,
            limit=4,
            extra=stmts or None,
            gap_hint="No counted series for this signal in this run.",
        )
        if not stmts and not extra_facts:
            b.gap = "No evidence for this signal in this run."
        sec.blocks.append(b)
        used += facts
    inst = ctx.by_metric("works_by_institution") + ctx.by_metric("trials_by_sponsor")
    if inst:
        sec.blocks.append(block("concentration", "Where the work is concentrated", inst, 1, limit=6))
    sec.data["chart"] = chart
    sec.confidence = confidence(used)
    return finish(sec)


def counts_by_kind(facts: list[Fact]) -> Counter:
    return Counter(f.kind for f in dedupe(facts))


__all__ = ["market_size", "trends", "assumption_facts", "counts_by_kind", "judge"]
