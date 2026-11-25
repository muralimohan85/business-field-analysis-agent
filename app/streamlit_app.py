"""Business Field Analysis agent: Streamlit app.

    streamlit run app/streamlit_app.py

Opens on the AI digital pathology demo: real openFDA records recorded on 25 Nov 2026 plus
two fictional sample uploads, analysed offline. No API key is needed. Paste a Claude API
key in the sidebar to let Claude plan and write within the same facts and checks.
"""

from __future__ import annotations

import sys
import tempfile
from datetime import date
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ui import T, basis_pill, card, conf_pill, esc, gap_html, inject, kpi, line_html, md, pill, tier_pill  # noqa: E402

from bfa.checks import NAMES  # noqa: E402
from bfa.config import LOCKED_CHECKS, load_config, profiles, to_yaml  # noqa: E402
from bfa.frameworks import READING_ORDER, TITLES  # noqa: E402
from bfa.planner import approve, build_plan, packs  # noqa: E402
from bfa.report.render import build_doc  # noqa: E402
from bfa.schemas import Brief  # noqa: E402

st.set_page_config(page_title="Business Field Analysis agent", page_icon="🧭", layout="wide")
inject()

DEMO = ROOT / "data" / "demo" / "digital_pathology"
DEMO_DATE = date(2026, 11, 25)
DEMO_UPLOADS = [
    (str(DEMO / "uploads" / "example-diagnostics-lab-survey.pdf"), "primary", True),
    (str(DEMO / "uploads" / "lumen-slide-systems-brochure.docx"), "secondary", True),
]
PAGES = [
    "New analysis",
    "Plan and run",
    "Report",
    "Frameworks",
    "Evidence",
    "Secondary search",
    "Export",
    "Agent settings",
]
BASE_WS = Path(tempfile.gettempdir()) / "bfa-app"


# ====================================================================== state
def ss():
    return st.session_state


def go(page: str) -> None:
    """Move to another page from a button. Applied before the sidebar radio is drawn on the next run."""
    ss().goto = page
    st.rerun()


def set_secondary(on: bool) -> None:
    """Switch the secondary evidence view. Call it before the toggle is drawn in this run."""
    ss().show_secondary = on
    ss().sec_toggle = on


def secondary_toggle(label: str) -> None:
    # A keyed widget keeps its identity across reruns; an unkeyed one whose default changes loses every other click.
    if "sec_toggle" not in ss():
        ss().sec_toggle = ss().show_secondary
    st.toggle(label, key="sec_toggle", help="Rebuilds the report with or without the secondary search results.")
    ss().show_secondary = ss().sec_toggle


def ws() -> Path:
    """This browser session's own workspace: concurrent visitors must not share one evidence file."""
    if "ws" not in ss():
        import uuid

        ss().ws = BASE_WS / uuid.uuid4().hex[:12]
    return ss().ws


def init() -> None:
    if "brief" not in ss():
        ss().brief = yaml.safe_load((DEMO / "brief.yaml").read_text())
        ss().uploads = list(DEMO_UPLOADS)
        ss().profile = "strict-fact-based"
        ss().overrides = {}
        ss().plan = None
        ss().run = None
        ss().run_sec = None
        ss().show_secondary = False
        ss().nav = "Report"
        ss().demo = True


def cfg():
    return load_config(ss().profile, ss().overrides)


def client():
    key = ss().get("api_key", "").strip()
    if not key:
        return None
    import anthropic

    return anthropic.Anthropic(api_key=key)


def engine() -> str:
    return "claude" if ss().get("api_key", "").strip() else "deterministic"


def run_analysis(plan=None, demo=False) -> None:
    from bfa.pipeline import run

    brief = Brief(**ss().brief)
    mode = "live" if ss().get("live") else "replay"
    with st.status("Running the analysis", expanded=True) as status:
        steps = []

        def on_step(step, msg):
            steps.append(msg)
            if step in ("plan", "write", "done") or len(steps) % 5 == 0:
                st.write(f"{step}: {msg}")

        try:
            r = run(
                brief,
                cfg(),
                mode=mode,
                snapshot="digital-pathology-real",
                engine=engine(),
                uploads=ss().uploads,
                plan=plan,
                auto_approve=demo or plan is not None,
                client=client(),
                today=DEMO_DATE if demo else None,
                workspace=ws(),
                on_step=on_step,
            )
        except PermissionError as exc:
            status.update(label=str(exc), state="error")
            return
        except Exception as exc:  # show the reason instead of a redacted crash page
            status.update(label="The run stopped", state="error")
            st.error(f"The run stopped: {type(exc).__name__}: {exc}")
            return
        status.update(
            label=f"Done: {len(r.report.all_statements())} statements, "
            f"{sum(c.passed for c in r.report.checks)}/{len(r.report.checks)} checks passed",
            state="complete",
        )
    ss().run, ss().run_sec = r, None
    set_secondary(False)


