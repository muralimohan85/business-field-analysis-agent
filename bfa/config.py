"""Agent settings: config/agent.yaml, merged with a profile and any overrides.

The guarantees that make a report fact-based are locked: no profile or override can
turn them off. Loading a configuration that tries to is an error, not a warning.
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator

from bfa.schemas import EvidencePolicy, short_hash

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
WORKSPACE = Path(os.environ.get("BFA_WORKSPACE", ROOT / "workspace"))

LOCKED_CHECKS = ("citations", "grounding", "numbers")
SEARCH_FEE_PER_1000 = 10.0  # Claude web search, USD per 1,000 searches


class EvidenceCfg(BaseModel):
    model_knowledge: Literal["never"] = "never"
    policy: EvidencePolicy = "primary_then_secondary_on_request"
    press_releases_primary: bool = False
    finding_min_facts: int = 3
    finding_min_kinds: int = 2
    block_min_facts: int = 2
    summary_min_tier: Literal["A", "B", "C"] = "A"
    flag_after_years: int = 3
    exclude_after_years: int = 10


class ScopeCfg(BaseModel):
    lock_after_plan: bool = True
    off_plan_queries: Literal["block", "ask", "allow"] = "block"
    out_of_scope: Literal["set_aside", "drop"] = "set_aside"
    steps_per_section: int = 20


class LimitsCfg(BaseModel):
    web_searches: int = 40
    secondary_searches: int = 20
    fetches: int = 80
    run_minutes: int = 30
    records_per_query: int = 100


class ModelsCfg(BaseModel):
    planner: str = "claude-opus-5-5"
    researcher: str = "claude-sonnet-5-5"
    writer: str = "claude-opus-5-5"
    pinned: bool = True
    temperature_write: float = 0.2
    prices_per_mtok: dict[str, dict[str, float]] = Field(default_factory=dict)  # fill in to see token cost


class ApprovalsCfg(BaseModel):
    plan: bool = True
    secondary_search: bool = True
    new_companies: bool = True
    working_range: bool = True
    review_before_export: bool = False


class SourcesCfg(BaseModel):
    enabled: dict[str, bool] = Field(default_factory=dict)
    official_domains: list[str] = Field(default_factory=list)
    blocked_domains: list[str] = Field(default_factory=list)


class OutputCfg(BaseModel):
    language: str = "English"
    citation_style: Literal["footnotes", "inline"] = "footnotes"
    frameworks: list[str] = Field(default_factory=list)


class AgentConfig(BaseModel):
    profile: str = "strict-fact-based"
    evidence: EvidenceCfg = Field(default_factory=EvidenceCfg)
    scope: ScopeCfg = Field(default_factory=ScopeCfg)
    limits: LimitsCfg = Field(default_factory=LimitsCfg)
    models: ModelsCfg = Field(default_factory=ModelsCfg)
    approvals: ApprovalsCfg = Field(default_factory=ApprovalsCfg)
    sources: SourcesCfg = Field(default_factory=SourcesCfg)
    output: OutputCfg = Field(default_factory=OutputCfg)
    checks: list[str] = Field(
        default_factory=lambda: (
            list(LOCKED_CHECKS) + ["scope", "policy", "gaps", "agreement", "findings", "injection", "budget"]
        )
    )
    run_manifest: Literal[True] = True

    @field_validator("checks")
    @classmethod
    def _locked_checks(cls, v: list[str]) -> list[str]:
        missing = [c for c in LOCKED_CHECKS if c not in v]
        if missing:
            raise ValueError(f"locked checks cannot be removed: {', '.join(missing)}")
        return v

    def key(self) -> str:
        return short_hash(self.model_dump())

    def secondary_allowed(self) -> bool:
        return self.evidence.policy != "primary_only"

    def connector_on(self, cid: str) -> bool:
        return self.sources.enabled.get(cid, True)


def _deep_merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def profiles() -> list[str]:
    return sorted(p.stem for p in (CONFIG_DIR / "profiles").glob("*.yaml"))


def load_config(profile: str | None = None, overrides: dict | None = None) -> AgentConfig:
    base = yaml.safe_load((CONFIG_DIR / "agent.yaml").read_text()) or {}
    prof = profile or base.get("profile", "strict-fact-based")
    path = CONFIG_DIR / "profiles" / f"{prof}.yaml"
    if path.exists():
        base = _deep_merge(base, yaml.safe_load(path.read_text()) or {})
    base["profile"] = prof
    base = _deep_merge(base, overrides or {})
    return AgentConfig.model_validate(base)


def to_yaml(cfg: AgentConfig) -> str:
    return yaml.safe_dump(cfg.model_dump(), sort_keys=False, allow_unicode=True)


def load_yaml(name: str) -> dict:
    return yaml.safe_load((CONFIG_DIR / name).read_text()) or {}
