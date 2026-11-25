"""The data model. Everything the report says traces back to a Fact, and every Fact to a Source.

Basis and tier travel with each fact:
  primary   = tier A: official statistics, regulators and registries, filings, papers, patents, trials
  secondary = tier B (company announcements, Wikidata, news) or C (research firms, blogs, vendor content)
Uploads are marked by the user as their own primary data or a third-party (secondary) report.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

Basis = Literal["primary", "secondary"]
Tier = Literal["A", "B", "C", "U"]  # U = upload (its basis says primary or secondary)
SourceKind = Literal[
    "statistics",
    "regulator",
    "filing",
    "paper",
    "patent",
    "trial",
    "news",
    "company",
    "research_firm",
    "web",
    "upload",
    "calculated",
    "user",
]
Position = Literal["new_entrant", "incumbent", "investor", "supplier", "company"]
EvidencePolicy = Literal["primary_only", "primary_then_secondary_on_request", "primary_then_secondary_for_gaps"]


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def short_hash(obj: object, n: int = 12) -> str:
    raw = obj if isinstance(obj, str) else json.dumps(obj, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:n]


class Brief(BaseModel):
    field: str
    geography: list[str] = Field(default_factory=lambda: ["Global"])
    horizon_years: int = 5
    position: Position = "new_entrant"
    company: str = ""
    competitors: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)  # empty = profile defaults
    depth: Literal["quick", "standard", "deep"] = "standard"
    pack: str = ""  # domain pack id, e.g. "health"; "" = auto
    topic: str = ""  # pack topic id, e.g. "digital_pathology"; "" = auto
    assumptions: list[dict] = Field(default_factory=list)  # your own inputs: {id, text, metric, value, unit, ...}

    def key(self) -> str:
        return short_hash(self.model_dump())


class PlanQuestion(BaseModel):
    id: str
    framework: str
    text: str
    terms: list[str] = Field(default_factory=list)
    connectors: list[str] = Field(default_factory=list)


class ConnectorQuery(BaseModel):
    """One call a connector will make. It must name the plan question it serves (query gate)."""

    connector: str
    question_id: str
    params: dict = Field(default_factory=dict)
    text: str = ""  # human-readable query, also checked by the gate

    def key(self) -> str:
        return short_hash({"c": self.connector, "p": self.params})


class Plan(BaseModel):
    brief_key: str
    field: str
    sub_segments: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    scope_terms: list[str] = Field(default_factory=list)  # a fact must mention one to be in scope
    exclude_terms: list[str] = Field(default_factory=list)  # any of these puts a query or fact out of scope
    geography: list[str] = Field(default_factory=list)
    companies: list[str] = Field(default_factory=list)
    segments: list[dict] = Field(default_factory=list)  # [{id, name, terms}]
    stages: list[dict] = Field(default_factory=list)  # value chain stages [{id, name, terms}]
    opportunities: list[dict] = Field(default_factory=list)  # candidate openings [{id, name, terms}]
    questions: list[PlanQuestion] = Field(default_factory=list)
    queries: list[ConnectorQuery] = Field(default_factory=list)
    assumptions: list[dict] = Field(default_factory=list)  # [{id, text, used_in, confidence, test, if_wrong, value}]
    approved: bool = False
    approved_at: str = ""

    def key(self) -> str:
        d = self.model_dump(exclude={"approved", "approved_at"})
        return short_hash(d)

    def question(self, qid: str) -> PlanQuestion | None:
        return next((q for q in self.questions if q.id == qid), None)


class Source(BaseModel):
    id: str
    connector: str
    basis: Basis
    tier: Tier
    kind: SourceKind
    title: str
    url: str = ""
    publisher: str = ""
    published: str = ""
    fetched: str = ""
    query_id: str = ""
    text: str = ""
    quarantined: list[str] = Field(default_factory=list)
    fictional: bool = False


class Fact(BaseModel):
    id: str
    source_id: str
    claim: str
    entity: str = ""
    metric: str = ""
    value: float | None = None
    unit: str = ""
    year: int | None = None
    geography: str = ""
    topics: list[str] = Field(default_factory=list)
    basis: Basis = "primary"
    tier: Tier = "A"
    kind: SourceKind = "statistics"
    as_of: str = ""
    location: str = ""  # where in the source: "record K241232", "page 3"
    direction: Literal["tailwind", "headwind", "neutral"] = "neutral"
    in_scope: bool = True
    scope_note: str = ""
    inputs: list[str] = Field(default_factory=list)  # for calculated facts: the fact ids it was computed from


class Statement(BaseModel):
    text: str
    fact_ids: list[str] = Field(default_factory=list)
    judgement: bool = False


class Block(BaseModel):
    key: str
    title: str
    statements: list[Statement] = Field(default_factory=list)
    gap: str = ""  # set when evidence is too thin; the block then says so
    rating: str = ""  # e.g. "4/5", "High", "Tailwind"
    data: dict = Field(default_factory=dict)


class Section(BaseModel):
    framework: str
    title: str
    blocks: list[Block] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "low"
    open_questions: list[str] = Field(default_factory=list)
    engine: str = "deterministic"
    data: dict = Field(default_factory=dict)

    def statements(self) -> list[Statement]:
        return [s for b in self.blocks for s in b.statements]

    def fact_ids(self) -> set[str]:
        return {f for s in self.statements() for f in s.fact_ids}


class Finding(BaseModel):
    id: str
    title: str
    sowhat: str
    strength: Literal["strong", "moderate", "signal"]
    fact_ids: list[str]
    source_kinds: list[str]
    counter: list[str] = Field(default_factory=list)
    feeds: list[str] = Field(default_factory=list)
    theme: str = ""


class CheckResult(BaseModel):
    rule: int
    name: str
    passed: bool
    detail: str = ""
    count: int = 0


class BlockedQuery(BaseModel):
    connector: str
    text: str
    question_id: str
    reason: str
    at: str = Field(default_factory=now_iso)


class RunManifest(BaseModel):
    run_id: str
    created: str = Field(default_factory=now_iso)
    brief_key: str
    plan_key: str
    profile: str
    config_hash: str
    engine: str
    evidence_basis: Literal["primary_only", "primary_secondary"] = "primary_only"
    models: dict = Field(default_factory=dict)
    prompt_version: str = ""
    snapshots: dict = Field(default_factory=dict)  # connector -> snapshot date / "live" / "fictional"
    tool_calls: list[dict] = Field(default_factory=list)
    blocked_queries: list[BlockedQuery] = Field(default_factory=list)
    set_aside: list[dict] = Field(default_factory=list)
    checks: list[CheckResult] = Field(default_factory=list)
    budget: dict = Field(default_factory=dict)
    fact_hash: str = ""  # replay test compares this
    fictional: bool = False


class Report(BaseModel):
    run_id: str
    brief: Brief
    plan: Plan
    title: str
    created: str = Field(default_factory=now_iso)
    evidence_basis: Literal["primary_only", "primary_secondary"] = "primary_only"
    summary: list[Statement] = Field(default_factory=list)
    verdict: str = ""
    verdict_basis: list[str] = Field(default_factory=list)
    sections: dict[str, Section] = Field(default_factory=dict)
    findings: list[Finding] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    checks: list[CheckResult] = Field(default_factory=list)
    fictional: bool = False

    def all_statements(self) -> list[Statement]:
        out = list(self.summary)
        for s in self.sections.values():
            out.extend(s.statements())
        return out
