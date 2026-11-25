"""Static charts for the exports (PNG). Single series each: no legend; direct labels; thin marks; recessive axes."""

from __future__ import annotations

from pathlib import Path

SERIES = "#257de0"
TEXT = "#191919"
MUTED = "#666666"
GRID = "#e6e6e6"


def _style(ax) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=8, length=0)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def decisions_chart(points: list[dict], path: Path, title: str = "FDA decisions per year") -> Path | None:
    """points: [{year, value}] from the trends section (full years only)."""
    if len(points) < 2:
        return None
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6.4, 2.6), dpi=200)
    years = [p["year"] for p in points]
    vals = [p["value"] for p in points]
    ax.bar(years, vals, width=0.6, color=SERIES, edgecolor="white", linewidth=1.5)
    peak = max(range(len(vals)), key=lambda i: vals[i])
    ax.annotate(
        f"{vals[peak]:g}",
        (years[peak], vals[peak]),
        textcoords="offset points",
        xytext=(0, 3),
        ha="center",
        fontsize=8,
        color=TEXT,
    )
    ax.annotate(
        f"{vals[-1]:g}",
        (years[-1], vals[-1]),
        textcoords="offset points",
        xytext=(0, 3),
        ha="center",
        fontsize=8,
        color=TEXT,
    )
    ax.set_xticks(years)
    ax.set_xticklabels([str(y) for y in years])
    ax.set_title(title, loc="left", fontsize=10, color=TEXT)
    _style(ax)
    fig.tight_layout()
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    return path


def opportunity_chart(points: list[dict], path: Path) -> Path | None:
    """2x2: attractiveness (y) against ability to win (x), one labelled dot per scored opportunity."""
    pts = [p for p in points if p.get("a")]
    if not pts:
        return None
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(5.2, 3.6), dpi=200)
    ax.axhline(3, color=GRID, linewidth=1)
    ax.axvline(3, color=GRID, linewidth=1)
    for p in pts:
        ax.scatter(p["b"], p["a"], s=70, color=SERIES, edgecolor="white", linewidth=1.5, zorder=3)
        ax.annotate(p["name"], (p["b"], p["a"]), textcoords="offset points", xytext=(7, 4), fontsize=8, color=TEXT)
    ax.set_xlim(0.5, 5.8)
    ax.set_ylim(0.5, 5.5)
    ax.set_xlabel("Ability to win (1 to 5)", fontsize=8, color=MUTED)
    ax.set_ylabel("Attractiveness (1 to 5)", fontsize=8, color=MUTED)
    ax.set_title("Opportunity landscape (scores from the evidence rubric)", loc="left", fontsize=10, color=TEXT)
    _style(ax)
    ax.xaxis.grid(False)
    ax.yaxis.grid(False)
    fig.tight_layout()
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    return path


def make_charts(sections: dict, folder: Path) -> dict[str, Path]:
    """sections: report.sections (the full report, whatever the export scope)."""
    folder.mkdir(parents=True, exist_ok=True)
    out = {}
    tr = sections.get("trends")
    if tr:
        series = next((v for k, v in tr.data.get("chart", {}).items() if "decision" in k.lower()), None)
        if series and (p := decisions_chart(series, folder / "decisions.png")):
            out["trends"] = p
    op = sections.get("opportunity")
    if op and (p := opportunity_chart(op.data.get("points", []), folder / "opportunity.png")):
        out["opportunity"] = p
    return out


__all__ = ["make_charts", "decisions_chart", "opportunity_chart"]
