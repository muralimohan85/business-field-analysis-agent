"""The query gate (rule 10): every search must serve a question in the approved plan.

It runs before each tool call. A query that names no plan question, uses a connector
the question did not ask for, drifts off the plan's terms or touches an excluded term
is blocked and logged, or held for your OK if the profile says "ask".
"""

from __future__ import annotations

from bfa.governance.scope import mentions
from bfa.schemas import BlockedQuery, ConnectorQuery, Plan


class QueryGate:
    def __init__(self, plan: Plan, mode: str = "block", require_approval: bool = True):
        self.plan, self.mode, self.require_approval = plan, mode, require_approval
        self.vocab = [t for t in (plan.keywords + plan.scope_terms + plan.companies) if t]
        self.blocked: list[BlockedQuery] = []
        self.allowed_off_plan: list[BlockedQuery] = []

    def _reason(self, q: ConnectorQuery) -> str:
        if self.require_approval and not self.plan.approved:
            return "the plan is not approved yet"
        question = self.plan.question(q.question_id)
        if question is None:
            return "names no question in the approved plan"
        if question.connectors and q.connector not in question.connectors:
            return f"connector {q.connector} was not planned for question {q.question_id}"
        bad = mentions(q.text, self.plan.exclude_terms)
        if bad:
            return f"uses the excluded term '{bad}'"
        if q.params.get("targeted"):
            return ""  # structured lookups by code or id from the plan
        vocab = self.vocab + question.terms
        if vocab and not mentions(q.text, vocab):
            return "shares no term with the plan"
        return ""

    def check(self, q: ConnectorQuery) -> tuple[bool, str]:
        reason = self._reason(q)
        if not reason:
            return True, ""
        rec = BlockedQuery(connector=q.connector, text=q.text, question_id=q.question_id, reason=reason)
        if self.mode == "allow":
            self.allowed_off_plan.append(rec)
            return True, f"off-plan but allowed by profile: {reason}"
        if self.mode == "ask":
            rec.reason = f"held for your approval: {reason}"
        self.blocked.append(rec)
        return False, rec.reason
