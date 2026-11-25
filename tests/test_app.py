"""The Streamlit app, driven like a user: every form, button and page switch must work without an error."""

from pathlib import Path

import pytest

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
APP = str(Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py")


def ok(at):
    assert not at.exception, [e.value for e in at.exception]


def button(at, label):
    return next(b for b in at.button if (b.label or "").startswith(label))


def nav(at, page):
    at.sidebar.radio[0].set_value(page).run()
    ok(at)
    assert at.session_state["nav"] == page


@pytest.fixture(scope="module")
def at():
    a = AppTest.from_file(APP, default_timeout=300)
    a.run()
    ok(a)
    return a


def test_opens_on_the_demo_report(at):
    assert at.session_state["nav"] == "Report"
    assert at.session_state["run"].report.verdict


def test_new_analysis_plan_and_run(at):
    nav(at, "New analysis")
    button(at, "Build the plan").click().run()
    ok(at)
    assert at.session_state["nav"] == "Plan and run"
    next(c for c in at.checkbox if "approve this plan" in c.label).check().run()
    button(at, "Run the analysis").click().run()
    ok(at)
    assert at.session_state["nav"] == "Report"


def test_secondary_search_and_switch(at):
    nav(at, "Secondary search")
    next(c for c in at.checkbox if "approve this secondary" in c.label).check()
    button(at, "Run secondary search").click().run()
    ok(at)
    assert at.session_state["run_sec"].report.evidence_basis == "primary_secondary"
    nav(at, "Report")
    next(t for t in at.toggle if "Include secondary" in t.label).set_value(False).run()
    ok(at)
    assert at.session_state["show_secondary"] is False


def test_one_click_navigation(at):
    for a, b in [
        ("Report", "Export"),
        ("Export", "Frameworks"),
        ("Frameworks", "Evidence"),
        ("Evidence", "Agent settings"),
        ("Agent settings", "Report"),
    ]:
        nav(at, a)
        nav(at, b)


def test_export_and_settings(at):
    nav(at, "Export")
    button(at, "Create files").click().run()
    ok(at)
    assert len(at.get("download_button")) == 3
    nav(at, "Agent settings")
    at.selectbox[0].set_value("exploratory").run()
    button(at, "Apply settings").click().run()
    ok(at)
    assert at.session_state["profile"] == "exploratory"
