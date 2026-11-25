"""Styling and small HTML pieces for the Streamlit app (tokens from the design mockup)."""

from __future__ import annotations

import html

import streamlit as st

T = {
    "bg": "#F5F6F8",
    "ink": "#111827",
    "muted": "#4B5563",
    "line": "#E3E6EB",
    "accent": "#2563EB",
    "accent_bg": "#EAF0FE",
    "accent_ink": "#1E40AF",
    "nav": "#0E1A2B",
    "warn": "#B45309",
    "warn_bg": "#FDF3E2",
    "good": "#15803D",
    "good_bg": "#E8F5EC",
    "bad": "#B91C1C",
    "bad_bg": "#FDECEC",
    "sec": "#7C3AED",
    "sec_bg": "#F1EAFE",
    "up": "#9C5D0C",
    "up_bg": "#F8F0E4",
}

CSS = f"""
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Space+Grotesk:wght@500;600&display=swap">
<style>
html, body, [class*="css"], .stApp, .stMarkdown, button, input, textarea, select {{
  font-family: Inter, system-ui, sans-serif !important; }}
.stApp {{ background: {T["bg"]}; color: {T["ink"]}; }}
h1, h2, h3 {{ font-family: 'Space Grotesk', Inter, sans-serif !important; color: {T["ink"]}; }}
.block-container {{ padding-top: 2.6rem; max-width: 1240px; }}
section[data-testid="stSidebar"] {{ background: {T["nav"]}; }}
section[data-testid="stSidebar"] * {{ color: #C9D2DE; }}
section[data-testid="stSidebar"] input, section[data-testid="stSidebar"] textarea {{ color: {T["ink"]} !important; }}
.bfa-lbl {{ font-size: 12px; font-weight: 600; letter-spacing: .05em; text-transform: uppercase; color: {T["muted"]}; }}
.bfa-sub {{ color: {T["muted"]}; font-size: 14px; margin-top: -4px; }}
.bfa-card {{ background: #fff; border: 1px solid {T["line"]}; border-radius: 12px; padding: 16px 20px; margin-bottom: 14px; }}
.bfa-card h4 {{ margin: 0 0 8px 0; font-size: 15px; font-weight: 600; font-family: Inter, sans-serif !important; }}
.bfa-kpi {{ background: #fff; border: 1px solid {T["line"]}; border-radius: 12px; padding: 12px 16px; }}
.bfa-kpi .l {{ font-size: 12.5px; color: {T["muted"]}; display: block; }}
.bfa-kpi .v {{ font-family: 'Space Grotesk', sans-serif; font-weight: 600; font-size: 26px; line-height: 1.3; display: block; }}
.bfa-kpi .n {{ font-size: 12px; color: {T["muted"]}; display: block; }}
.chip {{ display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 12px; font-weight: 500;
  border: 1px solid #D6DAE1; background: #fff; color: #374151; margin: 0 6px 6px 0; white-space: nowrap; }}
.ev {{ display: inline-block; font-size: 11px; font-weight: 600; padding: 0 6px; border-radius: 5px; background: {T["accent_bg"]};
  color: {T["accent_ink"]}; margin-left: 3px; vertical-align: 1px; cursor: help; }}
.stmt {{ font-size: 14.5px; line-height: 1.6; margin: 0 0 8px 0; }}
.stmt.j {{ background: #FFF8E6; border-radius: 6px; padding: 2px 6px; }}
.stmt .jl {{ font-size: 11px; font-weight: 600; color: {T["warn"]}; text-transform: uppercase; letter-spacing: .04em; margin-right: 6px; }}
.gap {{ background: {T["warn_bg"]}; color: #7C3F05; border-radius: 8px; padding: 8px 12px; font-size: 13.5px; margin: 6px 0 10px 0; }}
.blk {{ border-top: 1px solid {T["line"]}; padding-top: 10px; margin-top: 10px; }}
.blk h5 {{ font-size: 14.5px; font-weight: 600; margin: 0 0 6px 0; font-family: Inter, sans-serif !important; }}
.tbl {{ width: 100%; border-collapse: collapse; font-size: 13.5px; }}
.tbl th {{ text-align: left; font-size: 12px; color: {T["muted"]}; font-weight: 600; padding: 6px 8px; border-bottom: 1px solid {T["line"]}; }}
.tbl td {{ padding: 8px; border-bottom: 1px solid #EEF0F3; vertical-align: top; }}
.grid2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
.grid-bmc {{ display: grid; grid-template-columns: repeat(5, 1fr); grid-template-rows: auto auto auto; gap: 8px; }}
.cell {{ background: #fff; border: 1px solid {T["line"]}; border-radius: 10px; padding: 10px 12px; font-size: 13px; }}
.cell b {{ display: block; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: {T["muted"]}; margin-bottom: 4px; }}
.banner {{ border-radius: 10px; padding: 10px 14px; font-size: 13.5px; margin-bottom: 10px; }}
.src {{ font-size: 12.5px; color: {T["muted"]}; line-height: 1.5; margin-bottom: 4px; }}
sup a {{ text-decoration: none; }}
.stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {{
  background: {T["accent"]}; border-color: {T["accent"]}; }}
</style>
"""