def current():
    if ss().get("sec_toggle", ss().show_secondary) and ss().run_sec is not None:
        return ss().run_sec
    return ss().run


def ensure_run() -> bool:
    if ss().run is None and ss().demo:
        run_analysis(demo=True)
    return ss().run is not None


@st.cache_data(show_spinner=False)
def _doc_cache(run_id: str, basis: str, n: int):
    return None


def doc_for(r):
    key = (r.report.run_id, r.report.evidence_basis)
    cache = ss().setdefault("docs", {})
    if key not in cache:
        cache[key] = build_doc(r.report, r.store, "full", flag_after=r.cfg.evidence.flag_after_years)
    return cache[key]


# ====================================================================== sidebar
def sidebar() -> None:
    with st.sidebar:
        md(
            "<h2 style='color:#fff;margin:0 0 4px 0'>BFA agent</h2>"
            "<div style='font-size:12.5px;margin-bottom:14px'>Business field analysis, fact-based</div>"
        )
        if ss().get("goto"):
            ss().nav = ss().pop("goto")
        st.radio("Go to", PAGES, key="nav", label_visibility="collapsed")
        st.divider()
        st.caption("Engine")
        st.text_input(
            "Claude API key (optional)",
            type="password",
            key="api_key",
            help="Without a key the deterministic engine runs offline. With a key, Claude proposes plan "
            "vocabulary and rewrites statements; the same checks decide what stays.",
        )
        st.toggle("Live APIs (needs network)", key="live", help="Off: the recorded snapshot is replayed, no network.")
        st.caption(f"Engine: {engine()} · data: {'live' if ss().get('live') else 'recorded snapshot'}")
        if ss().run:
            r = current()
            st.divider()
            st.caption("Current analysis")
            md(
                f"<div style='font-size:13px'>{esc(r.report.brief.field.split(':')[0])}<br>"
                f"run {esc(r.report.run_id)}</div>"
            )
            md(basis_pill(r.report.evidence_basis))


# ====================================================================== pages
def page_new() -> None:
    st.title("New business field analysis")
    md(
        "<p class='bfa-sub'>Describe the field. The agent plans the research, gathers evidence from open databases and "
        "your documents, and fills the frameworks you pick. Every sentence in the report is cited; thin evidence is "
        "shown as a gap, never filled in.</p>"
    )
    b = ss().brief
    with st.form("brief_form"):
        md("<div class='bfa-lbl'>1 · The field</div>")
        field = st.text_area("Field, in plain words", b.get("field", ""), height=70)
        c1, c2, c3 = st.columns(3)
        geo = c1.text_input("Geography (comma separated)", ", ".join(b.get("geography", ["Global"])))
        horizon = c2.number_input("Horizon (years)", 1, 15, int(b.get("horizon_years", 5)))
        pos_opts = ["new_entrant", "incumbent", "investor", "supplier", "company"]
        position = c3.selectbox(
            "Your position",
            pos_opts,
            index=pos_opts.index(b.get("position", "new_entrant")),
            format_func=lambda x: x.replace("_", " "),
        )
        c4, c5 = st.columns(2)
        company = c4.text_input("Your company (optional, used for strengths and weaknesses)", b.get("company", ""))
        comps = c5.text_input("Competitors to track (comma separated)", ", ".join(b.get("competitors", [])))
        questions = st.text_area("Your questions (one per line)", "\n".join(b.get("questions", [])), height=70)
        md("<div class='bfa-lbl' style='margin-top:10px'>2 · Frameworks</div>")
        all_fw = [k for k in READING_ORDER]
        chosen = st.multiselect(
            "Frameworks to fill",
            all_fw,
            default=b.get("frameworks") or cfg().output.frameworks,
            format_func=lambda k: TITLES.get(k, k),
        )
        pk = packs()
        topics = [""] + [f"{p}/{t}" for p, d in pk.items() for t in d.get("topics", {})]
        cur = f"{b.get('pack', '')}/{b.get('topic', '')}" if b.get("topic") else ""
        topic = st.selectbox(
            "Domain pack (codes and segments for the databases)",
            topics,
            index=topics.index(cur) if cur in topics else 0,
            format_func=lambda x: x or "auto (plan from the brief's own words)",
        )
        md("<div class='bfa-lbl' style='margin-top:10px'>3 · Your assumptions (labelled wherever used)</div>")
        adf = pd.DataFrame(
            b.get("assumptions", []) or [{"id": "A1", "text": "", "metric": "", "value": None, "unit": ""}]
        )
        adf = st.data_editor(
            adf[[c for c in ["id", "text", "metric", "value", "unit", "confidence", "test"] if c in adf.columns]],
            num_rows="dynamic",
            width="stretch",
        )
        md("<div class='bfa-lbl' style='margin-top:10px'>4 · Your documents</div>")
        files = st.file_uploader(
            "PDF, Word, PowerPoint, Excel, CSV or text",
            accept_multiple_files=True,
            type=["pdf", "docx", "pptx", "xlsx", "csv", "txt", "md"],
        )
        basis = st.radio(
            "These files are",
            ["primary", "secondary"],
            horizontal=True,
            format_func=lambda x: "my own data (primary)" if x == "primary" else "third-party reports (secondary)",
        )
        keep_demo = st.checkbox("Keep the two fictional demo uploads", value=any(u[2] for u in ss().uploads))
        submitted = st.form_submit_button("Build the plan", type="primary")
    if submitted:
        pack, tid = (topic.split("/") + [""])[:2] if topic else ("", "")
        ss().brief = {
            "field": field.strip(),
            "geography": [g.strip() for g in geo.split(",") if g.strip()],
            "horizon_years": int(horizon),
            "position": position,
            "company": company.strip(),
            "competitors": [c.strip() for c in comps.split(",") if c.strip()],
            "questions": [q.strip() for q in questions.splitlines() if q.strip()],
            "frameworks": chosen,
            "pack": pack,
            "topic": tid,
            "assumptions": [
                {k: v for k, v in r.items() if v not in (None, "")}
                for r in adf.to_dict("records")
                if r.get("id") and r.get("text")
            ],
        }
        ups = [u for u in ss().uploads if keep_demo and u[2]]
        if files:
            ws().mkdir(parents=True, exist_ok=True)
            for f in files:
                p = ws() / "uploads" / f.name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(f.getvalue())
                ups.append((str(p), basis, False))
        ss().uploads = ups
        ss().plan = build_plan(Brief(**ss().brief), cfg())
        ss().demo = False
        go("Plan and run")
    if ss().uploads:
        md("<div class='bfa-lbl'>Uploads in this analysis</div>")
        for p, bs, sample in ss().uploads:
            md(
                f"<span class='chip'>{esc(Path(p).name)}</span> {tier_pill(bs, 'U', 'upload')}"
                f"{pill('fictional sample', '#EEF0F3', T['muted']) if sample else ''}"
            )


