"""Who is in the field: customer segments and needs, value chain and channels, competitors, business model canvas."""

from __future__ import annotations

from bfa.frameworks.base import (
    Ctx,
    block,
    confidence,
    dedupe,
    finish,
    group_entities,
    judge,
    lower_name,
    norm_company,
    quote,
    rank,
)
from bfa.frameworks.market import assumption_facts
from bfa.schemas import Block, Fact, Section, Statement

NEEDS = [("customers:need", "Needs"), ("customers:pain", "Pains"), ("customers:criteria", "Buying criteria")]


def customers(ctx: Ctx) -> Section:
    sec = Section(framework="customers", title="Customer segments and needs")
    pool = dedupe(
        ctx.by_topic("customers")
        + ctx.by_topic("porter:buyers")
        + ctx.by_topic("segment")
        + ctx.by_metric("labs_count")
        + ctx.by_metric("trials_by_sponsor")
        + ctx.by_metric("pathologists_count")
    )
    heat, used = {}, []
    for seg in ctx.plan.segments:
        facts = ctx.mentioning(seg["terms"], pool) + ctx.by_topic(f"segment:{seg['id']}")
        facts = dedupe(facts)
        used += facts
        sec.blocks.append(
            block(
                f"seg_{seg['id']}",
                seg["name"],
                facts,
                ctx.min_facts,
                limit=4,
                rating=f"{len(facts)} facts",
                data={"segment": seg["id"]},
                gap_hint="Size, needs and buying process need more evidence.",
            )
        )
        heat[seg["name"]] = {
            label: len([f for f in facts if any(t == topic for t in f.topics)]) for topic, label in NEEDS
        }
    for topic, label in NEEDS:
        facts = ctx.by_topic(topic)
        used += facts
        sec.blocks.append(block(topic.split(":")[1], f"{label} across segments", facts, ctx.min_facts, limit=5))
    if not ctx.plan.segments:
        sec.open_questions.append("No segments are defined for this field; add them to the brief or a domain pack.")
    sec.data["heatmap"] = heat
    sec.confidence = confidence(used)
    return finish(sec)


def stage_companies(ctx: Ctx) -> dict[str, list[Fact]]:
    out: dict[str, list[Fact]] = {}
    for f in ctx.by_metric("decision"):
        for t in f.topics:
            if t.startswith("stage:"):
                out.setdefault(t[6:], []).append(f)
    return out


def value_chain(ctx: Ctx) -> Section:
    sec = Section(framework="value_chain", title="Value chain and channels")
    by_stage = stage_companies(ctx)
    stages_data, used = [], []
    for st in ctx.plan.stages:
        decs = by_stage.get(st["id"], [])
        names = sorted({norm_company(f.entity) for f in decs if f.entity})
        extra = []
        if names:
            c = ctx.add_calc(
                f"Companies with FDA decisions at the {lower_name(st['name'])} stage in this run: {', '.join(names)}.",
                float(len(names)),
                "companies",
                decs,
                "stage_players",
                [f"stage:{st['id']}", "value_chain"],
            )
            extra.append(Statement(text=c.claim, fact_ids=[c.id] + [f.id for f in decs[:4]]))
        other = [f for f in ctx.mentioning(st["terms"]) if f.metric != "decision" and f.kind != "calculated"]
        used += decs + other
        sec.blocks.append(
            block(
                f"stage_{st['id']}",
                st["name"],
                other,
                ctx.min_facts,
                limit=3,
                extra=extra or None,
                data={"players": names},
            )
        )
        stages_data.append({"id": st["id"], "name": st["name"], "players": names, "evidence": len(decs) + len(other)})
    ch = ctx.by_topic("channel")
    used += ch
    sec.blocks.append(
        block(
            "channels",
            "Channels to market",
            ch,
            ctx.min_facts,
            limit=6,
            gap_hint="No evidence on how products reach buyers (partners, marketplaces, distributors).",
        )
    )
    pairings = [
        f
        for f in ctx.facts
        if "scanner" in f.claim.lower()
        and f.metric in ("decision", "")
        and ("algorithm" in f.claim.lower() or "ai" in f.claim.lower().split())
    ]
    sec.blocks.append(
        block(
            "control",
            "Control points",
            pairings,
            ctx.min_facts,
            limit=3,
            gap_hint="No evidence on which pairings of scanner, viewer and AI control access.",
        )
    )
    if not ctx.plan.stages:
        sec.open_questions.append("No value-chain stages are defined for this field; add them to a domain pack.")
    sec.data["stages"] = stages_data
    sec.confidence = confidence(used)
    return finish(sec)


