from datetime import date

import pytest

from bfa.config import load_config
from bfa.governance.budget import Budget, BudgetExceeded
from bfa.governance.gate import QueryGate
from bfa.governance.scope import ScopeLock, mentions
from bfa.planner import approve, build_plan
from bfa.schemas import ConnectorQuery, Fact


@pytest.fixture()
def plan(brief, cfg):
    return build_plan(brief, cfg, date(2026, 11, 25))


def test_plan_covers_frameworks(plan):
    ids = {q.id for q in plan.questions}
    assert {"Q-pestle", "Q-market_size", "Q-competitors", "Q-regulatory", "Q-risks"} <= ids
    assert all(q.question_id in ids for q in plan.queries)


def test_gate_needs_approval(plan):
    q = plan.queries[0]
    assert not QueryGate(plan).check(q)[0]
    assert QueryGate(approve(plan)).check(q)[0]


def test_gate_blocks_drift(plan):
    gate = QueryGate(approve(plan))
    off = ConnectorQuery(
        connector="pubmed", question_id="Q-trends", text="crypto mining profitability", params={"term": "crypto"}
    )
    unknown = ConnectorQuery(connector="pubmed", question_id="Q-made-up", text="digital pathology", params={})
    excluded = ConnectorQuery(
        connector="pubmed", question_id="Q-trends", text="veterinary digital pathology", params={}
    )
    for q in (off, unknown, excluded):
        ok, why = gate.check(q)
        assert not ok and why
    assert len(gate.blocked) == 3


def test_scope_lock(plan):
    lock = ScopeLock(plan, 10, date(2026, 11, 25))
    f = Fact(
        id="x", source_id="s", claim="A veterinary pathology scanner launched.", basis="primary", tier="A", kind="news"
    )
    assert not lock.check(f, False)[0]
    g = f.model_copy(update={"claim": "Whole slide imaging adoption grew in pathology labs."})
    assert lock.check(g, False)[0]
    h = g.model_copy(update={"claim": "Retail banking apps grew."})
    assert not lock.check(h, False)[0]
    old = g.model_copy(update={"year": 2001})
    assert not lock.check(old, True)[0]
    abroad = g.model_copy(update={"geography": "Brazil"})
    assert not lock.check(abroad, True)[0] or "Global" in plan.geography


def test_mentions_handles_plurals():
    assert mentions("Pathologists report a backlog", ["pathologist"]) == "pathologist"
    assert not mentions("pathologically", ["pathology"])


def test_budget_caps():
    b = Budget(load_config(overrides={"limits": {"fetches": 1}}).limits)
    b.spend("fetches", 1, "first")
    with pytest.raises(BudgetExceeded):
        b.spend("fetches", 1, "second")
    assert b.skipped and b.as_dict()["used"]["fetches"] == 1