def page_plan() -> None:
    st.title("Plan and run")
    md(
        "<p class='bfa-sub'>The plan is the contract: after you approve it, the scope locks and every search "
        "must serve "
        "one of these questions. Searches that drift are blocked and logged.</p>"
    )
    if ss().plan is None:
        ss().plan = build_plan(Brief(**ss().brief), cfg())
    plan = ss().plan
    c = cfg()
    k1, k2, k3, k4 = st.columns(4)
    md("")
    k1.markdown(kpi("Questions", str(len(plan.questions))), unsafe_allow_html=True)
    k2.markdown(kpi("Planned queries", str(len(plan.queries))), unsafe_allow_html=True)
    k3.markdown(kpi("Evidence policy", c.evidence.policy.replace("_", " ").split(" then")[0]), unsafe_allow_html=True)
    k4.markdown(kpi("Search cap", f"{c.limits.web_searches} web · {c.limits.fetches} fetches"), unsafe_allow_html=True)
    left, right = st.columns([3, 2])
    with left:
        rows = "".join(
            f"<tr><td><code>{esc(q.id)}</code></td><td>{esc(q.text)}</td><td>"
            + "".join(f"<span class='chip'>{esc(x.connector)}</span>" for x in plan.queries if x.question_id == q.id)
            + "</td></tr>"
            for q in plan.questions
        )
        md(
            card(
                "Questions and the searches that serve them",
                f"<table class='tbl'><tr><th>Id</th><th>Question</th><th>Searches</th></tr>{rows}</table>",
            )
        )
    with right:
        md(
            card(
                "Scope lock",
                "<div class='bfa-lbl'>In scope if a fact mentions</div>"
                + "".join(f"<span class='chip'>{esc(t)}</span>" for t in plan.scope_terms)
                + "<div class='bfa-lbl' style='margin-top:8px'>Excluded</div>"
                + ("".join(f"<span class='chip'>{esc(t)}</span>" for t in plan.exclude_terms) or "none")
                + f"<div class='bfa-lbl' style='margin-top:8px'>Geography</div>{esc(', '.join(plan.geography))}",
            )
        )
        if plan.assumptions:
            md(
                card(
                    "Your assumptions",
                    "".join(
                        f"<div class='src'><b>{esc(a['id'])}</b> {esc(a['text'])}: "
                        f"{esc(a.get('value', ''))} {esc(a.get('unit', ''))}</div>"
                        for a in plan.assumptions
                    ),
                )
            )
    st.divider()
    ok = st.checkbox("I approve this plan. Lock the scope and run.", value=False)
    if st.button("Run the analysis", type="primary", disabled=not ok):
        run_analysis(approve(plan.model_copy(deep=True)))
        go("Report")