def competitors(ctx: Ctx) -> Section:
    sec = Section(framework="competitors", title="Competitor analysis")
    pool = [
        f
        for f in ctx.facts
        if f.entity
        and (
            "competitor" in f.topics
            or f.metric in ("decision", "company_revenue", "patents_by_assignee", "trials_by_sponsor", "recall")
        )
    ]
    groups = group_entities(pool, ctx.brief.competitors)
    accepted = set(ctx.store.get("accepted_companies", []))
    order = sorted(groups, key=lambda k: (k not in ctx.brief.competitors, -len(groups[k]), k))
    rows, used = [], []
    for name in order[:14]:
        facts = rank(groups[name])
        used += facts
        decs = [f for f in facts if f.metric == "decision"]
        codes = sorted({c for f in decs for c in [f.claim.split("product code ")[-1].rstrip(").")]})
        pat = next((f for f in facts if f.metric == "patents_by_assignee"), None)
        tri = next((f for f in facts if f.metric == "trials_by_sponsor"), None)
        rev = max((f for f in facts if f.metric == "company_revenue"), key=lambda f: f.year or 0, default=None)
        moves = sorted((f for f in facts if f.as_of), key=lambda f: f.as_of, reverse=True)
        rows.append(
            {
                "company": name,
                "known": name in ctx.brief.competitors,
                "new": name not in ctx.brief.competitors and name not in accepted,
                "decisions": len(decs),
                "codes": codes,
                "patents": pat.value if pat else None,
                "trials": tri.value if tri else None,
                "revenue": rev.value if rev else None,
                "latest": moves[0].claim if moves else "",
                "latest_date": moves[0].as_of if moves else "",
                "facts": [f.id for f in facts],
            }
        )
        stmts = [quote(f) for f in (decs[:1] + ([rev] if rev else []) + ([pat] if pat else []))[:3]] or [
            quote(f) for f in facts[:2]
        ]
        sec.blocks.append(
            Block(key=f"co_{len(rows)}", title=name, statements=stmts, rating="new" if rows[-1]["new"] else "")
        )
    for name in ctx.brief.competitors:
        if name not in groups:
            rows.append(
                {
                    "company": name,
                    "known": True,
                    "new": False,
                    "decisions": 0,
                    "codes": [],
                    "patents": None,
                    "trials": None,
                    "revenue": None,
                    "latest": "",
                    "latest_date": "",
                    "facts": [],
                }
            )
            sec.blocks.append(
                Block(
                    key=f"co_{len(rows)}", title=name, gap="No record for this company in this run's primary sources."
                )
            )
    moves = sorted(
        [f for f in ctx.by_topic("competitor:move") if f.as_of and f.entity and f.entity != "FDA"],
        key=lambda f: f.as_of,
        reverse=True,
    )
    sec.blocks.append(
        Block(
            key="moves",
            title="Moves timeline",
            statements=[quote(f) for f in moves[:10]],
            gap="" if moves else "No dated moves in this run.",
        )
    )
    if rows:
        n = len([r for r in rows if r["facts"]])
        c = ctx.add_calc(
            f"{n} companies have records in this run's sources.",
            float(n),
            "companies",
            [f for r in rows for f in pool if f.id in r["facts"][:1]],
            "companies_found",
            ["competitor"],
        )
        sec.blocks.insert(
            0,
            Block(
                key="overview", title="Overview", statements=[Statement(text=c.claim, fact_ids=[c.id] + c.inputs[:6])]
            ),
        )
    sec.data["matrix"] = rows
    sec.confidence = confidence(used)
    return finish(sec)


def bmc(ctx: Ctx) -> Section:
    sec = Section(framework="bmc", title="Business model canvas")
    a = assumption_facts(ctx)
    segs = [
        b
        for b in ctx.sections.get("customers", Section(framework="", title="")).blocks
        if b.key.startswith("seg_") and b.statements
    ]
    seg_stmts = [s for b in segs for s in b.statements[:1]]
    own = [f for f in ctx.all_facts if "capability" in f.topics]  # your own capability data, if uploaded
    blocks = [
        ("segments", "Customer segments", [], seg_stmts),
        ("value", "Value propositions", ctx.by_topic("customers:need") + ctx.by_topic("customers:pain"), None),
        ("channels", "Channels", ctx.by_topic("channel") + ctx.by_topic("bmc:channels"), None),
        ("relationships", "Customer relationships", ctx.by_topic("bmc:relationships"), None),
        (
            "revenue",
            "Revenue streams",
            ctx.by_topic("bmc:revenue") + ([a["price_per_slide"]] if "price_per_slide" in a else []),
            None,
        ),
        (
            "resources",
            "Key resources",
            [f for f in own if f.direction != "headwind"] + ctx.by_metric("device_class")[:2],
            None,
        ),
        (
            "activities",
            "Key activities",
            ctx.mentioning(["validation", "clinical study", "regulatory submission"]),
            None,
        ),
        ("partners", "Key partners", ctx.by_topic("bmc:partners") + ctx.by_topic("channel:partner"), None),
        (
            "costs",
            "Cost structure",
            ctx.by_topic("bmc:costs") + [f for f in own if "bmc:costs" in f.topics or "pestle:economic" in f.topics],
            None,
        ),
    ]
    used = []
    for key, title, facts, extra in blocks:
        used += facts
        b = block(
            key,
            title,
            facts,
            1,
            limit=3,
            extra=extra or None,
            gap_hint="No evidence in this run; the canvas leaves this block open.",
        )
        if not facts and not extra:
            b.gap = "No evidence in this run; the canvas leaves this block open."
        sec.blocks.append(b)
    sec.confidence = confidence(used)
    return finish(sec)


__all__ = ["customers", "value_chain", "competitors", "bmc", "judge"]
