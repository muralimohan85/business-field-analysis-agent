"""Step 1: turn the brief into a research plan.

The plan is the contract the rest of the run is held to: the query gate only lets
through searches that serve one of its questions, and the scope lock uses its terms.
The deterministic planner uses a domain pack when the field matches one; otherwise it
plans from the brief's own words. The Claude planner can propose extra terms, segments
and stages; they are merged here and shown to you before you approve.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import yaml

from bfa.config import CONFIG_DIR, AgentConfig, load_yaml
from bfa.governance.scope import mentions
from bfa.schemas import Brief, ConnectorQuery, Plan, PlanQuestion, now_iso

COUNTRIES = {
    "global": "WLD",
    "world": "WLD",
    "us": "USA",
    "usa": "USA",
    "united states": "USA",
    "eu": "EUU",
    "europe": "EUU",
    "european union": "EUU",
    "india": "IND",
    "uk": "GBR",
    "united kingdom": "GBR",
    "germany": "DEU",
    "france": "FRA",
    "china": "CHN",
    "japan": "JPN",
    "brazil": "BRA",
    "canada": "CAN",
}
STOP = {"and", "or", "for", "the", "of", "in", "a", "an", "to", "with", "based", "market", "field", "global"}


def packs() -> dict[str, dict]:
    out = {}
    for p in sorted((CONFIG_DIR / "packs").glob("*.yaml")):
        d = yaml.safe_load(Path(p).read_text())
        out[d["pack"]] = d
    return out


def select_topic(brief: Brief) -> tuple[str, str, dict]:
    """(pack id, topic id, topic dict) or ("", "", {}) when no pack fits."""
    all_packs = packs()
    for pid, pack in all_packs.items():
        if brief.pack and brief.pack != pid:
            continue
        for tid, topic in pack.get("topics", {}).items():
            if brief.topic == tid or (not brief.topic and mentions(brief.field, topic.get("match", []))):
                return pid, tid, topic
    return "", "", {}


def _words(text: str) -> list[str]:
    toks = [t for t in re.findall(r"[a-zA-Z][a-zA-Z0-9\-]+", text.lower()) if t not in STOP and len(t) > 2]
    return toks


def _frameworks(brief: Brief, cfg: AgentConfig, pack_id: str) -> list[str]:
    chosen = list(brief.frameworks or cfg.output.frameworks)
    if pack_id == "health" and "regulatory" not in chosen:
        chosen.append("regulatory")
    return chosen


def build_plan(brief: Brief, cfg: AgentConfig, today: date | None = None) -> Plan:
    today = today or date.today()
    pack_id, topic_id, topic = select_topic(brief)
    catalogue = load_yaml("frameworks.yaml")["frameworks"]
    geo = ", ".join(brief.geography)
    words = _words(brief.field)
    phrase = " ".join(words[:4])
    keywords = topic.get("keywords") or ([phrase] + words)
    scope_terms = topic.get("scope_terms") or ([phrase] + [w for w in words if len(w) > 4])
    plan = Plan(
        brief_key=brief.key(),
        field=brief.field,
        keywords=keywords,
        scope_terms=scope_terms,
        exclude_terms=topic.get("exclude_terms", []),
        geography=brief.geography,
        sub_segments=topic.get("sub_segments", []),
        companies=list(brief.competitors),
        segments=topic.get("segments", []),
        stages=topic.get("stages", []),
        opportunities=topic.get("opportunities", []),
        assumptions=list(brief.assumptions),
    )
    enabled = {
        c
        for c in (
            "openfda",
            "clinicaltrials",
            "pubmed",
            "openalex",
            "worldbank",
            "sec_edgar",
            "patentsview",
            "claude_web",
        )
        if cfg.connector_on(c)
    }
    for fw in _frameworks(brief, cfg, pack_id):
        spec = catalogue.get(fw)
        if not spec:
            continue
        plan.questions.append(
            PlanQuestion(
                id=f"Q-{fw}",
                framework=fw,
                text=spec["question"].format(field=brief.field, geo=geo, horizon=brief.horizon_years),
                terms=keywords[:6],
                connectors=[c for c in spec.get("connectors", []) if c in enabled],
            )
        )
    for i, q in enumerate(brief.questions, 1):
        plan.questions.append(
            PlanQuestion(id=f"Q-user-{i}", framework="user", text=q, terms=_words(q)[:6], connectors=sorted(enabled))
        )
    qids = {q.id for q in plan.questions}

    def add(connector: str, qid: str, label: str, **params) -> None:
        if connector in enabled and qid in qids:
            plan.queries.append(ConnectorQuery(connector=connector, question_id=qid, text=label, params=params))

    last_full_year = today.year - 1
    years = list(range(last_full_year - 9, last_full_year + 1))
    for pc in topic.get("fda_product_codes", []):
        code, stage = pc["code"], pc.get("stage", "")
        add(
            "openfda",
            "Q-regulatory" if "Q-regulatory" in qids else "Q-pestle",
            f"FDA classification {code}",
            endpoint="classification",
            product_code=code,
            stage=stage,
            targeted=True,
        )
        add(
            "openfda",
            "Q-competitors",
            f"FDA 510(k) and De Novo decisions {code}",
            endpoint="510k",
            product_code=code,
            stage=stage,
            targeted=True,
        )
        add(
            "openfda",
            "Q-risks",
            f"FDA recalls {code}",
            endpoint="recall",
            product_code=code,
            stage=stage,
            targeted=True,
        )
    for term in topic.get("pubmed_terms", [f'"{phrase}"']):
        add("pubmed", "Q-trends", f"PubMed papers per year: {term}", term=term, years=years, targeted=True)
    add(
        "openalex",
        "Q-trends",
        f"OpenAlex works per year: {topic.get('openalex_search', phrase)}",
        search=topic.get("openalex_search", phrase),
        from_year=years[0],
        targeted=True,
    )
    add(
        "clinicaltrials",
        "Q-trends",
        f"ClinicalTrials.gov studies: {topic.get('trials_term', phrase)}",
        term=topic.get("trials_term", phrase),
        targeted=True,
    )
    if topic.get("patents"):
        p = topic["patents"]
        add(
            "patentsview",
            "Q-trends",
            f"US patents: {p['text']} {p.get('cpc', '')}",
            text=p["text"],
            cpc=p.get("cpc", ""),
            from_year=years[0],
            targeted=True,
        )
    countries = sorted({COUNTRIES[g.lower()] for g in brief.geography if g.lower() in COUNTRIES} - {"WLD"}) or ["WLD"]
    for wb in topic.get("worldbank", [{"indicator": "NY.GDP.MKTP.KD.ZG", "unit": "%", "topics": ["pestle:economic"]}]):
        add(
            "worldbank",
            "Q-pestle",
            f"World Bank {wb['indicator']}",
            indicator=wb["indicator"],
            countries=countries,
            unit=wb.get("unit", ""),
            topics=wb.get("topics", ["pestle:economic"]),
            targeted=True,
        )
    for t in topic.get("sec_tickers", []):
        add(
            "sec_edgar",
            "Q-competitors",
            f"SEC company facts {t['company']}",
            ticker=t["ticker"],
            company=t["company"],
            targeted=True,
        )
    for fw, questions in topic.get("web_questions_primary", {}).items():
        for wq in questions:
            add("claude_web", f"Q-{fw}", wq, question=wq, primary=True)
    if not topic:
        for fw in ("pestle", "market_size", "customers", "risks"):
            wq = f"{catalogue[fw]['question'].format(field=brief.field, geo=geo, horizon=brief.horizon_years)}"
            add("claude_web", f"Q-{fw}", wq, question=wq, primary=True)
    plan.queries = plan.queries[:200]
    return plan


def approve(plan: Plan) -> Plan:
    plan.approved, plan.approved_at = True, now_iso()
    return plan


def secondary_questions(plan: Plan, gaps: list[str], sections: list[str], own: list[str]) -> list[PlanQuestion]:
    """Questions a secondary search may serve: the report's gaps, chosen sections and your own questions."""
    out = []
    short = plan.field.split(":")[0].strip()
    for i, g in enumerate(gaps, 1):
        topic = g.split(":")[0].strip()
        text = f"What do recent sources say about {topic.lower()} in {short}?"
        out.append(
            PlanQuestion(
                id=f"Q-sec-gap-{i}",
                framework="secondary",
                text=text,
                terms=(_words(topic) + plan.keywords[:4])[:8],
                connectors=["gdelt", "claude_web_open"],
            )
        )
    for s in sections:
        out.append(
            PlanQuestion(
                id=f"Q-sec-{s}",
                framework=s,
                text=f"Secondary evidence for {s} in {plan.field}",
                terms=plan.keywords[:6],
                connectors=["gdelt", "claude_web_open"],
            )
        )
    for i, q in enumerate(own, 1):
        out.append(
            PlanQuestion(
                id=f"Q-sec-own-{i}",
                framework="secondary",
                text=q,
                terms=_words(q)[:8],
                connectors=["gdelt", "claude_web_open"],
            )
        )
    return out