def header(r) -> None:
    rep, counts = r.report, r.store.counts()
    b = rep.brief
    st.title(b.field.split(":")[0])
    md(
        f"<p class='bfa-sub'>{esc(', '.join(b.geography))} · {b.horizon_years}-year horizon · seen as "
        f"{esc(b.company + ' (' if b.company else '')}{esc(b.position.replace('_', ' '))}{')' if b.company else ''}"
        f" · run {esc(rep.run_id)}</p>"
    )
    chips = basis_pill(rep.evidence_basis) + pill("Model knowledge: never a source", "#EEF0F3", T["muted"])
    if rep.fictional or any(s.fictional for s in r.store.sources()):
        chips += pill("Includes fictional sample uploads", T["up_bg"], T["up"])
    md(chips)
    for note in r.manifest.notes:
        st.warning(note)
    k = st.columns(5)
    k[0].markdown(kpi("Verdict", rep.verdict, "from scored opportunities and findings"), unsafe_allow_html=True)
    k[1].markdown(
        kpi(
            "Facts in scope",
            str(counts["facts"]),
            f"{counts['primary_facts']} primary · {counts['secondary_facts']} secondary",
        ),
        unsafe_allow_html=True,
    )
    k[2].markdown(
        kpi("Sources", str(counts["sources"]), f"{counts['set_aside']} facts set aside"), unsafe_allow_html=True
    )
    passed = sum(c.passed for c in rep.checks)
    k[3].markdown(
        kpi("Checks", f"{passed}/{len(rep.checks)}", "locked: citations, grounding, numbers"), unsafe_allow_html=True
    )
    gaps = sum(1 for s in rep.sections.values() for bl in s.blocks if bl.gap)
    k[4].markdown(kpi("Gaps stated", str(gaps), "thin evidence is shown, not filled"), unsafe_allow_html=True)


def section_html(ds, lookup) -> str:
    out = []
    for b in ds.blocks:
        rating = f" {pill(b.rating, T['accent_bg'], T['accent_ink'])}" if b.rating else ""
        body = "".join(line_html(ln, lookup) for ln in b.lines)
        if b.gap:
            body += gap_html(b.gap)
        out.append(f"<div class='blk'><h5>{esc(b.title)}{rating}</h5>{body}</div>")
    return "".join(out)


def page_report() -> None:
    if not ensure_run():
        st.info("Run an analysis first.")
        return
    if ss().run_sec is not None:
        secondary_toggle("Include secondary evidence")
    r = current()
    header(r)
    doc = doc_for(r)
    lookup = {x.n: x for x in doc.refs}
    left, right = st.columns([3, 1])
    with left:
        body = "".join(line_html(ln, lookup) for ln in doc.summary)
        md(card(f"Executive summary · verdict: {r.report.verdict}", body, T["accent"]))
        fd = next((s for s in doc.sections if s.key == "findings"), None)
        if fd:
            md(card("Key findings and patterns", section_html(fd, lookup)))
        for ds in doc.sections:
            if ds.key == "findings":
                continue
            with st.expander(f"{ds.title}", expanded=ds.key in ("recommendations",)):
                md(conf_pill(ds.confidence))
                md(section_html(ds, lookup))
    with right:
        md(
            card(
                "In this report",
                "".join(f"<div class='src'>{esc(s.title)} {conf_pill(s.confidence)}</div>" for s in doc.sections),
            )
        )
        md(
            card(
                "Checks",
                "".join(
                    f"<div class='src'>{'✅' if c['passed'] else '❌'} <b>Rule {c['rule']}</b> "
                    f"{esc(NAMES.get(c['name'], c['name']))}"
                    f"<br><span style='font-size:12px'>{esc(c['detail'])}</span></div>"
                    for c in doc.checks
                ),
            )
        )
        if doc.open_questions:
            md(card("Open questions", "".join(f"<div class='src'>• {esc(q)}</div>" for q in doc.open_questions[:12])))
    with st.expander(f"Sources ({len(doc.refs)})"):
        for x in doc.refs:
            link = f" <a href='{esc(x.url)}' target='_blank'>link</a>" if x.url.startswith("http") else ""
            flags = "".join(pill(f, T["warn_bg"], T["warn"]) for f in x.flags)
            md(
                f"<div class='src'><b>{x.n}.</b> {esc(x.claim)} — <i>{esc(x.source)}</i>, {esc(x.date or 'undated')} "
                f"{tier_pill(x.basis, x.tier, x.kind)}{flags}{link}</div>"
            )


