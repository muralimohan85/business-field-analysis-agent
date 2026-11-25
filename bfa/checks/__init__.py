"""The checks (the "critic"). They run after analysis and before anything is exported.

Statement-level checks remove any statement that fails them (citations, numbers,
grounding, injection, policy) and the block says what was removed. Report-level checks
then record the result of each rule in the run manifest. Three checks are locked on in
every profile: citations, grounding and numbers. Export is refused while a locked check fails.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bfa.calc import fmt_num
from bfa.config import LOCKED_CHECKS, AgentConfig
from bfa.safety.sanitizer import is_injection
from bfa.schemas import CheckResult, Fact, Report, Statement
from bfa.store import Store

RULES = {
    "citations": 1,
    "grounding": 1,
    "numbers": 2,
    "gaps": 4,
    "findings": 4,
    "agreement": 5,
    "injection": 6,
    "policy": 8,
    "budget": 9,
    "scope": 10,
}
NAMES = {
    "citations": "Every statement cites a source",
    "grounding": "Statements say only what their sources say",
    "numbers": "Every number traces to a cited fact or the calculator; estimates never averaged",
    "gaps": "Thin evidence is shown as a gap",
    "findings": "Findings meet the evidence threshold",
    "agreement": "Frameworks agree with each other",
    "injection": "No instruction from a source reached the report",
    "policy": "Evidence basis, tier and age respected",
    "budget": "Spend stayed within the caps",
    "scope": "Only in-scope evidence is cited; off-plan queries blocked",
}

_NUM = re.compile(r"(?<![A-Za-z0-9\-.])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(?![A-Za-z0-9]|\(k\))")
_WORD = re.compile(r"[a-zA-Z][a-zA-Z\-]{3,}")
STOP = set(
    """this that with from were have been their there which about into than then they them these those
