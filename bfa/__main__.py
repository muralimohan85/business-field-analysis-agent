"""Command line: python -m bfa <command>

demo        run the digital pathology demo offline and export the report (Word, slides, PDF, Markdown, Excel)
plan        show the research plan for a brief (nothing is fetched)
run         run an analysis: plan, gather, analyse, check, write
record      run live and save every API response as a snapshot, for exact replays later
replay      repeat a saved run from its snapshot and compare the evidence (drift test)
secondary   add an optional secondary search to a saved run (you approve it)
export      export a saved run
settings    print the merged agent settings for a profile
sources     list connectors, their basis and whether they are ready
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import yaml

from bfa.config import ROOT, load_config, profiles, to_yaml
from bfa.schemas import Brief

DEMO = ROOT / "data" / "demo" / "digital_pathology"
DEMO_UPLOADS = [
    (str(DEMO / "uploads" / "example-diagnostics-lab-survey.pdf"), "primary", True),
    (str(DEMO / "uploads" / "lumen-slide-systems-brochure.docx"), "secondary", True),
]


def _brief(path: str) -> Brief:
    return Brief(**yaml.safe_load(Path(path).read_text()))


def _uploads(items: list[str]) -> list[tuple]:
    """--upload path[:primary|secondary[:sample]]"""
    out = []
    for it in items or []:
        parts = it.split(":")
        out.append((parts[0], parts[1] if len(parts) > 1 else "primary", len(parts) > 2 and parts[2] == "sample"))
    return out


def _print_report(r) -> None:
    rep = r.report
    print(f"\n{rep.title}\nVerdict: {rep.verdict}   Evidence basis: {rep.evidence_basis.replace('_', ' ')}")
    print("\nExecutive summary")
    for s in rep.summary:
        print(f"  - {s.text}")
    print("\nChecks")
    for c in rep.checks:
        print(f"  {'pass' if c.passed else 'FAIL'}  rule {c.rule:>2}  {c.name:<12} {c.detail}")
    counts = r.store.counts()
    print(
        f"\nEvidence: {counts['sources']} sources, {counts['facts']} facts in scope "
        f"({counts['primary_facts']} primary, {counts['secondary_facts']} secondary), {counts['set_aside']} set aside, "
        f"{counts['blocked']} queries blocked"
    )
    if r.skipped:
        print(f"Skipped {len(r.skipped)} planned queries (see gather_log.json); first: {r.skipped[0]}")
    print(f"Saved to {r.folder}")


def _export(r, formats: str, out: Path, scope: str, confidential: str) -> None:
    from bfa.report.export import export

    for fmt in [f.strip() for f in formats.split(",") if f.strip()]:
        name = "report" if scope == "full" else scope.replace("_", "-")
        p = export(
            r.report,
            r.store,
            fmt,
            out / f"{name}.{fmt}",
            scope=scope,
            confidential=confidential,
            flag_after=r.cfg.evidence.flag_after_years,
        )
        print(f"  wrote {p}")


def cmd_demo(a) -> int:
    from bfa.pipeline import run

    cfg = load_config(a.profile)
    r = run(
        _brief(str(DEMO / "brief.yaml")),
        cfg,
        mode="replay",
        snapshot="digital-pathology-real",
        engine=a.engine,
        uploads=DEMO_UPLOADS,
        auto_approve=True,
        today=date.fromisoformat(a.today),
    )
    _print_report(r)
    out = Path(a.out)
    print("\nExports")
    _export(r, "md,docx,pptx,pdf,xlsx", out, "full", "mark")
    _export(r, "docx,pdf", out, "decision_brief", "mark")
    _export(r, "pdf", out, "one_page", "mark")
    (out / "manifest.json").write_text(r.manifest.model_dump_json(indent=1))
    return 0


def cmd_plan(a) -> int:
    from bfa.planner import build_plan

    plan = build_plan(_brief(a.brief), load_config(a.profile))
    print(f"Plan {plan.key()} for: {plan.field}")
    print(f"Scope terms: {', '.join(plan.scope_terms)}\nExcluded: {', '.join(plan.exclude_terms) or 'none'}")
    for q in plan.questions:
        n = sum(1 for x in plan.queries if x.question_id == q.id)
        print(f"  {q.id:<22} {n:>2} queries  {q.text}")
    if a.out:
        Path(a.out).write_text(plan.model_dump_json(indent=1))
        print(f"wrote {a.out}")
    return 0


def cmd_run(a) -> int:
    from bfa.pipeline import run
    from bfa.planner import build_plan
    from bfa.schemas import Plan

    cfg = load_config(a.profile)
    brief = _brief(a.brief)
    plan = Plan.model_validate_json(Path(a.plan).read_text()) if a.plan else None
    if not a.yes and cfg.approvals.plan and not (plan and plan.approved):
        p = plan or build_plan(brief, cfg)
        print(
            f"Plan {p.key()}: {len(p.questions)} questions, {len(p.queries)} queries. "
            "Approve it with --yes (or review it with `python -m bfa plan`)."
        )
        return 2
    r = run(
        brief,
        cfg,
        mode=a.mode,
        snapshot=a.snapshot,
        engine=a.engine,
        uploads=_uploads(a.upload),
        plan=plan,
        auto_approve=a.yes,
        on_step=(lambda s, m: print(f"[{s}] {m}")) if a.verbose else (lambda s, m: None),
    )
    _print_report(r)
    if a.export:
        _export(r, a.export, Path(a.out or r.folder / "exports"), a.scope, a.confidential)
    return 1 if r.blocked_export else 0


def cmd_record(a) -> int:
    a.mode, a.snapshot = "record", a.snapshot or f"recorded-{date.today().isoformat()}"
    print(f"Recording live responses into data/snapshots/{a.snapshot}/")
    return cmd_run(a)


def cmd_replay(a) -> int:
    from bfa.pipeline import replay_test

    res = replay_test(Path(a.run))
    print(json.dumps(res, indent=1))
    return 0 if res["same_evidence"] else 1


def cmd_secondary(a) -> int:
    from bfa.pipeline import open_run
    from bfa.secondary import SecondaryRequest, run_secondary

    base = open_run(Path(a.run))
    gaps = base.report.open_questions[: a.gaps] if a.gaps else []
    req = SecondaryRequest(
        gaps=gaps, sections=[s for s in (a.sections or "").split(",") if s], own=a.question or [], max_searches=a.max
    )
    print(
        f"Secondary search on {len(req.gaps)} open questions, sections {req.sections or 'none'}, "
        f"{len(req.own)} own questions"
    )
    r = run_secondary(base, req, mode=a.mode, approve=a.yes)
    _print_report(r)
    return 0


def cmd_export(a) -> int:
    from bfa.pipeline import open_run

    r = open_run(Path(a.run))
    _export(r, a.format, Path(a.out or Path(a.run) / "exports"), a.scope, a.confidential)
    return 0


def cmd_settings(a) -> int:
    print(to_yaml(load_config(a.profile)))
    print(f"# profiles: {', '.join(profiles())}")
    return 0


def cmd_sources(a) -> int:
    from bfa.connectors.base import Http
    from bfa.connectors.registry import build, catalogue

    cfg = load_config(a.profile)
    conns = build(cfg, Http(mode="live"))
    cat = catalogue()
    for cid, meta in cat.items():
        c = conns.get(cid)
        ready = ("ready" if c.available()[0] else c.available()[1]) if c else meta.get("status", "off")
        print(
            f"  {cid:<16} {meta.get('basis', ''):<9} tier {meta.get('tier', ''):<2} {ready:<28} {meta.get('name', '')}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="bfa", description="Business field analysis agent")
    p.add_argument("--profile", default=None, help="settings profile (config/profiles/)")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("demo", help="offline demo with exports")
    d.add_argument("--out", default="examples/digital-pathology")
    d.add_argument("--engine", default="deterministic", choices=["deterministic", "claude"])
    d.add_argument("--today", default="2026-11-25", help="fix the run date so the demo is reproducible")
    d.set_defaults(fn=cmd_demo)

    pl = sub.add_parser("plan", help="show the plan for a brief")
    pl.add_argument("--brief", required=True)
    pl.add_argument("--out")
    pl.set_defaults(fn=cmd_plan)

    for name, fn in (("run", cmd_run), ("record", cmd_record)):
        r = sub.add_parser(name, help=f"{name} an analysis")
        r.add_argument("--brief", required=True)
        r.add_argument("--plan", help="an approved plan.json to use instead of planning again")
        r.add_argument("--engine", default="deterministic", choices=["deterministic", "claude"])
        r.add_argument("--mode", default="replay", choices=["replay", "live", "record"])
        r.add_argument("--snapshot", default="digital-pathology-real" if name == "run" else None)
        r.add_argument("--upload", action="append", help="path[:primary|secondary[:sample]]")
        r.add_argument("--yes", action="store_true", help="approve the plan")
        r.add_argument("--export", default="", help="formats, e.g. docx,pptx,pdf,md,xlsx")
        r.add_argument("--scope", default="full", choices=["full", "decision_brief", "one_page"])
        r.add_argument("--confidential", default="mark", choices=["mark", "remove"])
        r.add_argument("--out")
        r.add_argument("-v", "--verbose", action="store_true")
        r.set_defaults(fn=fn)

    rp = sub.add_parser("replay", help="repeat a saved run and compare evidence")
    rp.add_argument("run", help="run folder, e.g. workspace/runs/<id>")
    rp.set_defaults(fn=cmd_replay)

    s = sub.add_parser("secondary", help="optional secondary search on a saved run")
    s.add_argument("run")
    s.add_argument("--gaps", type=int, default=5, help="how many open questions to search")
    s.add_argument("--sections", default="", help="sections to add secondary evidence to")
    s.add_argument("--question", action="append", help="your own question (repeatable)")
    s.add_argument("--max", type=int, default=10, help="max secondary searches")
    s.add_argument("--mode", default="replay", choices=["replay", "live", "record"])
    s.add_argument("--yes", action="store_true", help="approve the secondary search")
    s.set_defaults(fn=cmd_secondary)

    e = sub.add_parser("export", help="export a saved run")
    e.add_argument("run")
    e.add_argument("--format", default="docx,pptx,pdf")
    e.add_argument("--scope", default="full", choices=["full", "decision_brief", "one_page"])
    e.add_argument("--confidential", default="mark", choices=["mark", "remove"])
    e.add_argument("--out")
    e.set_defaults(fn=cmd_export)

    sub.add_parser("settings", help="print merged settings").set_defaults(fn=cmd_settings)
    sub.add_parser("sources", help="list connectors").set_defaults(fn=cmd_sources)

    a = p.parse_args(argv)
    try:
        return a.fn(a)
    except PermissionError as exc:
        print(f"Stopped: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
