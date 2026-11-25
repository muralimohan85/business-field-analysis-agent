"""Synthesis: key findings, SWOT, opportunity landscape, recommendations, risks and assumptions, executive summary.

A key finding is a pattern: at least N facts from M kinds of source (rule 4). Below that
it is shown as a signal to watch. Scores and recommendations are judgements; each cites
the facts it rests on, and every number in them comes from the calculator.
"""

from __future__ import annotations

import re

from bfa.calc import fmt_num
from bfa.frameworks.base import Ctx, block, confidence, dedupe, finish, judge, lower_name, norm_company, quote, rank
from bfa.frameworks.market import assumption_facts
from bfa.schemas import Block, Fact, Finding, Section, Statement

THEMES = {
    "regulatory": (
        "Regulatory records define who can enter and how",
        "Plan the route against existing device types and decisions before building.",
    ),
    "pestle:legal": (
        "Rules shape the route to market",
        "Regulatory work sits on the critical path; budget for it early.",
    ),
    "trend:decisions": (
        "Regulatory decisions are accumulating",
        "Each clearance by another company creates both a predicate and a competitor.",
    ),
    "trend:papers": (
        "Research output is a leading signal",
        "Follow where the research concentrates for partners and talent.",
    ),
    "trend:patents": (
        "Patent activity marks where companies are investing",
        "Check freedom to operate before committing.",
    ),
    "trend:trials": (
        "Clinical studies are testing the technology",
        "Trial sponsors are candidate partners and rivals.",
    ),
    "competitor": ("Several companies already hold positions", "Entry needs a clear angle against named incumbents."),
    "competitor:move": ("Competitors are moving", "Track these moves; they change the opportunity landscape."),
    "risk": ("Risks show up in the records", "Build mitigations into the plan, not after it."),
    "pestle:economic": ("Economics are a swing factor", "Test willingness to pay before sizing the business."),
    "pestle:social": (
        "Workforce and demographic pressure is documented",
        "Lead with relief for the people doing the work.",
    ),
    "pestle:technological": (
        "Technology is moving fast",
        "Differentiate on data, validation and workflow, not on the model alone.",
    ),
    "customers:pain": ("Buyers' pains are documented", "Anchor the value proposition on these pains."),
    "customers:need": ("Buyer needs are stated in the sources", "Match the offer to the stated needs."),
    "channel": ("Routes to market run through partners", "Choose a channel partner early."),
    "market:estimate": ("Market estimates exist but differ", "Plan on a working range, not on a headline number."),
    "porter:rivalry": (
        "Rivalry is concentrated in a few companies per stage",
        "Pick a stage where a mid-size player can stand out, or partner at the crowded ones.",
    ),
    "porter:buyers": ("Buyers set the terms", "Design pricing and integration around how labs buy."),
    "porter:suppliers": (
        "Scanner vendors control access to the lab",
        "Treat scanner vendors as channel partners first.",
    ),
    "porter:entrants": ("The route for new entrants is documented", "Use existing device types as predicates."),
    "customers:criteria": ("Buying criteria are clear", "Validation, integration and price per slide decide deals."),
    "pestle:political": ("Public programmes shape demand", "Track funding programmes in each target country."),
    "bmc:revenue": ("Buyers prefer recurring pricing", "Offer a subscription or a price per slide."),
    "channel:distributor": ("Distribution runs through vendors and resellers", "Choose a distribution partner early."),
}
KIND_NAMES = {
    "regulator": "regulator records",
    "upload": "your documents",
    "paper": "papers",
    "patent": "patents",
    "trial": "trial registries",
    "statistics": "official statistics",
    "filing": "company filings",
    "news": "news",
    "web": "web pages",
    "official": "official pages",
}
GENERIC = {"upload", "assumption", "market:revenue", "ecosystem", "value_chain", "technology"}


def _kinds(facts: list[Fact]) -> list[str]:
    return sorted({f.kind for f in facts if f.kind != "calculated"})


