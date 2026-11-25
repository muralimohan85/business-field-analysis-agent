"""End to end on the recorded snapshot: the demo must pass every check and replay identically."""

import pytest

from bfa.checks import locked_failures
from bfa.pipeline import open_run, replay_test, run
from bfa.secondary import SecondaryRequest, run_secondary, toggle
from tests.conftest import TODAY


def test_demo_passes_all_checks(demo_run):
    failed = [c for c in demo_run.report.checks if not c.passed]
    assert not failed, failed
    assert len(demo_run.report.checks) == 10
    assert not locked_failures(demo_run.report.checks)


def test_every_statement_cites_existing_facts(demo_run):
    st = demo_run.store
    for s in demo_run.report.all_statements():
        assert s.fact_ids and all(st.fact(i) for i in s.fact_ids), s.text


def test_primary_only_report_cites_no_secondary(demo_run):
    st = demo_run.store
    assert demo_run.report.evidence_basis == "primary_only"
    cited = {i for s in demo_run.report.all_statements() for i in s.fact_ids}
    assert all(st.fact(i).basis == "primary" for i in cited)


def test_report_has_every_default_framework(demo_run, cfg):
    assert set(cfg.output.frameworks) <= set(demo_run.report.sections)
    assert demo_run.report.summary and demo_run.report.verdict


def test_real_fda_records_are_used(demo_run):
    claims = " ".join(f.claim for f in demo_run.store.facts())
    assert "product code QKQ" in claims and "De Novo" in claims


def test_bottom_up_market_uses_survey_and_assumptions(demo_run):
    mk = demo_run.report.sections["market_size"]
    bu = next(b for b in mk.blocks if b.key == "bottom_up")
    assert "1,200 labs" in bu.statements[0].text and "$21.6 million" in bu.statements[0].text


def test_injection_from_upload_was_quarantined(demo_run):
    inj = next(c for c in demo_run.report.checks if c.name == "injection")
    assert inj.passed and inj.count >= 1


def test_replay_reproduces_evidence(demo_run):
    res = replay_test(demo_run.folder)
    assert res["same_evidence"] and res["same_statements"]


def test_saved_run_reopens(demo_run):
    r = open_run(demo_run.folder)
    assert r.report.run_id == demo_run.report.run_id and r.store.counts()["facts"] > 50


def test_plan_needs_approval(brief, cfg, tmp_path):
    with pytest.raises(PermissionError):
        run(brief, cfg, today=TODAY, workspace=tmp_path)


def test_secondary_search_is_labelled_and_switchable(demo_run):
    sec = run_secondary(
        demo_run,
        SecondaryRequest(gaps=demo_run.report.open_questions[:2], sections=["market_size"]),
        approve=True,
        today=TODAY,
    )
    assert sec.report.evidence_basis == "primary_secondary"
    assert all(c.passed for c in sec.report.checks)
    tam = next(b for b in sec.report.sections["market_size"].blocks if b.key == "tam")
    assert any("1.1 billion" in s.text for s in tam.statements)  # the secondary upload's estimate
    off = toggle(sec, False, TODAY)
    assert off.report.evidence_basis == "primary_only"


def test_secondary_needs_approval_and_policy(demo_run):
    with pytest.raises(PermissionError):
        run_secondary(demo_run, SecondaryRequest(), approve=False)
    strict = demo_run.cfg.model_copy(
        update={"evidence": demo_run.cfg.evidence.model_copy(update={"policy": "primary_only"})}
    )
    with pytest.raises(PermissionError):
        run_secondary(demo_run.__class__(**{**demo_run.__dict__, "cfg": strict}), SecondaryRequest(), approve=True)
