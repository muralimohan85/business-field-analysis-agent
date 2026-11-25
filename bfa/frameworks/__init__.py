"""Framework registry. Builders run in dependency order: the environment and market first,
then players, then synthesis (findings, SWOT, opportunities, recommendations, risks), which
reads the sections built before it.
"""

from __future__ import annotations

from bfa.frameworks import environment, market, players, synthesis
from bfa.frameworks.base import Ctx
from bfa.schemas import Finding, Section

TITLES = {
    "pestle": "PESTLE",
    "market_size": "Market size and growth",
    "customers": "Customer segments and needs",
    "trends": "Trends and signals",
    "porter": "Porter's five forces",
    "value_chain": "Value chain and channels",
    "competitors": "Competitor analysis",
    "swot": "SWOT",
    "opportunity": "Opportunity landscape",
    "bmc": "Business model canvas",
    "findings": "Key findings and patterns",
    "recommendations": "Recommendations and next steps",
    "risks": "Risks and assumptions",
    "regulatory": "Regulatory pathway",
    "technology": "Technology readiness",
    "scenarios": "Scenarios",
}

BUILDERS = {
    "pestle": environment.pestle,
    "regulatory": environment.regulatory,
    "market_size": market.market_size,
    "trends": market.trends,
    "technology": environment.technology,
    "customers": players.customers,
    "value_chain": players.value_chain,
    "porter": environment.porter,
    "competitors": players.competitors,
    "bmc": players.bmc,
    "scenarios": environment.scenarios,
}
SYNTHESIS = ["findings", "swot", "opportunity", "recommendations", "risks"]
ORDER = list(BUILDERS) + SYNTHESIS
# Report reading order (what the reader sees), independent of build order.
READING_ORDER = [
    "findings",
    "pestle",
    "market_size",
    "customers",
    "trends",
    "regulatory",
    "technology",
    "porter",
    "value_chain",
    "competitors",
    "swot",
    "opportunity",
    "bmc",
    "scenarios",
    "recommendations",
    "risks",
]
# Synthesis needs some inputs even if you switched them off; they are built quietly and not shown.
NEEDS = {
    "recommendations": ["opportunity"],
    "swot": ["porter"],
    "risks": ["market_size"],
    "bmc": ["customers", "value_chain"],
    "opportunity": [],
    "findings": [],
}


def analyse(ctx: Ctx, frameworks: list[str]) -> tuple[dict[str, Section], list[Finding]]:
    wanted = set(frameworks)
    needed = set(wanted) | {"findings"}  # findings feed recommendations and the summary
    for fw in list(wanted):
        needed |= set(NEEDS.get(fw, []))
    found: list[Finding] = []
    for fw in ORDER:
        if fw not in needed:
            continue
        if fw == "findings":
            found, sec = synthesis.findings(ctx)
        elif fw == "recommendations":
            sec = synthesis.recommendations(ctx, found)
        elif fw in SYNTHESIS:
            sec = getattr(synthesis, fw)(ctx)
        else:
            sec = BUILDERS[fw](ctx)
        ctx.sections[fw] = sec
    shown = {fw: ctx.sections[fw] for fw in READING_ORDER if fw in wanted and fw in ctx.sections}
    return shown, found


__all__ = ["analyse", "BUILDERS", "ORDER", "READING_ORDER", "TITLES", "Ctx"]