def findings(ctx: Ctx) -> tuple[list[Finding], Section]:
    mn, mk = ctx.cfg.evidence.finding_min_facts, ctx.cfg.evidence.finding_min_kinds
    base = [f for f in ctx.facts if f.kind not in ("calculated", "user") and "capability" not in f.topics]
    themes = sorted(
        {t for f in base for t in f.topics if t not in GENERIC and not t.startswith(("stage:", "segment:"))}
    )
    found, signals = [], []
    for t in themes:
        facts = rank(dedupe([f for f in base if t in f.topics]))
        kinds = _kinds(facts)
        title, sowhat = THEMES.get(
            t, (f"Evidence clusters around {t.replace(':', ' ')}", "Review the facts behind it.")
        )
        tier_a = sum(1 for f in facts if f.tier in ("A", "U")) / max(len(facts), 1)
        if len(facts) >= mn and len(kinds) >= mk:
            strength = "strong" if len(facts) >= 2 * mn and len(kinds) >= mk and tier_a >= 0.6 else "moderate"
            found.append((strength, len(facts), t, title, sowhat, facts, kinds))
        elif facts:
            signals.append(("signal", len(facts), t, title, sowhat, facts, kinds))
    found.sort(key=lambda x: (x[0] != "strong", -x[1]))
    signals.sort(key=lambda x: -x[1])
    chosen, sets = [], []
    for item in found + signals:
        ids = {f.id for f in item[5]}
        if any(len(ids & s) / max(len(ids | s), 1) >= 0.5 for s in sets):
            continue  # same evidence as a finding already chosen
        sets.append(ids)
        chosen.append(item)
    chosen = [c for c in chosen if c[0] != "signal"][:8] + [c for c in chosen if c[0] == "signal"][:4]
    out, support = [], {}
    for i, (strength, _count, t, title, sowhat, facts, kinds) in enumerate(chosen, 1):
        every = facts
        facts = _mix(facts, 8)
        names = ", ".join(KIND_NAMES.get(k, k) for k in kinds)
        support[f"K{i}"] = ctx.add_calc(
            f"{_n(len(every), 'fact')} from {_n(len(kinds), 'kind')} of source ({names}) support this pattern.",
            float(len(every)),
            "facts",
            every,
            "finding_support",
            [t],
        )
        major = (
            "tailwind"
            if sum(f.direction == "tailwind" for f in facts) >= sum(f.direction == "headwind" for f in facts)
            else "headwind"
        )
        counter = [f.id for f in facts if f.direction not in (major, "neutral")]
        feeds = sorted({k for k, s in ctx.sections.items() if s.fact_ids() & {f.id for f in facts}})
        out.append(
            Finding(
                id=f"K{i}",
                title=title,
                sowhat=sowhat,
                strength=strength,
                fact_ids=[f.id for f in facts[:8]],
                source_kinds=kinds,
                counter=counter[:4],
                feeds=feeds,
                theme=t,
            )
        )
    sec = Section(framework="findings", title="Key findings and patterns")
    for k in out:
        facts = [ctx.store.fact(i) for i in k.fact_ids]
        sec.blocks.append(
            Block(
                key=k.id,
                title=k.title,
                rating=k.strength,
                statements=[
                    judge(f"{k.title}. {k.sowhat}", facts[:4]),
                    Statement(text=support[k.id].claim, fact_ids=[support[k.id].id] + k.fact_ids[:4]),
                ]
                + [quote(f) for f in facts[:3]],
                data={"kinds": k.source_kinds, "theme": k.theme, "support": support[k.id].id},
            )
        )
    if not found:
        sec.open_questions.append(
            f"No pattern reaches {mn} facts from {mk} kinds of source in this run; "
            "signals are listed instead. Add sources or run a secondary search."
        )
    sec.confidence = "high" if sum(k.strength == "strong" for k in out) >= 2 else "medium" if found else "low"
    return out, finish(sec)


def _section_of(ctx: Ctx, fid: str) -> list[str]:
    return [k for k, s in ctx.sections.items() if fid in s.fact_ids()]


def _n(count: int, word: str, plural: str = "") -> str:
    return f"{count} {word if count == 1 else (plural or word + 's')}"


def _mix(facts: list[Fact], n: int) -> list[Fact]:
    """Round-robin across kinds of source, so one database cannot crowd out the rest."""
    by_kind: dict[str, list[Fact]] = {}
    for f in facts:
        by_kind.setdefault(f.kind, []).append(f)
    out, i = [], 0
    while len(out) < n and any(i < len(v) for v in by_kind.values()):
        for v in by_kind.values():
            if i < len(v) and len(out) < n:
                out.append(v[i])
        i += 1
    return out


