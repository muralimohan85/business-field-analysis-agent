"""Shared machinery for the framework builders.

A builder reads only facts from the store (never the model's own knowledge), writes
statements that cite them, and marks a block as a gap when the evidence is thin. The
deterministic builders quote or summarise facts; numbers they add come from the
calculator as calculated facts, so the number check can trace them.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from bfa.calc import calculated_fact, fmt_num
from bfa.config import AgentConfig
from bfa.governance.scope import mentions
from bfa.schemas import Block, Brief, Fact, Plan, Section, Statement
from bfa.store import Store

TIER_RANK = {"A": 0, "U": 1, "B": 2, "C": 3}
_SUFFIX = re.compile(
    r"[,.]?\s+(inc|incorporated|ltd|limited|llc|corp|corporation|co|gmbh|ag|sa|s\.a|b\.v|bv|nv|n\.v|"
    r"plc|pte|kk|k\.k|ab|oy|srl|spa|holdings?|group|medical systems nederland|electronics nederland|nederland)\.?$",
    re.I,
)


@dataclass
class Ctx:
    store: Store
    plan: Plan
    brief: Brief
    cfg: AgentConfig
    include_secondary: bool = False
    today: date = field(default_factory=date.today)
    sections: dict[str, Section] = field(default_factory=dict)
    _facts: list[Fact] | None = None

    @property
    def facts(self) -> list[Fact]:
        """Evidence about the field. Facts about your own company (topic 'capability') are kept for the SWOT only."""
        return [f for f in self.all_facts if "capability" not in f.topics]

    @property
    def all_facts(self) -> list[Fact]:
        if self._facts is None:
            self._facts = self.store.facts(in_scope=True, include_secondary=self.include_secondary)
        return self._facts

    def refresh(self) -> None:
        self._facts = None

    def by_topic(self, topic: str) -> list[Fact]:
        return [f for f in self.facts if any(t == topic or t.startswith(topic + ":") for t in f.topics)]

    def by_metric(self, metric: str) -> list[Fact]:
        return [f for f in self.facts if f.metric == metric]

    def mentioning(self, terms: list[str], pool: list[Fact] | None = None) -> list[Fact]:
        return [f for f in (self.facts if pool is None else pool) if mentions(f.claim + " " + f.entity, terms)]

    def add_calc(
        self, claim: str, value, unit: str, inputs: list[Fact], metric: str, topics: list[str], year: int | None = None
    ) -> Fact:
        f = calculated_fact(claim, value, unit, inputs, metric, topics, year)
        self.store.add_fact(f)
        if self._facts is not None and all(x.id != f.id for x in self._facts):
            if self.include_secondary or f.basis == "primary":
                self._facts.append(f)
        return f

    @property
    def min_facts(self) -> int:
        return self.cfg.evidence.block_min_facts


def rank(facts: list[Fact]) -> list[Fact]:
    """Best evidence first: tier, then newest."""
    return sorted(facts, key=lambda f: (TIER_RANK.get(f.tier, 9), -(f.year or 0), f.id))


def dedupe(facts: list[Fact]) -> list[Fact]:
    seen, out = set(), []
    for f in facts:
        if f.id not in seen:
            seen.add(f.id)
            out.append(f)
    return out


def quote(f: Fact) -> Statement:
    """A statement that is the fact itself: the safest grounded sentence there is."""
    return Statement(text=f.claim, fact_ids=[f.id])


def judge(text: str, facts: list[Fact]) -> Statement:
    return Statement(text=text, fact_ids=[f.id for f in facts], judgement=True)


def independent(facts: list[Fact]) -> int:
    """Independent evidence = distinct sources (a calculated fact counts its inputs' sources)."""
    return len({f.source_id for f in facts if f.source_id != "calculator"} | {i for f in facts for i in f.inputs})


def block(
    key: str,
    title: str,
    facts: list[Fact],
    min_facts: int,
    limit: int = 6,
    gap_hint: str = "",
    extra: list[Statement] | None = None,
    rating: str = "",
    data: dict | None = None,
) -> Block:
    facts = rank(dedupe(facts))
    b = Block(
        key=key,
        title=title,
        statements=(extra or []) + [quote(f) for f in facts[:limit]],
        rating=rating,
        data=data or {},
    )
    if independent(facts) < min_facts and not extra:
        n = len(facts)
        b.gap = (
            f"Not enough evidence: {n} fact{'s' if n != 1 else ''} from "
            f"{independent(facts)} source{'s' if independent(facts) != 1 else ''}. {gap_hint}"
        ).strip()
    return b


def confidence(facts: list[Fact]) -> str:
    facts = dedupe(facts)
    if not facts:
        return "low"
    tier_a = sum(1 for f in facts if f.tier in ("A", "U")) / len(facts)
    srcs = independent(facts)
    if len(facts) >= 8 and srcs >= 3 and tier_a >= 0.6:
        return "high"
    if len(facts) >= 3 and srcs >= 2:
        return "medium"
    return "low"


def finish(section: Section) -> Section:
    """Every gap becomes an open question; confidence comes from the facts the section cites."""
    for b in section.blocks:
        q = f"{b.title}: {b.gap}"
        if b.gap and q not in section.open_questions:
            section.open_questions.append(q)
    n, gaps = len(section.blocks), sum(1 for b in section.blocks if b.gap)
    if n and gaps == n:
        section.confidence = "low"
    elif n and gaps * 2 >= n and section.confidence == "high":
        section.confidence = "medium"
    return section


def norm_company(name: str) -> str:
    n = " ".join((name or "").replace(",", " ").split())
    for _ in range(3):
        n2 = _SUFFIX.sub("", n).strip(" ,.")
        if n2 == n:
            break
        n = n2
    return n


def group_entities(facts: list[Fact], known: list[str]) -> dict[str, list[Fact]]:
    """Group facts by company, folding legal-name variants and matching names you gave in the brief."""
    groups: dict[str, list[Fact]] = defaultdict(list)
    for f in facts:
        if not f.entity or f.entity in ("FDA",):
            continue
        base = norm_company(f.entity)
        label = next((k for k in known if k.lower() in base.lower() or base.lower().startswith(k.lower())), None)
        if label is None:
            label = next(
                (
                    g
                    for g in groups
                    if g.lower() == base.lower()
                    or base.lower().startswith(g.lower() + " ")
                    or g.lower().startswith(base.lower() + " ")
                ),
                base,
            )
        groups[label].append(f)
    return dict(groups)


def series(facts: list[Fact]) -> dict[tuple[str, str], list[Fact]]:
    """Group yearly facts by (metric, entity or claim stem)."""
    out: dict[tuple[str, str], list[Fact]] = defaultdict(list)
    for f in facts:
        if f.year is None or f.value is None:
            continue
        stem = re.sub(r"\b(19|20)\d\d\b", "", f.claim)
        stem = re.sub(r"[\d,.]+", "#", stem)
        out[(f.metric, f.entity or stem)].append(f)
    return {k: sorted(v, key=lambda x: x.year) for k, v in out.items() if len({x.year for x in v}) >= 2}


def change_claim(first: Fact, last: Fact, what: str, unit: str = "") -> str:
    a, b = fmt_num(first.value, unit), fmt_num(last.value, unit)
    verb = (
        "rose"
        if (last.value or 0) > (first.value or 0)
        else "fell"
        if (last.value or 0) < (first.value or 0)
        else "held"
    )
    return f"{what} {verb} from {a} in {first.year} to {b} in {last.year}."


def lower_name(name: str) -> str:
    """Lower-case a stage name for use mid-sentence, keeping acronyms such as 'AI'."""
    return " ".join(w if w.isupper() and len(w) > 1 else w.lower() for w in name.split())