def page_frameworks() -> None:
    if not ensure_run():
        return
    r = current()
    rep = r.report
    keys = [k for k in READING_ORDER if k in rep.sections]
    choice = st.radio(
        "Framework", keys, horizontal=True, format_func=lambda k: TITLES.get(k, k), label_visibility="collapsed"
    )
    sec = rep.sections[choice]
    doc = doc_for(r)
    lookup = {x.n: x for x in doc.refs}
    ds = next(s for s in doc.sections if s.key == choice)
    st.subheader(sec.title)
    md(conf_pill(sec.confidence))
    if choice == "swot":
        grid = "".join(
            f"<div class='cell'><b>{esc(b.title)}</b>"
            + "".join(line_html(ln, lookup) for ln in b.lines[:4])
            + (gap_html(b.gap) if b.gap else "")
            + "</div>"
            for b in ds.blocks
        )
        md(f"<div class='grid2'>{grid}</div>")
    elif choice == "bmc":
        pos = {
            "partners": "1/2/1/3",
            "activities": "2/3/1/2",
            "resources": "2/3/2/3",
            "value": "3/4/1/3",
            "relationships": "4/5/1/2",
            "channels": "4/5/2/3",
            "segments": "5/6/1/3",
            "costs": "1/3/3/4",
            "revenue": "3/6/3/4",
        }
        cells = []
        for b, key in zip(ds.blocks, [x.key for x in sec.blocks], strict=True):
            c0, c1, r0, r1 = pos.get(key, "1/2/1/2").split("/")
            cells.append(
                f"<div class='cell' style='grid-column:{c0}/{c1};grid-row:{r0}/{r1}'><b>{esc(b.title)}</b>"
                + "".join(line_html(ln, lookup) for ln in b.lines[:3])
                + (f"<div style='color:{T['warn']};font-size:12px'>Open: no evidence</div>" if b.gap else "")
                + "</div>"
            )
        md(f"<div class='grid-bmc'>{''.join(cells)}</div>")
    else:
        if choice == "opportunity" and sec.data.get("points"):
            pts = pd.DataFrame([p for p in sec.data["points"] if p.get("a")])
            if not pts.empty:
                base = alt.Chart(pts).encode(
                    x=alt.X(
                        "b:Q",
                        title="Ability to win (1 to 5)",
                        scale=alt.Scale(domain=[0.5, 5.5]),
                        axis=alt.Axis(values=[1, 2, 3, 4, 5]),
                    ),
                    y=alt.Y(
                        "a:Q",
                        title="Attractiveness (1 to 5)",
                        scale=alt.Scale(domain=[0.5, 5.5]),
                        axis=alt.Axis(values=[1, 2, 3, 4, 5]),
                    ),
                    tooltip=["name", "a", "b", "n"],
                )
                chart = base.mark_circle(size=140, color=T["accent"]) + base.mark_text(
                    align="left", dx=10, fontSize=12
                ).encode(text="name")
                st.altair_chart(chart.properties(height=320), width="stretch")
                st.caption("Rubric: " + sec.data.get("rubric", "").replace("\n", " "))
        if choice == "trends" and sec.data.get("chart"):
            rows = [
                {"series": k, "year": str(p["year"]), "value": p["value"]}
                for k, v in sec.data["chart"].items()
                for p in v
            ]
            df = pd.DataFrame(rows)
            for name, g in df.groupby("series"):
                st.caption(name)
                st.altair_chart(
                    alt.Chart(g)
                    .mark_bar(color=T["accent"], cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
                    .encode(x=alt.X("year:N", title=None), y=alt.Y("value:Q", title=None), tooltip=["year", "value"])
                    .properties(height=200),
                    width="stretch",
                )
        if choice == "competitors" and sec.data.get("matrix"):
            m = pd.DataFrame(sec.data["matrix"])
            m["codes"] = m["codes"].apply(lambda x: ", ".join(x))
            st.dataframe(
                m[
                    [
                        "company",
                        "known",
                        "new",
                        "decisions",
                        "codes",
                        "patents",
                        "trials",
                        "revenue",
                        "latest_date",
                        "latest",
                    ]
                ],
                width="stretch",
                hide_index=True,
            )
            new = m[m["new"]]["company"].tolist()
            if new and cfg().approvals.new_companies:
                acc = st.multiselect("Companies the run found that you did not name: accept as competitors", new)
                if st.button("Accept selected"):
                    prev = set(r.store.get("accepted_companies", []))
                    r.store.set("accepted_companies", sorted(prev | set(acc)))
                    st.success("Saved. They will no longer be flagged as new.")
        if choice == "customers" and sec.data.get("heatmap"):
            st.dataframe(pd.DataFrame(sec.data["heatmap"]).T, width="stretch")
        if choice == "regulatory" and sec.data.get("timeline"):
            st.dataframe(
                pd.DataFrame(sec.data["timeline"])[["date", "code", "company", "claim"]],
                width="stretch",
                hide_index=True,
            )
        if choice == "risks" and sec.data.get("register"):
            st.dataframe(pd.DataFrame(sec.data["register"]), width="stretch", hide_index=True)
        md(section_html(ds, lookup))
    if sec.open_questions:
        md(card("Open questions", "".join(f"<div class='src'>• {esc(q)}</div>" for q in sec.open_questions)))


def page_evidence() -> None:
    if not ensure_run():
        return
    r = current()
    store = r.store
    tabs = st.tabs(["Facts", "Sources", "Set aside", "Blocked queries", "Quarantined text", "Skipped", "Run manifest"])
    with tabs[0]:
        facts = store.facts(in_scope=True)
        df = pd.DataFrame(
            [
                {
                    "id": f.id,
                    "claim": f.claim,
                    "basis": f.basis,
                    "tier": f.tier,
                    "kind": f.kind,
                    "year": f.year,
                    "value": f.value,
                    "unit": f.unit,
                    "topics": ", ".join(f.topics),
                    "source": f.source_id,
                }
                for f in facts
            ]
        )
        c1, c2, c3 = st.columns(3)
        basis = c1.multiselect("Basis", ["primary", "secondary"], default=["primary", "secondary"])
        kinds = c2.multiselect("Kind", sorted(df["kind"].unique()), default=sorted(df["kind"].unique()))
        q = c3.text_input("Search the claims")
        view = df[df["basis"].isin(basis) & df["kind"].isin(kinds)]
        if q:
            view = view[view["claim"].str.contains(q, case=False)]
        st.caption(f"{len(view)} of {len(df)} facts. Calculated facts list the facts they were computed from.")
        st.dataframe(view, width="stretch", hide_index=True)
    with tabs[1]:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "id": s.id,
                        "title": s.title,
                        "publisher": s.publisher,
                        "basis": s.basis,
                        "tier": s.tier,
                        "kind": s.kind,
                        "published": s.published,
                        "fetched": s.fetched,
                        "url": s.url,
                        "fictional": s.fictional,
                    }
                    for s in store.sources()
                ]
            ),
            width="stretch",
            hide_index=True,
        )
    with tabs[2]:
        st.caption("Facts outside the locked scope are kept here with the reason, never cited.")
        st.dataframe(
            pd.DataFrame(
                [{"claim": f.claim, "reason": f.scope_note, "source": f.source_id} for f in store.facts(in_scope=False)]
            ),
            width="stretch",
            hide_index=True,
        )
    with tabs[3]:
        b = store.blocked()
        st.caption("Searches the query gate stopped because they did not serve the approved plan.")
        st.dataframe(pd.DataFrame([x.model_dump() for x in b]) if b else pd.DataFrame(), width="stretch")
    with tabs[4]:
        st.caption(
            "Sentences in sources that read like instructions to an AI tool. Removed before any engine read them."
        )
        for s in store.sources():
            for qtext in s.quarantined:
                md(f"<div class='gap'><b>{esc(s.title)}</b>: {esc(qtext)}</div>")
    with tabs[5]:
        st.caption("Planned queries that did not run, and why (missing key, not in the snapshot, cap reached).")
        for x in r.skipped:
            md(f"<div class='src'>• {esc(x)}</div>")
    with tabs[6]:
        st.json(r.manifest.model_dump(mode="json"), expanded=False)