def swot(ctx: Ctx) -> Section:
    subject = ctx.brief.company or "a new entrant"
    sec = Section(framework="swot", title=f"SWOT for {subject}")
    # Strengths and weaknesses describe the subject: only facts about it count (its own data, or naming it).
    about = [
        f
        for f in ctx.all_facts
        if f.kind not in ("calculated", "user")
        and (
            "capability" in f.topics
            or (
                ctx.brief.company
                and ctx.brief.company.lower() in (f.entity + " " + f.claim).lower()
                and f.kind != "upload"
            )
        )
    ]
    s_facts = rank([f for f in about if f.direction != "headwind"])
    w_facts = rank([f for f in about if f.direction == "headwind"])
    hint = (
        "Strengths and weaknesses need evidence about the subject: upload your own capability data marked as "
        "primary, or name your company in the brief."
    )
    # Opportunities and threats describe the field.
    riv = ctx.sections.get("porter")
    riv_stmts = [s for b in (riv.blocks if riv else []) if b.key == "rivalry" for s in b.statements[:1]]
    about_ids = {f.id for f in about}
    head = rank(
        [
            f
            for f in ctx.facts
            if f.direction == "headwind"
            and f.kind not in ("calculated", "user")
            and f.id not in about_ids
            and not (f.value == 0 and f.metric.endswith("_total"))
        ]
    )
    threat_ids = {i for s in riv_stmts for i in s.fact_ids} | {f.id for f in head[:4]}
    tail = rank(
        [
            f
            for f in ctx.facts
            if f.direction == "tailwind"
            and f.kind not in ("calculated", "user")
            and f.id not in about_ids
            and f.id not in threat_ids
        ]
    )
    o_pick, t_pick = _mix(tail, 4), _mix(head, 4)
    traces = {f.id: _section_of(ctx, f.id) or ["evidence"] for f in o_pick + t_pick + s_facts[:4] + w_facts[:4]}
    sec.blocks.append(block("strengths", "Strengths", s_facts, 1, limit=4, gap_hint=hint))
    sec.blocks.append(block("weaknesses", "Weaknesses", w_facts, 1, limit=4, gap_hint=hint))
    ob = block("opportunities", "Opportunities", o_pick, ctx.min_facts, limit=4)
    ob.statements = [quote(f) for f in o_pick]
    tb = block("threats", "Threats", t_pick, ctx.min_facts, limit=4, extra=riv_stmts or None)
    tb.statements = (riv_stmts or []) + [quote(f) for f in t_pick]
    sec.blocks += [ob, tb]
    for b in sec.blocks:
        if b.gap and b.key in ("strengths", "weaknesses"):
            b.gap = hint
        b.data["traces"] = {i: traces.get(i, []) for s in b.statements for i in s.fact_ids if i in traces}
    sec.data["traces"] = traces
    sec.data["subject"] = subject
    sec.confidence = confidence(tail + head + about)
    return finish(sec)


