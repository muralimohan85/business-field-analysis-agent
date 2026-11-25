"""Scope lock (rule 10): once the plan is approved, field, geography and horizon are fixed.

A fact outside the scope is not deleted. It is set aside with the reason, so you can
see what the agent left out and why.
"""

from __future__ import annotations

import re
from datetime import date

from bfa.schemas import Fact, Plan

GLOBAL = {"global", "world", "worldwide", "all"}
_EU = {"eu", "europe", "european union"}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def mentions(text: str, terms: list[str]) -> str | None:
    t = _norm(text)
    for term in terms:
        term_n = _norm(term)
        if term_n and re.search(r"(?<![a-z0-9])" + re.escape(term_n) + r"(?:s|es)?(?![a-z0-9])", t):
            return term
    return None


class ScopeLock:
    def __init__(self, plan: Plan, exclude_after_years: int = 10, today: date | None = None):
        self.plan = plan
        self.scope_terms = plan.scope_terms
        self.exclude_terms = plan.exclude_terms
        self.geo = {_norm(g) for g in plan.geography}
        self.exclude_after = exclude_after_years
        self.today = today or date.today()

    def geography_ok(self, geography: str) -> bool:
        g = _norm(geography)
        if not g or not self.geo or self.geo & GLOBAL or g in GLOBAL:
            return True
        if g in self.geo:
            return True
        return g in _EU and bool(self.geo & _EU)

    def check(self, fact: Fact, targeted: bool) -> tuple[bool, str]:
        """targeted = the fact came from a structured query aimed at this field (a product code, a series id)."""
        text = " ".join([fact.claim, fact.entity])
        bad = mentions(text, self.exclude_terms)
        if bad:
            return False, f"mentions the excluded term '{bad}'"
        if not self.geography_ok(fact.geography):
            return False, f"geography '{fact.geography}' is outside the brief ({', '.join(self.plan.geography)})"
        if fact.year and self.exclude_after and fact.year < self.today.year - self.exclude_after:
            return False, f"from {fact.year}, older than the {self.exclude_after}-year limit"
        if targeted or fact.kind in ("statistics", "calculated", "user"):
            return True, "targeted query" if targeted else ""
        hit = mentions(text, self.scope_terms) if self.scope_terms else "any"
        if not hit:
            return False, "does not mention the field"
        return True, f"mentions '{hit}'"
