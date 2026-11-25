"""Deterministic tagging of free text: topics, direction and simple metrics (market sizes, growth rates).

Used for web passages, news and uploads when the deterministic engine runs. The Claude
engine classifies text itself, but its output passes the same checks.
"""

from __future__ import annotations

import re
from functools import lru_cache

from bfa.config import load_yaml
from bfa.governance.scope import mentions

_MONEY = re.compile(r"(?:US\$|USD|\$)\s?(\d+(?:[.,]\d+)?)\s?(billion|million|bn|mn|b|m)\b", re.IGNORECASE)
_PCT = re.compile(r"(\d+(?:\.\d+)?)\s?%")
_YEAR = re.compile(r"\b(20[0-4]\d)\b")


@lru_cache(maxsize=1)
def rules() -> dict:
    return load_yaml("rules.yaml")


def tag(text: str, extra_terms: dict[str, list[str]] | None = None) -> tuple[list[str], str]:
    """Return (topics, direction) for a passage."""
    r = rules()
    topics = [t for t, terms in r["topics"].items() if mentions(text, terms)]
    for t, terms in (extra_terms or {}).items():
        if mentions(text, terms):
            topics.append(t)
    tail = mentions(text, r["direction"]["tailwind"])
    head = mentions(text, r["direction"]["headwind"])
    direction = "headwind" if head and not tail else "tailwind" if tail and not head else "neutral"
    return sorted(set(topics)), direction


def money(text: str) -> float | None:
    m = _MONEY.search(text)
    if not m:
        return None
    v = float(m.group(1).replace(",", ""))
    mult = 1e9 if m.group(2).lower() in ("billion", "bn", "b") else 1e6
    return v * mult


def growth_rate(text: str) -> float | None:
    if not re.search(r"cagr|compound annual|annual growth|grow(?:th|ing)? at", text, re.IGNORECASE):
        return None
    m = _PCT.search(text)
    return float(m.group(1)) if m else None


def year_in(text: str) -> int | None:
    years = [int(y) for y in _YEAR.findall(text)]
    return min(years) if years else None


_LABS = re.compile(r"(\d[\d,]*)\s+(?:pathology\s+|histopathology\s+|clinical\s+)?(?:laboratories|labs)\b", re.I)
_SLIDES = re.compile(r"(\d[\d,]*)\s+(?:glass\s+)?slides\s+(?:per|a|each)\s+(?:lab|laboratory)\b", re.I)
_PATHOLOGISTS = re.compile(r"(\d[\d,]*)\s+(?:practising\s+|practicing\s+)?pathologists\b", re.I)


def _int(s: str) -> float:
    return float(s.replace(",", ""))


def market_metrics(text: str) -> dict:
    """Metrics a sentence states outright: market size (USD), growth rate (%), labs, slides per lab, pathologists."""
    out = {}
    for rx, metric, unit in (
        (_SLIDES, "slides_per_lab", "slides"),
        (_LABS, "labs_count", "labs"),
        (_PATHOLOGISTS, "pathologists_count", "pathologists"),
    ):
        m = rx.search(text)
        if m and _int(m.group(1)) >= 10:
            return {"metric": metric, "value": _int(m.group(1)), "unit": unit, "year": year_in(text)}
    if re.search(r"market", text, re.IGNORECASE):
        v = money(text)
        if v:
            out.update(metric="market_size", value=v, unit="USD", year=year_in(text))
    g = growth_rate(text)
    if g is not None and "metric" not in out:
        out.update(metric="growth_rate", value=g, unit="%", year=year_in(text))
    return out