def page_secondary() -> None:
    if not ensure_run():
        return
    from bfa.secondary import SecondaryRequest, run_secondary

    st.title("Secondary search (optional)")
    md(
        "<p class='bfa-sub'>The primary report is complete. A secondary search looks at news, company announcements, "
        "research firms and the wider web, only for what you pick. Everything it finds is labelled secondary, never "
        "replaces a primary fact and never feeds a figure in the executive summary. You can switch it off again.</p>"
    )
    base = ss().run
    c = base.cfg
    if not c.secondary_allowed():
        md(
            gap_html(
                "This profile's evidence policy is primary only, so secondary search is off. Change the policy in "
                "Agent settings to use it."
            )
        )
        return
    with st.form("secondary_form"):
        gaps = st.multiselect(
            "Open questions to work on", base.report.open_questions, default=base.report.open_questions[:3]
        )
        secs = st.multiselect(
            "Sections to add secondary evidence to",
            list(base.report.sections),
            default=["market_size"],
            format_func=lambda k: TITLES.get(k, k),
        )
        own = st.text_area("Your own questions (one per line)")
        conns = st.multiselect(
            "Sources",
            ["gdelt", "claude_web_open"],
            default=["gdelt", "claude_web_open"],
            format_func=lambda x: {
                "gdelt": "GDELT news (no key)",
                "claude_web_open": "Claude web search, wider web (key)",
            }[x],
        )
        mx = st.slider("Most searches", 1, c.limits.secondary_searches, min(10, c.limits.secondary_searches))
        ok = st.checkbox("I approve this secondary search (a plan amendment)")
        go = st.form_submit_button("Run secondary search", type="primary")
    if go:
        if not ok:
            st.warning("Tick the approval box first.")
        else:
            req = SecondaryRequest(
                gaps=gaps,
                sections=secs,
                own=[q for q in own.splitlines() if q.strip()],
                connectors=conns,
                max_searches=mx,
            )
            with st.spinner("Searching"):
                ss().run_sec = run_secondary(
                    base, req, mode="live" if ss().get("live") else "replay", client=client(), approve=True
                )
            set_secondary(True)
    if ss().run_sec is not None:
        s = ss().run_sec
        before, after = base.store.counts(), s.store.counts()
        md(
            card(
                "Result",
                f"{after['secondary_facts']} secondary facts in the store (including secondary uploads). "
                f"{len(s.skipped)} planned searches did not run: "
                + "; ".join(esc(x) for x in s.skipped[:3])
                + ("…" if len(s.skipped) > 3 else ""),
            )
        )
        secondary_toggle("Include secondary evidence in the report")
        st.caption(
            f"Primary report: {len(base.report.all_statements())} statements · with secondary: "
            f"{len(s.report.all_statements())} statements · before: {before['facts']} facts"
        )