def inject() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def md(h: str) -> None:
    st.markdown(h, unsafe_allow_html=True)


def pill(text: str, bg: str, fg: str) -> str:
    return f'<span class="chip" style="background:{bg};color:{fg};border-color:{bg}">{esc(text)}</span>'


def basis_pill(basis: str) -> str:
    if basis in ("primary_secondary", "Primary + secondary"):
        return pill("Primary + secondary", T["sec_bg"], T["sec"])
    return pill("Primary only", T["good_bg"], T["good"])


def conf_pill(c: str) -> str:
    bg, fg = {"high": (T["good_bg"], T["good"]), "medium": (T["warn_bg"], T["warn"])}.get(c, ("#EEF0F3", T["muted"]))
    return pill(f"Confidence: {c}", bg, fg)


def tier_pill(basis: str, tier: str, kind: str = "") -> str:
    if kind == "upload":
        return pill(f"Upload · {basis}", T["up_bg"], T["up"])
    if kind == "calculated":
        return pill("Calculated", "#EEF0F3", T["muted"])
    if kind == "user":
        return pill("Your assumption", T["up_bg"], T["up"])
    if basis == "secondary":
        return pill(f"Secondary · tier {tier}", T["sec_bg"], T["sec"])
    return pill(f"Primary · tier {tier}", T["good_bg"], T["good"])


def kpi(label: str, value: str, note: str = "") -> str:
    return (
        f'<div class="bfa-kpi"><span class="l">{esc(label)}</span><span class="v">{esc(value)}</span>'
        f'<span class="n">{esc(note)}</span></div>'
    )


def card(title: str, body: str, accent: str | None = None) -> str:
    top = f"border-top:3px solid {accent};" if accent else ""
    head = f"<h4>{esc(title)}</h4>" if title else ""
    return f'<div class="bfa-card" style="{top}">{head}{body}</div>'


def refs_html(refs: list[int], lookup: dict) -> str:
    out = []
    for n in refs:
        r = lookup.get(n)
        tip = esc(f"{r.claim} — {r.source} ({r.basis}, tier {r.tier}, {r.date or 'undated'})") if r else ""
        out.append(f'<span class="ev" title="{tip}">{n}</span>')
    return "".join(out)


def line_html(ln, lookup: dict) -> str:
    j = " j" if ln.judgement else ""
    lab = '<span class="jl">Judgement</span>' if ln.judgement else ""
    conf = f" {pill('confidential', T['up_bg'], T['up'])}" if ln.confidential else ""
    return f'<div class="stmt{j}">{lab}{esc(ln.text)} {refs_html(ln.refs, lookup)}{conf}</div>'


def gap_html(text: str) -> str:
    return f'<div class="gap"><b>Gap.</b> {esc(text)}</div>'
