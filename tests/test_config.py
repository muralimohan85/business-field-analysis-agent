import pytest
from pydantic import ValidationError

from bfa.config import LOCKED_CHECKS, AgentConfig, load_config, profiles


def test_profiles_load():
    names = profiles()
    assert {"strict-fact-based", "exploratory", "regulated-health"} <= set(names)
    for n in names:
        assert load_config(n).profile == n


def test_locked_checks_cannot_be_removed():
    with pytest.raises(ValidationError):
        AgentConfig(checks=["scope"])
    assert set(LOCKED_CHECKS) <= set(load_config().checks)


def test_model_knowledge_is_never_a_source():
    with pytest.raises(ValidationError):
        load_config(overrides={"evidence": {"model_knowledge": "allowed"}})


def test_run_manifest_is_locked():
    with pytest.raises(ValidationError):
        load_config(overrides={"run_manifest": False})


def test_overrides_merge_deeply():
    c = load_config("exploratory", {"limits": {"fetches": 7}})
    assert c.limits.fetches == 7 and c.limits.web_searches == 60


def test_regulated_health_is_primary_only():
    c = load_config("regulated-health")
    assert not c.secondary_allowed() and c.approvals.review_before_export