def page_export() -> None:
    if not ensure_run():
        return
    from bfa.report.export import ExportBlocked, export

    r = current()
    st.title("Export")
    md(
        "<p class='bfa-sub'>Word, slides and PDF are written from the same document, so every statement keeps its "
        "source numbers. Export is refused while a locked check fails.</p>"
    )
    md(basis_pill(r.report.evidence_basis))
    c1, c2 = st.columns(2)
    fmts = c1.multiselect(
        "Formats",
        ["docx", "pptx", "pdf", "md", "xlsx"],
        default=["docx", "pptx", "pdf"],
        format_func=lambda f: {
            "docx": "Word",
            "pptx": "Slides (PowerPoint)",
            "pdf": "PDF",
            "md": "Markdown",
            "xlsx": "Excel evidence pack",
        }[f],
    )
    scope = c2.radio(
        "Scope",
        ["one_page", "decision_brief", "full", "custom"],
        index=1,
        horizontal=True,
        format_func=lambda s: s.replace("_", " ").capitalize(),
    )
    sections = None
    if scope == "custom":
        sections = st.multiselect(
            "Sections",
            list(r.report.sections),
            default=list(r.report.sections)[:5],
            format_func=lambda k: TITLES.get(k, k),
        )
    conf = st.radio(
        "Statements from your uploads",
        ["mark", "remove"],
        horizontal=True,
        format_func=lambda x: "keep and mark confidential" if x == "mark" else "leave out",
    )
    if r.cfg.approvals.review_before_export:
        if not st.checkbox("I have reviewed this report (the profile asks for review before export)"):
            return
    if st.button("Create files", type="primary"):
        out = ws() / "exports" / r.report.run_id
        made = []
        try:
            for f in fmts:
                name = scope if scope != "full" else "report"
                made.append(
                    export(
                        r.report,
                        r.store,
                        f,
                        out / f"{name}.{f}",
                        scope="full" if scope == "custom" else scope,
                        sections=sections,
                        confidential=conf,
                        flag_after=r.cfg.evidence.flag_after_years,
                    )
                )
        except ExportBlocked as exc:
            st.error(str(exc))
        for p in made:
            st.download_button(f"Download {p.name}", p.read_bytes(), file_name=p.name, key=str(p))