also more most over such only each when what where while will would could should after before under above
between through during within without across other some many much very here year years this run data shows
shown fact facts source sources records record lists listed includes include""".split()
)
AVERAGE = re.compile(r"\b(average|mean|consensus|blended)\b[^.]{0,60}\b(estimate|market|size)", re.I)


def numbers(text: str) -> list[float]:
    out = []
    for m in _NUM.finditer(text or ""):
        whole = m.group(1).replace(",", "")
        out.append(float(whole + ("." + m.group(2) if m.group(2) else "")))
    return out


def _fact_numbers(f: Fact) -> set[float]:
    vals = set(numbers(f.claim)) | set(numbers(f.entity))
    if f.value is not None:
        vals.add(round(float(f.value), 6))
        vals |= set(numbers(fmt_num(f.value, f.unit)))
        vals |= set(numbers(fmt_num(f.value)))
    if f.year:
        vals.add(float(f.year))
    return vals


def _close(a: float, pool: set[float]) -> bool:
    return any(abs(a - b) <= max(0.051, abs(b) * 0.005) for b in pool)


def _content(text: str) -> set[str]:
    return {w.lower().rstrip("s") for w in _WORD.findall(text or "") if w.lower() not in STOP}


@dataclass
class Removal:
    section: str
    block: str
    text: str
    reason: str
    check: str


@dataclass
class Critic:
    store: Store
    cfg: AgentConfig
    basis: str = "primary_only"
    engine: str = "deterministic"
    removed: list[Removal] = field(default_factory=list)

    # ---- statement-level -------------------------------------------------
    def why_not(self, s: Statement) -> tuple[str, str]:
        """('', '') if the statement passes; otherwise (check, reason)."""
        if not s.fact_ids:
            return "citations", "no citation"
        facts = [self.store.fact(i) for i in s.fact_ids]
        if any(f is None for f in facts):
            return "citations", "cites a fact that does not exist"
        if is_injection(s.text):
            return "injection", "reads like an instruction from a source"
        if self.basis == "primary_only" and any(f.basis == "secondary" for f in facts):
            return "policy", "cites a secondary source in a primary-only report"
        if any(not f.in_scope for f in facts):
            return "scope", "cites a fact set aside by the scope lock"
        pool = set().union(*(_fact_numbers(f) for f in facts))
        for f in facts:  # calculated facts carry their inputs' numbers too
            for i in f.inputs:
                g = self.store.fact(i)
                if g:
                    pool |= _fact_numbers(g)
        for n in numbers(s.text):
            if not _close(n, pool):
                return "numbers", f"the number {fmt_num(n)} is not in any cited fact"
        if AVERAGE.search(s.text):
            return "numbers", "averages market estimates (rule 3: side by side, never averaged)"
        claims = " ".join(f.claim + " " + f.entity for f in facts)
        if s.text.strip() in claims:
            return "", ""
        if not s.judgement or self.engine != "deterministic":
            words = _content(s.text)
            have = _content(claims)
            if words:
                overlap = len(words & have) / len(words)
                need = 0.6 if not s.judgement else 0.3
                if overlap < need:
                    return "grounding", f"only {overlap:.0%} of its terms appear in the cited facts"
        return "", ""

    def review(self, report: Report) -> Report:
        for key, sec in report.sections.items():
            for b in sec.blocks:
                keep = []
                for s in b.statements:
                    check, reason = self.why_not(s)
                    if check:
                        self.removed.append(Removal(key, b.key, s.text, reason, check))
                    else:
                        keep.append(s)
                if len(keep) < len(b.statements):
                    n = len(b.statements) - len(keep)
                    b.data["removed_by_checks"] = n
                    if not keep and not b.gap:
                        b.gap = (
                            f"{n} statement{'s' if n > 1 else ''} removed by the checks; no grounded statement left."
                        )
                b.statements = keep
        keep = []
        for s in report.summary:
            check, reason = self.why_not(s)
            if check:
                self.removed.append(Removal("summary", "summary", s.text, reason, check))
            else:
                keep.append(s)
        report.summary = keep
        return report


# ---- report-level ---------------------------------------------------------
def _result(name: str, passed: bool, detail: str, count: int = 0) -> CheckResult:
    return CheckResult(rule=RULES[name], name=name, passed=passed, detail=detail, count=count)


def run_checks(
    report: Report,
    store: Store,
    cfg: AgentConfig,
    critic: Critic,
    budget: dict | None = None,
    blocked: int = 0,
    set_aside: int = 0,
) -> list[CheckResult]:
    stmts = report.all_statements()
    by_check = {}
    for r in critic.removed:
        by_check.setdefault(r.check, []).append(r)
    out: list[CheckResult] = []
    enabled = set(cfg.checks)

    def removed_detail(name: str, ok_text: str) -> tuple[bool, str, int]:
        rs = by_check.get(name, [])
        if rs:
            return True, f"{len(rs)} statement(s) removed before the report was written; {ok_text}", len(rs)
        return True, ok_text, 0

    # 1 citations
    missing = [s for s in stmts if not s.fact_ids or any(store.fact(i) is None for i in s.fact_ids)]
    ok, d, n = removed_detail("citations", f"all {len(stmts)} statements cite facts")
    out.append(_result("citations", not missing, d if not missing else f"{len(missing)} uncited statement(s)", n))
    # 1 grounding
    bad = [s for s in stmts if critic.why_not(s)[0] == "grounding"]
    ok, d, n = removed_detail("grounding", "every remaining statement is supported by its cited facts")
    out.append(_result("grounding", not bad, d if not bad else f"{len(bad)} unsupported statement(s)", n))
    # 2 numbers
    bad = [s for s in stmts if critic.why_not(s)[0] == "numbers"]
    nums = sum(len(numbers(s.text)) for s in stmts)
    ok, d, n = removed_detail("numbers", f"{nums} numbers traced to cited facts or the calculator")
    out.append(_result("numbers", not bad, d if not bad else f"{len(bad)} untraced number(s)", n))
    # 10 scope
    cited = {i for s in stmts for i in s.fact_ids}
    off = [i for i in cited if (f := store.fact(i)) and not f.in_scope]
    out.append(
        _result(
            "scope",
            not off,
            f"{set_aside} fact(s) set aside, {blocked} off-plan quer(ies) blocked; none cited"
            if not off
            else f"{len(off)} out-of-scope fact(s) cited",
            set_aside + blocked,
        )
    )
    # 8 policy
    facts = [store.fact(i) for i in cited if store.fact(i)]
    sec_cited = [f for f in facts if f.basis == "secondary"]
    stale = [f for f in facts if f.year and f.year < report_year(report) - cfg.evidence.flag_after_years]
    policy_ok = report.evidence_basis == "primary_secondary" or not sec_cited
    out.append(
        _result(
            "policy",
            policy_ok,
            (
                f"basis {report.evidence_basis.replace('_', ' ')}; {len(sec_cited)} secondary fact(s) cited "
                f"(labelled); {len(stale)} fact(s) older than {cfg.evidence.flag_after_years} years flagged"
            )
            if policy_ok
            else f"{len(sec_cited)} secondary fact(s) cited in a primary-only report",
            len(stale),
        )
    )
    # 4 gaps
    unflagged = []
    for key, sec in report.sections.items():
        for b in sec.blocks:
            if not b.statements and not b.gap:
                unflagged.append(f"{key}/{b.key} is empty without saying why")
            elif b.gap and not any(q.startswith(b.title) for q in sec.open_questions):
                unflagged.append(f"{key}/{b.key} gap missing from open questions")
    gaps = sum(1 for sec in report.sections.values() for b in sec.blocks if b.gap)
    out.append(
        _result(
            "gaps",
            not unflagged,
            f"{gaps} gap(s) stated in the report and listed as open questions"
            if not unflagged
            else "; ".join(unflagged[:5]),
            gaps,
        )
    )
    # 4 findings
    mn, mk = cfg.evidence.finding_min_facts, cfg.evidence.finding_min_kinds
    wrong = []
    for k in report.findings:
        fs = [store.fact(i) for i in k.fact_ids if store.fact(i)]
        kinds = {f.kind for f in fs if f.kind != "calculated"}
        if k.strength != "signal" and (len(fs) < min(mn, len(k.fact_ids)) or len(kinds) < mk):
            wrong.append(k.id)
    strong = sum(k.strength == "strong" for k in report.findings)
    out.append(
        _result(
            "findings",
            not wrong,
            f"{len(report.findings)} finding(s), {strong} strong; each meets "
            f"{mn} facts from {mk} kinds or is shown as a signal"
            if not wrong
            else f"findings below threshold: {', '.join(wrong)}",
            len(report.findings),
        )
    )
    # 5 agreement
    problems = []
    swot = report.sections.get("swot")
    if swot:
        ids = {b.key: {i for s in b.statements for i in s.fact_ids} for b in swot.blocks}
        if ids.get("opportunities", set()) & ids.get("threats", set()):
            problems.append("a fact is both an opportunity and a threat")
        if ids.get("strengths", set()) & ids.get("weaknesses", set()):
            problems.append("a fact is both a strength and a weakness")
    rec, opp = report.sections.get("recommendations"), report.sections.get("opportunity")
    if rec and opp and rec.data.get("options"):
        best = max((p["a"] * p["b"] for p in opp.data.get("points", []) if p.get("a")), default=None)
        top = next((o for o in rec.data["options"] if o["recommended"]), None)
        if top and best is not None and top["a"] * top["b"] != best:
            problems.append("the recommended option is not the highest-scored opportunity")
    section_ids = {i for sec in report.sections.values() for i in sec.fact_ids()}
    orphan = [i for s in report.summary for i in s.fact_ids if i not in section_ids]
    if orphan:
        problems.append(f"the summary cites {len(orphan)} fact(s) no section uses")
    out.append(
        _result(
            "agreement",
            not problems,
            "SWOT, opportunities, recommendations and summary agree" if not problems else "; ".join(problems),
            len(problems),
        )
    )
    # 6 injection
    quarantined = sum(len(s.quarantined) for s in store.sources())
    leaked = [s for s in stmts if is_injection(s.text)]
    out.append(
        _result(
            "injection",
            not leaked,
            f"{quarantined} sentence(s) quarantined from sources; none reached the report"
            if not leaked
            else f"{len(leaked)} statement(s) read like instructions",
            quarantined,
        )
    )
    # 9 budget
    b = budget or {}
    over = [k for k, v in (b.get("used") or {}).items() if v > (b.get("caps") or {}).get(k, 10**9)]
    used = ", ".join(f"{k.replace('_', ' ')} {v}/{b['caps'][k]}" for k, v in (b.get("used") or {}).items())
    out.append(
        _result(
            "budget",
            not over,
            (used or "no paid calls") + (f"; skipped: {len(b.get('skipped', []))}" if b.get("skipped") else ""),
            len(b.get("skipped", [])),
        )
    )
    return [r for r in out if r.name in enabled or r.name in LOCKED_CHECKS]


def report_year(report: Report) -> int:
    return int(report.created[:4])


def locked_failures(results: list[CheckResult]) -> list[CheckResult]:
    return [r for r in results if r.name in LOCKED_CHECKS and not r.passed]


__all__ = ["Critic", "run_checks", "locked_failures", "numbers", "RULES", "NAMES"]