def opportunity(ctx: Ctx) -> Section:
    """Score each candidate opportunity from the evidence that mentions it. The rubric is fixed and shown:

    attractiveness = 2, +1 if any tailwind, +1 if 3 or more tailwinds, +1 if customer evidence asks for it,
                     -1 if headwinds outnumber tailwinds                         (clamped to 1..5)
    ability to win = 4, -1 for every 2 companies already holding records here, -1 if 2 or more headwinds
                                                                                  (clamped to 1..5)
    """
    sec = Section(framework="opportunity", title="Opportunity landscape")
    points = []
    for opp in ctx.plan.opportunities:
        facts = rank(
            dedupe(
                [
                    f
                    for f in ctx.mentioning(opp["terms"])
                    if f.kind not in ("calculated", "user") and "capability" not in f.topics
                ]
            )
        )
        if len({f.source_id for f in facts}) < ctx.min_facts:
            sec.blocks.append(
                Block(
                    key=opp["id"],
                    title=opp["name"],
                    gap=f"Not enough evidence to score: {len(facts)} fact(s) from "
                    f"{len({f.source_id for f in facts})} source(s).",
                )
            )
            points.append({"id": opp["id"], "name": opp["name"], "a": None, "b": None, "n": len(facts)})
            continue
        tail = sum(f.direction == "tailwind" for f in facts)
        head = sum(f.direction == "headwind" for f in facts)
        cust = sum(any(t.startswith(("customers:", "segment:")) for t in f.topics) or f.kind == "upload" for f in facts)
        cos = len(
            {
                norm_company(f.entity)
                for f in facts
                if f.entity
                and f.entity != "FDA"
                and (f.metric in ("decision", "patents_by_assignee", "trials_by_sponsor") or "competitor" in f.topics)
            }
        )
        a = max(1, min(5, 2 + (tail > 0) + (tail >= 3) + (cust > 0) - (head > tail)))
        b = max(1, min(5, 4 - cos // 2 - (head >= 2)))
        c = ctx.add_calc(
            f"Score for {opp['name']}: attractiveness {a} of 5 ({_n(tail, 'tailwind')}, "
            f"{_n(head, 'headwind')}, {_n(cust, 'customer fact')}); ability to win {b} of 5 "
            f"({_n(cos, 'company', 'companies')} already holding records here); from "
            f"{_n(len(facts), 'fact')}.",
            float(a * b),
            "score",
            facts[:12],
            "opportunity_score",
            [f"opportunity:{opp['id']}"],
        )
        sec.blocks.append(
            Block(
                key=opp["id"],
                title=opp["name"],
                rating=f"{a}×{b}",
                statements=[Statement(text=c.claim, fact_ids=[c.id] + [f.id for f in facts[:4]], judgement=True)]
                + [quote(f) for f in _mix(facts, 3)],
                data={"a": a, "b": b, "calc": c.id, "tail": tail, "head": head, "cust": cust, "companies": cos},
            )
        )
        points.append({"id": opp["id"], "name": opp["name"], "a": a, "b": b, "n": len(facts), "calc": c.id})
    if not ctx.plan.opportunities:
        sec.open_questions.append(
            "No candidate opportunities are defined for this field; add them to the brief or pack."
        )
    sec.data["points"] = points
    sec.data["rubric"] = opportunity.__doc__.split("shown:")[1].strip()
    sec.confidence = "medium" if any(p["a"] for p in points) else "low"
    return finish(sec)


def recommendations(ctx: Ctx, found: list[Finding]) -> Section:
    sec = Section(framework="recommendations", title="Recommendations and next steps")
    opp = ctx.sections.get("opportunity")
    scored = sorted(
        [p for p in (opp.data.get("points", []) if opp else []) if p.get("a")],
        key=lambda p: (-(p["a"] * p["b"]), -p["a"], -p["n"]),
    )[:3]
    if not scored:
        sec.blocks.append(
            Block(
                key="options",
                title="Options",
                gap=(
                    "Not enough evidence to score any opportunity, so no option is recommended. "
                    "Close the open questions "
                    "first, with a secondary search or your own data."
                ),
            )
        )
        sec.data["options"] = []
        return finish(sec)
    a = assumption_facts(ctx)
    options = []
    for i, p in enumerate(scored):
        letter = "ABC"[i]
        calc = ctx.store.fact(p["calc"])
        opp_block = next(b for b in opp.blocks if b.key == p["id"])
        support = [s for s in opp_block.statements[1:3]]
        linked, cautions = [], []
        for k in found:
            ids = [x for x in k.fact_ids if x in set(calc.inputs)]
            if k.strength == "signal" or not ids:
                continue
            dirs = [ctx.store.fact(x).direction for x in ids]
            (cautions if k.theme == "risk" or dirs.count("headwind") > dirs.count("tailwind") else linked).append(
                (k, ids)
            )
        stmts = [Statement(text=calc.claim, fact_ids=[calc.id] + calc.inputs[:4], judgement=True)] + support
        for k, ids in linked[:2]:
            stmts.append(judge(f"Supported by finding {k.id}: {k.title}.", [ctx.store.fact(x) for x in ids[:3]]))
        for k, ids in cautions[:1]:
            stmts.append(judge(f"Watch finding {k.id}: {k.title}.", [ctx.store.fact(x) for x in ids[:3]]))
        linked = [k for k, _ in linked]
        must = (
            [
                {"id": x["id"], "text": x["text"]}
                for x in ctx.plan.assumptions
                if x.get("metric") in ("reachable_share", "price_per_slide")
            ]
            if a
            else []
        )
        sec.blocks.append(
            Block(
                key=f"opt_{letter}",
                title=f"Option {letter}: {p['name']}",
                rating="Recommended" if i == 0 else "",
                statements=stmts,
                data={
                    "score": p["a"] * p["b"],
                    "a": p["a"],
                    "b": p["b"],
                    "must": must,
                    "findings": [k.id for k in linked],
                },
            )
        )
        options.append(
            {
                "letter": letter,
                "name": p["name"],
                "a": p["a"],
                "b": p["b"],
                "recommended": i == 0,
                "must": must,
                "findings": [k.id for k in linked],
            }
        )
    gaps = [q for s in ctx.sections.values() for q in s.open_questions][:4]
    reg = ctx.sections.get("regulatory")
    codes = sorted({row["code"] for row in (reg.data.get("timeline", []) if reg else [])})
    vc = ctx.sections.get("value_chain")
    partners = [st for st in (vc.data.get("stages", []) if vc else []) if st["players"]]
    steps = {"First 30 days": [], "Days 31 to 90": [], "Days 91 to 180": []}
    if codes:
        steps["First 30 days"].append(
            {
                "action": f"Confirm the regulatory route and a predicate among product codes {', '.join(codes)}",
                "owner": "Regulatory lead",
            }
        )
    for g in gaps[:2]:
        steps["First 30 days"].append(
            {"action": f"Close the open question: {g.split(':')[0]}", "owner": "Product manager"}
        )
    if partners:
        st = partners[0]
        steps["Days 31 to 90"].append(
            {
                "action": f"Shortlist partners at the {lower_name(st['name'])} stage ({', '.join(st['players'][:3])})",
                "owner": "Business development",
            }
        )
    steps["Days 31 to 90"].append(
        {"action": "Design a validation study for the recommended option", "owner": "Clinical or technical lead"}
    )
    steps["Days 91 to 180"].append(
        {"action": "Run a pilot with one partner and measure against the scored criteria", "owner": "Product manager"}
    )
    steps["Days 91 to 180"].append({"action": "Decision gate: go or no-go on the full build", "owner": "Leadership"})
    sec.data["options"] = options
    sec.data["steps"] = steps
    sec.data["note"] = "Next steps are proposals for you to own; they are actions, not findings."
    sec.confidence = "medium" if any(o["findings"] for o in options) else "low"
    return finish(sec)


RISK_CATS = [
    ("Regulatory", ("pestle:legal", "regulatory")),
    ("Market", ("pestle:economic", "market")),
    ("Technology", ("pestle:technological",)),
    ("Competitive", ("competitor", "porter")),
    ("Execution", ("risk",)),
]
IMPACT = {"Regulatory": 4, "Market": 3, "Technology": 4, "Competitive": 4, "Execution": 3}


def risks(ctx: Ctx) -> Section:
    sec = Section(framework="risks", title="Risks and assumptions")
    pool = rank(
        [
            f
            for f in ctx.facts
            if (f.direction == "headwind" or "risk" in f.topics)
            and f.kind != "calculated"
            and not (f.value == 0 and f.metric.endswith("_total"))
        ]
    )
    register, taken = [], set()
    for cat, prefixes in RISK_CATS:
        facts = [f for f in pool if f.id not in taken and any(t.startswith(prefixes) for t in f.topics)]
        if not facts:
            continue
        taken |= {f.id for f in facts}
        likelihood = min(5, 1 + len(facts))
        sec.blocks.append(
            Block(
                key=f"risk_{cat.lower()}",
                title=f"{cat} risk",
                rating=f"L{likelihood} × I{IMPACT[cat]}",
                statements=[quote(f) for f in facts[:3]],
                data={"likelihood": likelihood, "impact": IMPACT[cat], "n": len(facts)},
            )
        )
        register.append(
            {
                "category": cat,
                "likelihood": likelihood,
                "impact": IMPACT[cat],
                "facts": [f.id for f in facts[:3]],
                "top": facts[0].claim,
            }
        )
    if not register:
        sec.blocks.append(Block(key="risk_none", title="Risks", gap="No headwind or risk evidence in this run."))
    a_facts = [f for f in ctx.facts if f.kind == "user" and "assumption" in f.topics]
    sec.blocks.append(
        Block(
            key="assumptions",
            title="Assumptions you gave",
            statements=[quote(f) for f in a_facts],
            gap="" if a_facts else "No assumptions given in the brief.",
            data={"log": ctx.plan.assumptions},
        )
    )
    m = ctx.sections.get("market_size")
    bu = next((b for b in (m.blocks if m else []) if b.key == "bottom_up"), None)
    a = assumption_facts(ctx)
    if bu and bu.data.get("som") and "share_digitised" in a:
        som = bu.data["som"]
        som_fact = next(ctx.store.fact(i) for s in bu.statements for i in s.fact_ids[:1] if "SOM" in s.text)
        lo, hi = som * 0.5, som * 1.5
        c = ctx.add_calc(
            f"If A1 (share digitised) were half the assumed {fmt_num(a['share_digitised'].value)}%, SOM would "
            f"be {fmt_num(lo, 'USD')}; at one and a half times, {fmt_num(hi, 'USD')}.",
            hi,
            "USD",
            [som_fact, a["share_digitised"]],
            "sensitivity",
            ["assumption"],
        )
        sec.blocks.append(
            Block(
                key="sensitivity",
                title="How SOM moves if A1 is off",
                statements=[Statement(text=c.claim, fact_ids=[c.id, som_fact.id, a["share_digitised"].id])],
                data={"low": lo, "base": som, "high": hi},
            )
        )
    sec.data["register"] = register
    sec.confidence = confidence(pool)
    return finish(sec)


def summary(ctx: Ctx, found: list[Finding]) -> tuple[list[Statement], str, list[str], list[str]]:
    """Executive summary, written last and only from checked sections. Returns (statements, verdict, basis, gaps)."""
    stmts: list[Statement] = []
    fsec = ctx.sections.get("findings")
    for k in [k for k in found if k.strength != "signal"][:2]:
        blk = next((b for b in (fsec.blocks if fsec else []) if b.key == k.id), None)
        sup_id = blk.data.get("support") if blk else None
        sup = ctx.store.fact(sup_id) if sup_id else None
        if sup:
            stmts.append(
                Statement(
                    text=f"{k.title} ({k.strength} pattern): {sup.claim[0].lower()}{sup.claim[1:]} {k.sowhat}",
                    fact_ids=[sup.id] + k.fact_ids[:3],
                    judgement=True,
                )
            )
        else:
            stmts.append(judge(f"{k.title}. {k.sowhat}", [ctx.store.fact(i) for i in k.fact_ids[:3]]))
    porter = ctx.sections.get("porter")
    ent = next((b for b in (porter.blocks if porter else []) if b.key == "entrants" and b.statements), None)
    if ent:
        stmts.append(ent.statements[0])
    m = ctx.sections.get("market_size")
    bu = next((b for b in (m.blocks if m else []) if b.key == "bottom_up" and b.statements), None)
    if bu:
        txt = bu.statements[0].text.replace("Bottom-up SAM: ", "")
        stmts.append(
            Statement(
                text="Market sized bottom-up from cited facts and your assumptions (SAM): " + txt,
                fact_ids=bu.statements[0].fact_ids,
            )
        )
    rec = ctx.sections.get("recommendations")
    top = next((b for b in (rec.blocks if rec else []) if b.rating == "Recommended"), None)
    if top:
        o = next(x for x in rec.data["options"] if x["recommended"])
        stmts.append(
            judge(
                f"Recommended option: {o['name']}, scored {o['a']} of 5 for attractiveness and {o['b']} "
                f"of 5 for ability to win.",
                [ctx.store.fact(i) for i in top.statements[0].fact_ids[:4]],
            )
        )
    risk = ctx.sections.get("risks")
    rb = next((b for b in (risk.blocks if risk else []) if b.key.startswith("risk_") and b.statements), None)
    if rb:
        stmts.append(
            Statement(
                text=f"Top risk ({rb.title.lower()}): " + rb.statements[0].text, fact_ids=rb.statements[0].fact_ids
            )
        )
    # figures in the summary must come from the minimum tier (rule: summary_min_tier)
    allowed = {"A": ("A", "U"), "B": ("A", "U", "B"), "C": ("A", "U", "B", "C")}[ctx.cfg.evidence.summary_min_tier]
    clean = []
    for s in stmts:
        tiers = [ctx.store.fact(i).tier for i in s.fact_ids if ctx.store.fact(i)]
        if re.search(r"\d", s.text) and any(t not in allowed for t in tiers):
            continue
        clean.append(s)
    opp = ctx.sections.get("opportunity")
    best = max(
        (p for p in (opp.data.get("points", []) if opp else []) if p.get("a")),
        key=lambda p: p["a"] * p["b"],
        default=None,
    )
    strong = sum(k.strength == "strong" for k in found)
    if best and best["a"] >= 4 and best["b"] >= 3 and strong:
        verdict = "Attractive"
    elif best:
        verdict = "Selective"
    else:
        verdict = "Not enough evidence"
    basis = [i for s in clean for i in s.fact_ids][:12]
    gaps = [q for s in ctx.sections.values() for q in s.open_questions]
    return clean, verdict, basis, gaps


__all__ = ["findings", "swot", "opportunity", "recommendations", "risks", "summary"]