def page_settings() -> None:
    st.title("Agent settings")
    md(
        "<p class='bfa-sub'>Profiles set how strict the agent is. Three things are locked in every profile: "
        "the model's "
        "own knowledge is never a source; citations, grounding and number checks always run; every run saves a "
        "manifest.</p>"
    )
    names = profiles()
    if "profile_pick" not in ss():
        ss().profile_pick = ss().profile
    st.selectbox("Profile", names, key="profile_pick")
    ss().profile = ss().profile_pick
    c = load_config(ss().profile, ss().overrides)
    with st.form("settings_form"):
        md("<div class='bfa-lbl'>Evidence</div>")
        a, b, d = st.columns(3)
        pol = ["primary_only", "primary_then_secondary_on_request", "primary_then_secondary_for_gaps"]
        policy = a.selectbox(
            "Evidence policy", pol, index=pol.index(c.evidence.policy), format_func=lambda x: x.replace("_", " ")
        )
        fmin = b.number_input("Facts a key finding needs", 2, 10, c.evidence.finding_min_facts)
        kmin = d.number_input("Kinds of source a finding needs", 1, 5, c.evidence.finding_min_kinds)
        bmin = a.number_input("Independent sources a block needs", 1, 5, c.evidence.block_min_facts)
        flag = b.number_input("Flag facts older than (years)", 1, 20, c.evidence.flag_after_years)
        excl = d.number_input("Exclude facts older than (years)", 2, 50, c.evidence.exclude_after_years)
        st.text_input("Model knowledge as a source 🔒", "never", disabled=True)
        md("<div class='bfa-lbl'>Scope and drift</div>")
        a, b = st.columns(2)
        offp = a.selectbox(
            "Off-plan searches",
            ["block", "ask", "allow"],
            index=["block", "ask", "allow"].index(c.scope.off_plan_queries),
        )
        oos = b.selectbox(
            "Out-of-scope facts", ["set_aside", "drop"], index=["set_aside", "drop"].index(c.scope.out_of_scope)
        )
        md("<div class='bfa-lbl'>Spend caps</div>")
        a, b, d = st.columns(3)
        ws_ = a.number_input("Web searches", 0, 500, c.limits.web_searches)
        sec_ = b.number_input("Secondary searches", 0, 500, c.limits.secondary_searches)
        fet = d.number_input("Fetches", 0, 2000, c.limits.fetches)
        md("<div class='bfa-lbl'>Approvals</div>")
        a, b, d = st.columns(3)
        ap_plan = a.checkbox("Approve the plan before running", c.approvals.plan)
        ap_sec = b.checkbox("Approve each secondary search", c.approvals.secondary_search)
        ap_rev = d.checkbox("Review before export", c.approvals.review_before_export)
        md("<div class='bfa-lbl'>Sources</div>")
        conns = [
            "openfda",
            "clinicaltrials",
            "pubmed",
            "openalex",
            "worldbank",
            "sec_edgar",
            "patentsview",
            "claude_web",
            "gdelt",
            "claude_web_open",
        ]
        on = st.multiselect("Connectors switched on", conns, default=[x for x in conns if c.connector_on(x)])
        domains = st.text_area("Official domains for the primary web search", "\n".join(c.sources.official_domains))
        md("<div class='bfa-lbl'>Checks</div>")
        optional = ["scope", "policy", "gaps", "agreement", "findings", "injection", "budget"]
        st.multiselect("Locked checks 🔒", list(LOCKED_CHECKS), default=list(LOCKED_CHECKS), disabled=True)
        chk = st.multiselect("Other checks", optional, default=[x for x in c.checks if x in optional])
        md("<div class='bfa-lbl'>Models (pinned)</div>")
        a, b, d = st.columns(3)
        planner = a.text_input("Planner", c.models.planner)
        writer = b.text_input("Writer", c.models.writer)
        researcher = d.text_input("Web search (researcher)", c.models.researcher)
        st.caption(
            "No temperature setting: Claude Opus 5.5 fixes sampling. Runs repeat exactly through record and replay."
        )
        saved = st.form_submit_button("Apply settings", type="primary")
    if saved:
        ss().overrides = {
            "evidence": {
                "policy": policy,
                "finding_min_facts": int(fmin),
                "finding_min_kinds": int(kmin),
                "block_min_facts": int(bmin),
                "flag_after_years": int(flag),
                "exclude_after_years": int(excl),
            },
            "scope": {"off_plan_queries": offp, "out_of_scope": oos},
            "limits": {"web_searches": int(ws_), "secondary_searches": int(sec_), "fetches": int(fet)},
            "approvals": {"plan": ap_plan, "secondary_search": ap_sec, "review_before_export": ap_rev},
            "sources": {
                "enabled": {x: (x in on) for x in conns},
                "official_domains": [x.strip() for x in domains.splitlines() if x.strip()],
            },
            "checks": list(LOCKED_CHECKS) + chk,
            "models": {"planner": planner, "writer": writer, "researcher": researcher},
        }
        ss().plan = None
        st.success("Applied. New runs use these settings; the run manifest records them.")
    y = to_yaml(load_config(ss().profile, ss().overrides))
    with st.expander("Settings as YAML (save as a profile in config/profiles/)"):
        st.code(y, language="yaml")
        st.download_button("Download profile", y, file_name=f"{ss().profile}-custom.yaml")


# ====================================================================== main
init()
sidebar()
{
    "New analysis": page_new,
    "Plan and run": page_plan,
    "Report": page_report,
    "Frameworks": page_frameworks,
    "Evidence": page_evidence,
    "Secondary search": page_secondary,
    "Export": page_export,
    "Agent settings": page_settings,
}[ss().nav]()
md(
    "<p class='src' style='margin-top:24px'>Demo data: openFDA records recorded on 25 Nov 2026 (real) and two "
    "fictional "
    "sample uploads (Example Diagnostics, Lumen Slide Systems). Not advice; check the sources.</p>"
)
