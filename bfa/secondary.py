"""Optional secondary search, only when you ask for it.

The primary report is finished first. A secondary search then serves only the questions
you pick: the report's open questions, chosen sections, or your own questions. It is a
plan amendment you approve; the query gate checks every search against it. Everything it
finds is labelled secondary (tier B or C), and the report can be rebuilt with or without it.
Secondary facts never replace primary ones and never feed the executive summary's figures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from bfa.checks import run_checks
from bfa.config import AgentConfig
from bfa.connectors.base import Http
from bfa.governance.budget import Budget
from bfa.governance.gate import QueryGate
from bfa.governance.scope import ScopeLock
from bfa.pipeline import Run, build_report, gather, save
from bfa.planner import secondary_questions, select_topic
from bfa.schemas import ConnectorQuery, Plan, now_iso


@dataclass
class SecondaryRequest:
    gaps: list[str] = field(default_factory=list)  # open questions to work on
    sections: list[str] = field(default_factory=list)  # sections to add secondary evidence to
    own: list[str] = field(default_factory=list)  # your own questions
    connectors: list[str] = field(default_factory=lambda: ["gdelt", "claude_web_open"])
    max_searches: int = 10


def amend_plan(plan: Plan, req: SecondaryRequest) -> Plan:
    """Add the secondary questions and their queries to a copy of the plan. You approve the copy."""
    new = plan.model_copy(deep=True)
    qs = secondary_questions(plan, req.gaps, req.sections, req.own)
    new.questions += qs
    _, _, topic = select_topic_from_plan(plan)
    for q in qs:
        q.connectors = [c for c in q.connectors if c in req.connectors]
        if "gdelt" in q.connectors:
            query = topic.get("gdelt_query") or f'"{plan.keywords[0]}"'
            new.queries.append(
                ConnectorQuery(
                    connector="gdelt",
                    question_id=q.id,
                    text=f"{query} news: {q.text[:80]}",
                    params={"query": query, "timespan": "3m"},
                )
            )
        if "claude_web_open" in q.connectors:
            new.queries.append(
                ConnectorQuery(
                    connector="claude_web_open",
                    question_id=q.id,
                    text=q.text,
                    params={"question": q.text, "primary": False},
                )
            )
    for fw, questions in topic.get("web_questions_secondary", {}).items():
        qid = f"Q-sec-{fw}"
        if qid in {q.id for q in qs} and "claude_web_open" in req.connectors:
            for wq in questions:
                new.queries.append(
                    ConnectorQuery(
                        connector="claude_web_open", question_id=qid, text=wq, params={"question": wq, "primary": False}
                    )
                )
    # one GDELT call per run is enough: the same query serves every question
    seen, queries = set(), []
    for q in new.queries:
        k = (q.connector, q.key())
        if q.connector == "gdelt" and k in seen:
            continue
        seen.add(k)
        queries.append(q)
    new.queries = queries
    new.approved, new.approved_at = False, ""
    return new


def select_topic_from_plan(plan: Plan):
    from bfa.schemas import Brief

    return select_topic(Brief(field=plan.field))


def run_secondary(
    base: Run,
    req: SecondaryRequest,
    *,
    mode: str = "replay",
    snapshot: str | None = None,
    client=None,
    approve: bool = False,
    today: date | None = None,
) -> Run:
    cfg: AgentConfig = base.cfg
    if not cfg.secondary_allowed():
        raise PermissionError("This profile's evidence policy is primary only; secondary search is switched off.")
    if cfg.approvals.secondary_search and not approve:
        raise PermissionError("A secondary search needs your approval (approvals.secondary_search is on).")
    amended = amend_plan(base.plan, req)
    amended.approved, amended.approved_at = True, now_iso()
    new_q = [q for q in amended.queries if q.question_id.startswith("Q-sec")][: req.max_searches]
    work = amended.model_copy(update={"queries": new_q})
    snapshot = snapshot or (base.store.get("gather_log") or {}).get("snapshot", "default")
    http = Http(mode=mode, snapshot=snapshot)
    budget = Budget(cfg.limits)
    gate = QueryGate(work, mode=cfg.scope.off_plan_queries)
    lock = ScopeLock(work, cfg.evidence.exclude_after_years, today)
    log = gather(work, cfg, base.store, http, budget, gate, lock, client)
    log["snapshot"], log["mode"], log["secondary"] = snapshot, mode, True
    report, critic = build_report(
        base.store,
        amended,
        base.report.brief,
        cfg,
        base.report.run_id,
        include_secondary=True,
        today=today,
        fictional=base.report.fictional,
    )
    report.checks = run_checks(
        report,
        base.store,
        cfg,
        critic,
        budget.as_dict(),
        blocked=len(gate.blocked),
        set_aside=base.store.counts()["set_aside"],
    )
    manifest = base.manifest.model_copy(deep=True)
    manifest.evidence_basis = report.evidence_basis
    manifest.blocked_queries += gate.blocked
    manifest.set_aside += log["set_aside"]
    manifest.checks = report.checks
    manifest.budget = {"primary": base.manifest.budget, "secondary": budget.as_dict()}
    manifest.tool_calls += [
        {"connector": c["connector"], "url": c["url"], "mode": c["mode"], "fetched": c["fetched"], "secondary": True}
        for c in http.calls
    ]
    base.store.set("secondary_log", log)
    folder = base.folder / "with-secondary"
    folder.mkdir(exist_ok=True)
    save(folder, report, manifest, amended, cfg, log)
    return Run(
        report=report,
        manifest=manifest,
        store=base.store,
        folder=folder,
        plan=amended,
        cfg=cfg,
        removed=critic.removed,
        skipped=log["skipped"],
    )


def toggle(base: Run, include_secondary: bool, today: date | None = None) -> Run:
    """Rebuild the report from the same store with secondary evidence included or excluded."""
    report, critic = build_report(
        base.store,
        base.plan,
        base.report.brief,
        base.cfg,
        base.report.run_id,
        include_secondary=include_secondary,
        today=today,
        fictional=base.report.fictional,
    )
    b = base.manifest.budget or {}
    b = b if "caps" in b else b.get("secondary", {})
    report.checks = run_checks(
        report,
        base.store,
        base.cfg,
        critic,
        b,
        blocked=len(base.manifest.blocked_queries),
        set_aside=base.store.counts()["set_aside"],
    )
    return Run(
        report=report,
        manifest=base.manifest,
        store=base.store,
        folder=base.folder,
        plan=base.plan,
        cfg=base.cfg,
        removed=critic.removed,
        skipped=base.skipped,
    )


__all__ = ["SecondaryRequest", "amend_plan", "run_secondary", "toggle"]
