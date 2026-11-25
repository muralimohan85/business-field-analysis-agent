"""Arithmetic done in code, never by the model (rule 2).

Every result becomes a calculated fact that lists the fact ids it was computed from,
so a number in the report can always be traced back to its inputs.
"""

from __future__ import annotations

from bfa.schemas import Fact, short_hash


def cagr(start: float, end: float, years: float) -> float | None:
    if start is None or end is None or start <= 0 or end <= 0 or years <= 0:
        return None
    return (end / start) ** (1 / years) - 1


def fold_change(start: float, end: float) -> float | None:
    if not start or start <= 0 or end is None:
        return None
    return end / start


def value_range(values: list[float]) -> tuple[float, float] | None:
    vals = [v for v in values if v is not None]
    return (min(vals), max(vals)) if vals else None


def product(values: list[float]) -> float | None:
    out = 1.0
    for v in values:
        if v is None:
            return None
        out *= v
    return out


def fmt_num(v: float | None, unit: str = "") -> str:
    """Format a number the same way everywhere, so the number check can find it in the facts."""
    if v is None:
        return "n/a"
    if unit in ("USD", "$"):
        if abs(v) >= 1e9:
            return f"${v / 1e9:,.1f} billion"
        if abs(v) >= 1e6:
            return f"${v / 1e6:,.1f} million"
        return f"${v:,.0f}"
    if unit == "%":
        return f"{v:.0f}%" if float(v).is_integer() else f"{v:.1f}%"
    if abs(v) >= 1000 or float(v).is_integer():
        return f"{v:,.0f}"
    return f"{v:,.2f}"


def calculated_fact(
    claim: str,
    value: float | None,
    unit: str,
    inputs: list[Fact],
    metric: str,
    topics: list[str],
    year: int | None = None,
) -> Fact:
    """A fact produced by the calculator. Its basis is primary only if every input is primary."""
    basis = "primary" if all(f.basis == "primary" for f in inputs) else "secondary"
    tier = "A" if basis == "primary" and all(f.tier in ("A", "U") for f in inputs) else "C"
    return Fact(
        id="CALC-" + short_hash([claim, [f.id for f in inputs]], 8),
        source_id="calculator",
        claim=claim,
        metric=metric,
        value=value,
        unit=unit,
        year=year,
        topics=topics,
        basis=basis,
        tier=tier,
        kind="calculated",
        inputs=[f.id for f in inputs],
        location="computed in code",
    )
