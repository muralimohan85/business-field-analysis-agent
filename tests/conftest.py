"""Shared fixtures. The demo run replays the recorded openFDA snapshot plus two fictional sample uploads;
it runs once per test session and needs no network."""

from __future__ import annotations

from datetime import date

import pytest
import yaml

from bfa.config import ROOT, load_config
from bfa.schemas import Brief, Fact, Source

DEMO = ROOT / "data" / "demo" / "digital_pathology"
TODAY = date(2026, 11, 25)
UPLOADS = [
    (str(DEMO / "uploads" / "example-diagnostics-lab-survey.pdf"), "primary", True),
    (str(DEMO / "uploads" / "lumen-slide-systems-brochure.docx"), "secondary", True),
]


@pytest.fixture(scope="session")
def brief() -> Brief:
    return Brief(**yaml.safe_load((DEMO / "brief.yaml").read_text()))


@pytest.fixture(scope="session")
def cfg():
    return load_config()


@pytest.fixture(scope="session")
def demo_run(brief, cfg, tmp_path_factory):
    from bfa.pipeline import run

    ws = tmp_path_factory.mktemp("ws")
    return run(
        brief,
        cfg,
        mode="replay",
        snapshot="digital-pathology-real",
        uploads=UPLOADS,
        auto_approve=True,
        today=TODAY,
        workspace=ws,
    )


@pytest.fixture()
def store(tmp_path):
    from bfa.store import Store

    return Store(tmp_path / "t.db")


def add(
    store,
    fid,
    claim,
    *,
    basis="primary",
    tier="A",
    kind="regulator",
    value=None,
    unit="",
    year=None,
    topics=None,
    source="s1",
    in_scope=True,
    direction="neutral",
    inputs=None,
) -> Fact:
    if store.source(source) is None:
        store.add_source(
            Source(
                id=source,
                connector="fixture",
                basis=basis,
                tier=tier,
                kind=kind,
                title=f"Fixture source {source}",
                url=f"https://example.org/{source}",
                publisher="Example",
                fetched="2026-11-25T00:00:00+00:00",
            )
        )
    f = Fact(
        id=fid,
        source_id=source,
        claim=claim,
        value=value,
        unit=unit,
        year=year,
        basis=basis,
        tier=tier,
        kind=kind,
        topics=topics or [],
        in_scope=in_scope,
        direction=direction,
        inputs=inputs or [],
    )
    store.add_fact(f)
    return f


@pytest.fixture()
def fact():
    return add
