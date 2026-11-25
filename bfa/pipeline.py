"""The run, in seven steps, with the governance switched in at each one.

1 plan       brief -> plan (Claude may propose vocabulary); you approve; the scope locks
2 gather     each planned query passes the query gate and the budget, then a connector
3 clean      sources are sanitised; facts outside the locked scope are set aside
4 analyse    framework builders read only stored facts; numbers come from the calculator
5 write      deterministic statements, or Claude rewrites them within the same facts
6 check      the critic removes failing statements; ten rules are recorded
7 manifest   everything needed to repeat the run is saved; the replay test compares fact hashes
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from bfa.checks import Critic, locked_failures, run_checks
from bfa.config import WORKSPACE, AgentConfig, load_config
from bfa.connectors.base import SNAPSHOT_DIR, ConnectorError, Http, SnapshotMissing
from bfa.connectors.registry import build as build_connectors
from bfa.connectors.registry import is_secondary
from bfa.frameworks import analyse
from bfa.frameworks.base import Ctx, finish
from bfa.frameworks.synthesis import summary as write_summary
from bfa.governance.budget import Budget, BudgetExceeded
from bfa.governance.gate import QueryGate
from bfa.governance.scope import ScopeLock
from bfa.ingest.uploads import parse as parse_upload
from bfa.ingest.uploads import to_evidence
from bfa.planner import approve, build_plan
from bfa.schemas import Brief, Fact, Plan, Report, RunManifest, Source, now_iso, short_hash

Step = Callable[[str, str], None]


@dataclass
class Run:
    report: Report
    manifest: RunManifest
    store: object
    folder: Path
    plan: Plan
    cfg: AgentConfig
    removed: list = field(default_factory=list)
    skipped: list = field(default_factory=list)

    @property
    def blocked_export(self) -> list:
        return locked_failures(self.report.checks)


def snapshot_is_fictional(snapshot: str) -> bool:
    meta = SNAPSHOT_DIR / snapshot / "meta.json"
    if meta.exists():
        return bool(json.loads(meta.read_text()).get("fictional"))
    return "fictional" in snapshot


def _noop(step: str, msg: str) -> None:
    pass


def store_assumptions(store, plan: Plan) -> list[Fact]:
    """Your assumptions become user facts (tier U, kind 'user'), so the report can cite them and say whose they are."""
    if not plan.assumptions:
        return []
    src = Source(
        id="brief-assumptions",
        connector="brief",
        basis="primary",
        tier="U",
        kind="user",
        title="Your assumptions (from the brief)",
        url="brief://assumptions",
        publisher="you",
        fetched=now_iso(),
    )
    store.add_source(src)
    out = []
    for a in plan.assumptions:
        unit = a.get("unit", "")
        val = a.get("value")
        claim = f"Assumption {a['id']} (yours): {a['text']}"
        f = Fact(
            id=f"ASM-{a['id']}",
            source_id=src.id,
            claim=claim,
            metric=a.get("metric", ""),
            value=float(val) if val is not None else None,
            unit=unit,
            basis="primary",
            tier="U",
            kind="user",
            topics=["assumption"],
            location=f"brief assumption {a['id']}",
            as_of=src.fetched[:10],
        )
        store.add_fact(f)
        out.append(f)
    return out


def gather(
    plan: Plan,
    cfg: AgentConfig,
    store,
    http: Http,
    budget: Budget,
    gate: QueryGate,
    lock: ScopeLock,
    client=None,
    fictional: bool = False,
    on_step: Step = _noop,
    connectors: dict | None = None,
) -> dict:
    """Steps 2 and 3. Returns a summary of what happened per connector."""
    conns = connectors or build_connectors(cfg, http, client)
    log = {"calls": 0, "skipped": [], "set_aside": [], "by_connector": {}}
    for q in plan.queries:
        ok, why = gate.check(q)
        if not ok:
            store.log_blocked(gate.blocked[-1])
            on_step("gather", f"blocked: {q.text} ({why})")
            continue
        conn = conns.get(q.connector)
        if conn is None:
            log["skipped"].append(f"{q.text}: connector {q.connector} is switched off")
            continue
        avail, hint = conn.available()
        if not avail:
            log["skipped"].append(f"{q.text}: {hint}")
            continue
        kind = (
            "secondary_searches"
            if is_secondary(q.connector)
            else "web_searches"
            if q.connector.startswith("claude_web")
            else "fetches"
        )
        try:
            budget.spend(kind, 1, q.text)
            res = conn.run(q)
        except BudgetExceeded as exc:
            log["skipped"].append(f"{q.text}: {exc}")
            continue
        except SnapshotMissing:
            budget.used[kind] -= 1  # nothing was called, nothing spent
            log["skipped"].append(f"{q.text}: not in the snapshot; run `make record` with network access")
            continue
        except ConnectorError as exc:
            log["skipped"].append(f"{q.text}: {exc}")
            continue
        log["calls"] += 1
        stats = log["by_connector"].setdefault(q.connector, {"queries": 0, "sources": 0, "facts": 0, "set_aside": 0})
        stats["queries"] += 1
        for s in res.sources:
            s.fictional = s.fictional or fictional
            store.add_source(s)
            stats["sources"] += 1
        for f in res.facts[: cfg.limits.records_per_query * 4]:
            inside, note = lock.check(f, res.targeted)
            f.in_scope, f.scope_note = inside, note
            if not inside:
                log["set_aside"].append(
                    {"fact": f.id, "claim": f.claim[:160], "reason": note, "connector": q.connector}
                )
                stats["set_aside"] += 1
                if cfg.scope.out_of_scope == "drop":
                    continue
            store.add_fact(f)
            stats["facts"] += int(inside)
        store.log_call("gather", q.connector, {"q": q.text, "question": q.question_id}, res.note or "ok", now_iso())
        on_step("gather", f"{q.connector}: {q.text} -> {len(res.facts)} facts")
    return log


def ingest_uploads(uploads: list[tuple], plan: Plan, store, lock: ScopeLock, fictional: bool = False) -> list[dict]:
    out = []
    for item in uploads:
        path, basis = item[0], item[1]
        fictional = item[2] if len(item) > 2 else fictional  # (path, basis[, fictional sample])
        parsed = parse_upload(path)
        terms = {s["id"]: s["terms"] for s in plan.segments} if plan.segments else None
        extra = {f"segment:{k}": v for k, v in (terms or {}).items()}
        src, facts = to_evidence(parsed, basis, plan.scope_terms, fictional=fictional, extra_topics=extra or None)
        store.add_source(src)
        kept = 0
        for f in facts:
            inside, note = lock.check(f, targeted=False)
            f.in_scope, f.scope_note = inside, note
            store.add_fact(f)
            kept += int(inside)
        out.append(
            {
                "file": parsed.name,
                "basis": basis,
                "passages": len(parsed.passages),
                "facts": kept,
                "quarantined": len(parsed.quarantined),
                "source": src.id,
                "fictional": fictional,
                "path": str(path),
            }
        )
    return out


def build_report(
    store,
    plan: Plan,
    brief: Brief,
    cfg: AgentConfig,
    run_id: str,
    include_secondary: bool,
    engine: str = "deterministic",
    writer=None,
    today: date | None = None,
    fictional: bool = False,
) -> tuple[Report, Critic]:
    """Steps 4 to 6 from what is already in the store. The include/exclude-secondary switch calls this again."""
    ctx = Ctx(
        store=store, plan=plan, brief=brief, cfg=cfg, include_secondary=include_secondary, today=today or date.today()
    )
    frameworks = list(dict.fromkeys(q.framework for q in plan.questions if q.framework != "user"))
    sections, found = analyse(ctx, frameworks)
    stmts, verdict, basis, gaps = write_summary(ctx, found)
    has_secondary = include_secondary and any(f.basis == "secondary" for f in ctx.facts)
    report = Report(
        run_id=run_id,
        brief=brief,
        plan=plan,
        title=f"Business field analysis: {short_field(brief.field)}",
        evidence_basis="primary_secondary" if has_secondary else "primary_only",
        summary=stmts,
        verdict=verdict,
        verdict_basis=basis,
        sections=sections,
        findings=found,
        open_questions=gaps,
        fictional=fictional,
    )
    critic = Critic(store=store, cfg=cfg, basis=report.evidence_basis, engine="deterministic")
    if engine == "claude" and writer is not None:
        writer.critic = critic
        writer.rewrite(report)
    critic.review(report)
    for sec in report.sections.values():
        finish(sec)
    report.open_questions = list(dict.fromkeys(q for s in report.sections.values() for q in s.open_questions))
    return report, critic


def short_field(field_text: str) -> str:
    return field_text.split(":")[0].strip()


def run(
    brief: Brief,
    cfg: AgentConfig | None = None,
    *,
    mode: str = "replay",
    snapshot: str = "digital-pathology-real",
    engine: str = "deterministic",
    uploads: list[tuple] | None = None,
    plan: Plan | None = None,
    auto_approve: bool = False,
    client=None,
    today: date | None = None,
    workspace: Path | None = None,
    on_step: Step = _noop,
    run_id: str | None = None,
) -> Run:
    cfg = cfg or load_config()
    today = today or date.today()
    fictional = snapshot_is_fictional(snapshot)
    http = Http(mode=mode, snapshot=snapshot)
    budget = Budget(cfg.limits)
    caller = None
    # 1 plan
    plan = plan or build_plan(brief, cfg, today)
    if engine == "claude" and not plan.approved:
        from bfa.engines.claude import ClaudeCaller, ClaudePlanner, merge_proposal

        caller = ClaudeCaller(http, client, budget, slot="claude_planner")
        try:
            plan = merge_proposal(plan, ClaudePlanner(cfg, caller).propose(brief, plan))
        except (SnapshotMissing, RuntimeError) as exc:
            on_step("plan", f"Claude planner skipped: {exc}")
    if not plan.approved:
        if cfg.approvals.plan and not auto_approve:
            raise PermissionError("The plan needs your approval before the run (approvals.plan is on).")
        plan = approve(plan)
    on_step("plan", f"plan {plan.key()} approved: {len(plan.questions)} questions, {len(plan.queries)} queries")
    run_id = run_id or f"{today.isoformat()}-{short_hash([brief.key(), plan.key(), cfg.key(), engine, snapshot], 6)}"
    folder = (workspace or WORKSPACE) / "runs" / run_id
    folder.mkdir(parents=True, exist_ok=True)
    db = folder / "evidence.db"
    for stale in (db, *(db.with_name(db.name + s) for s in ("-journal", "-wal", "-shm"))):
        stale.unlink(missing_ok=True)  # a leftover journal from an interrupted run would corrupt the new file
    from bfa.store import Store

    store = Store(db)
    gate = QueryGate(plan, mode=cfg.scope.off_plan_queries, require_approval=True)
    lock = ScopeLock(plan, cfg.evidence.exclude_after_years, today)
    store_assumptions(store, plan)
    up = ingest_uploads(uploads or [], plan, store, lock, fictional=False)
    store.set("uploads", up)
    # 2-3 gather and clean
    log = gather(plan, cfg, store, http, budget, gate, lock, client, fictional, on_step)
    log["snapshot"], log["mode"], log["uploads"] = snapshot, mode, up
    evidence_hash = store.fact_hash()
    store.set("gather_log", log)
    # 4-6 analyse, write, check
    writer = None
    if engine == "claude":
        from bfa.engines.claude import ClaudeCaller, ClaudeWriter

        caller = caller or ClaudeCaller(http, client, budget)
        caller.slot = "claude_writer"
        writer = ClaudeWriter(cfg, caller, None)
    report, critic = build_report(
        store,
        plan,
        brief,
        cfg,
        run_id,
        include_secondary=False,
        engine=engine,
        writer=writer,
        today=today,
        fictional=fictional,
    )
    checks = run_checks(
        report, store, cfg, critic, budget.as_dict(), blocked=len(gate.blocked), set_aside=store.counts()["set_aside"]
    )
    report.checks = checks
    # 7 manifest
    snaps = {c: ("fictional" if fictional else http.snapshot_date(c) or mode) for c in log["by_connector"]}
    manifest = RunManifest(
        run_id=run_id,
        brief_key=brief.key(),
        plan_key=plan.key(),
        profile=cfg.profile,
        config_hash=cfg.key(),
        engine=engine,
        evidence_basis=report.evidence_basis,
        models=cfg.models.model_dump() if engine == "claude" else {},
        prompt_version=_prompt_version(engine),
        snapshots=snaps,
        tool_calls=[
            {"connector": c["connector"], "url": c["url"], "mode": c["mode"], "fetched": c["fetched"]}
            for c in http.calls
        ]
        + ([{"connector": "claude", **c} for c in caller.calls] if caller else []),
        blocked_queries=gate.blocked,
        set_aside=log["set_aside"],
        checks=checks,
        budget=budget.as_dict(),
        fact_hash=evidence_hash,
        fictional=fictional,
    )
    save(folder, report, manifest, plan, cfg, log)
    on_step(
        "done",
        f"report {run_id}: {len(report.all_statements())} statements, "
        f"{sum(c.passed for c in checks)}/{len(checks)} checks passed",
    )
    return Run(
        report=report,
        manifest=manifest,
        store=store,
        folder=folder,
        plan=plan,
        cfg=cfg,
        removed=critic.removed,
        skipped=log["skipped"],
    )


def _prompt_version(engine: str) -> str:
    if engine != "claude":
        return "deterministic"
    from bfa.engines.claude import PROMPT_VERSION

    return PROMPT_VERSION


def save(folder: Path, report: Report, manifest: RunManifest, plan: Plan, cfg: AgentConfig, log: dict) -> None:
    from bfa.config import to_yaml

    (folder / "report.json").write_text(report.model_dump_json(indent=1))
    (folder / "manifest.json").write_text(manifest.model_dump_json(indent=1))
    (folder / "plan.json").write_text(plan.model_dump_json(indent=1))
    (folder / "settings.yaml").write_text(to_yaml(cfg))
    (folder / "gather_log.json").write_text(json.dumps(log, indent=1, default=str))


def load_run(folder: Path) -> tuple[Report, RunManifest]:
    return (
        Report.model_validate_json((folder / "report.json").read_text()),
        RunManifest.model_validate_json((folder / "manifest.json").read_text()),
    )


def replay_test(folder: Path, cfg: AgentConfig | None = None, workspace: Path | None = None) -> dict:
    """Re-run a saved run from its snapshot and compare the evidence hash (drift check)."""
    report, manifest = load_run(folder)
    plan = Plan.model_validate_json((folder / "plan.json").read_text())
    cfg = cfg or AgentConfig.model_validate(__import__("yaml").safe_load((folder / "settings.yaml").read_text()))
    snapshot = json.loads((folder / "gather_log.json").read_text()).get("snapshot") or _guess_snapshot(manifest)
    log = json.loads((folder / "gather_log.json").read_text())
    uploads = [(u["path"], u["basis"], u.get("fictional", False)) for u in log.get("uploads", []) if u.get("path")]
    again = run(
        report.brief,
        cfg,
        mode="replay",
        snapshot=snapshot,
        engine=manifest.engine,
        plan=plan,
        uploads=uploads,
        today=date.fromisoformat(report.created[:10]),
        workspace=workspace or folder.parent.parent / "replays",
        run_id=manifest.run_id,
    )
    same = again.manifest.fact_hash == manifest.fact_hash
    stmts_a = [s.text for s in report.all_statements()]
    stmts_b = [s.text for s in again.report.all_statements()]
    return {
        "same_evidence": same,
        "fact_hash": manifest.fact_hash,
        "replay_hash": again.manifest.fact_hash,
        "same_statements": stmts_a == stmts_b,
        "statements": len(stmts_a),
    }


def _guess_snapshot(manifest: RunManifest) -> str:
    return "digital-pathology-fictional" if manifest.fictional else "digital-pathology-real"


__all__ = [
    "run",
    "build_report",
    "gather",
    "ingest_uploads",
    "load_run",
    "open_run",
    "replay_test",
    "Run",
    "store_assumptions",
]


def open_run(folder: Path) -> Run:
    """Re-open a saved run (report, manifest, plan, settings and evidence store) from its folder."""
    import yaml

    from bfa.store import Store

    folder = Path(folder)
    report, manifest = load_run(folder)
    plan = Plan.model_validate_json((folder / "plan.json").read_text())
    cfg = AgentConfig.model_validate(yaml.safe_load((folder / "settings.yaml").read_text()))
    db = folder / "evidence.db"
    if not db.exists():
        db = folder.parent / "evidence.db"  # a with-secondary folder shares the run's store
    store = Store(db)
    log = json.loads((folder / "gather_log.json").read_text()) if (folder / "gather_log.json").exists() else {}
    return Run(
        report=report, manifest=manifest, store=store, folder=folder, plan=plan, cfg=cfg, skipped=log.get("skipped", [])
    )
