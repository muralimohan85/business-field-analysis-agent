"""Build the connectors a run uses, from config/sources.yaml and the agent settings."""

from __future__ import annotations

from bfa.config import AgentConfig, load_yaml
from bfa.connectors.base import Connector, Http
from bfa.connectors.markets import PatentsView, SecEdgar, WorldBank
from bfa.connectors.regulatory import OpenFDA
from bfa.connectors.science import ClinicalTrials, OpenAlex, PubMed
from bfa.connectors.web import ClaudeWeb, Gdelt

PRIMARY = {
    "openfda": OpenFDA,
    "clinicaltrials": ClinicalTrials,
    "pubmed": PubMed,
    "openalex": OpenAlex,
    "worldbank": WorldBank,
    "sec_edgar": SecEdgar,
    "patentsview": PatentsView,
}
SECONDARY = {"gdelt": Gdelt}


def catalogue() -> dict:
    return load_yaml("sources.yaml")["connectors"]


def build(cfg: AgentConfig, http: Http, client=None) -> dict[str, Connector]:
    out: dict[str, Connector] = {}
    for cid, cls in {**PRIMARY, **SECONDARY}.items():
        if cfg.connector_on(cid):
            out[cid] = cls(http)
    if cfg.connector_on("claude_web"):
        out["claude_web"] = ClaudeWeb(http, cfg.sources.official_domains, cfg.models.researcher, client)
    if cfg.connector_on("claude_web_open"):
        web = ClaudeWeb(http, cfg.sources.official_domains, cfg.models.researcher, client)
        web.id, web.basis, web.tier = "claude_web_open", "secondary", "B"
        out["claude_web_open"] = web
    return out


def is_secondary(cid: str) -> bool:
    return cid in SECONDARY or cid == "claude_web_open"
