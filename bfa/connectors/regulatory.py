"""openFDA device classifications, 510(k) and De Novo decisions, and recalls (primary, tier A)."""

from __future__ import annotations

from bfa.connectors.base import Connector, Result
from bfa.schemas import ConnectorQuery

DECISIONS = {
    "SESE": "cleared (substantially equivalent)",
    "SESD": "cleared (substantially equivalent, with drug)",
    "SESK": "cleared (substantially equivalent, kit)",
    "SESP": "cleared (substantially equivalent, postmarket surveillance)",
    "SESU": "cleared (substantially equivalent, with limitations)",
    "DENG": "granted De Novo",
    "SN": "found not substantially equivalent",
}


class OpenFDA(Connector):
    id = "openfda"
    name = "openFDA"
    kind = "regulator"
    key_env = "OPENFDA_API_KEY"
    homepage = "https://open.fda.gov"

    def run(self, q: ConnectorQuery) -> Result:
        ep, pc = q.params.get("endpoint", "510k"), q.params["product_code"]
        params = {"search": f"product_code:{pc}", "limit": min(int(q.params.get("limit", 100)), 1000)}
        if self.api_key:
            params["api_key"] = self.api_key
        body = self.http.get_json(self.id, f"https://api.fda.gov/device/{ep}.json", params, secret_params=("api_key",))
        rows = body.get("results", []) if isinstance(body, dict) else []
        total = (body.get("meta", {}).get("results", {}) or {}).get("total", len(rows)) if isinstance(body, dict) else 0
        stage = q.params.get("stage", "")
        stage_t = [f"stage:{stage}"] if stage else []
        res = Result()
        if ep == "classification":
            for r in rows:
                src = self.source(
                    q,
                    f"fda-class-{pc}",
                    f"FDA product classification {pc}: {r.get('device_name', '')}",
                    f"https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfpcd/classification.cfm?ID={pc}",
                    text=r.get("definition", ""),
                )
                res.sources.append(src)
                res.facts.append(
                    self.fact(
                        src,
                        f"FDA product code {pc} covers '{r.get('device_name', '').strip()}' "
                        f"(21 CFR {r.get('regulation_number', '?')}, device class {r.get('device_class', '?')}).",
                        entity="FDA",
                        metric="device_class",
                        value=_num(r.get("device_class")),
                        location=f"product code {pc}",
                        topics=["regulatory", "pestle:legal", "porter:entrants"] + stage_t,
                        geography="US",
                    )
                )
        elif ep == "510k":
            src = self.source(
                q,
                f"fda-510k-{pc}",
                f"openFDA 510(k) and De Novo decisions, product code {pc}",
                f"https://api.fda.gov/device/510k.json?search=product_code:{pc}",
            )
            res.sources.append(src)
            res.facts.append(
                self.fact(
                    src,
                    f"openFDA lists {total} 510(k) and De Novo decisions under FDA product code {pc}.",
                    entity="FDA",
                    metric="decisions_total",
                    value=float(total),
                    unit="decisions",
                    location=f"product code {pc}",
                    topics=["regulatory", "trend:decisions", "porter:rivalry"] + stage_t,
                    geography="US",
                )
            )
            for r in sorted(rows, key=lambda x: x.get("decision_date", "")):
                k, d = r.get("k_number", ""), r.get("decision_date", "")
                verb = DECISIONS.get(r.get("decision_code", ""), f"decided ({r.get('decision_code', '')})")
                kind = "denovo" if k.startswith("DEN") else "pmn"
                rsrc = self.source(
                    q,
                    f"fda-{k}",
                    f"FDA {k}: {r.get('device_name', '')}",
                    f"https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfpmn/{kind}.cfm?ID={k}",
                    published=d,
                    publisher="U.S. FDA",
                )
                res.sources.append(rsrc)
                applicant = " ".join((r.get("applicant") or "").split())
                res.facts.append(
                    self.fact(
                        rsrc,
                        f"FDA {verb} {k} on {d}: '{r.get('device_name', '').strip()}' from {applicant} "
                        f"(product code {pc}).",
                        entity=applicant,
                        metric="decision",
                        year=_year(d),
                        location=f"record {k}",
                        as_of=d,
                        direction="tailwind",
                        geography="US",
                        topics=["regulatory", "competitor", "competitor:move", "trend:decisions", "pestle:legal"]
                        + stage_t,
                    )
                )
        elif ep == "recall":
            src = self.source(
                q,
                f"fda-recall-{pc}",
                f"openFDA recalls, product code {pc}",
                f"https://api.fda.gov/device/recall.json?search=product_code:{pc}",
            )
            res.sources.append(src)
            res.facts.append(
                self.fact(
                    src,
                    f"openFDA lists {total} recall records under FDA product code {pc}.",
                    entity="FDA",
                    metric="recalls_total",
                    value=float(total),
                    unit="recalls",
                    location=f"product code {pc}",
                    topics=["regulatory", "risk"] + stage_t,
                    geography="US",
                )
            )
            for r in rows:
                ev, d = (
                    r.get("res_event_number", ""),
                    r.get("event_date_posted", "") or r.get("event_date_initiated", ""),
                )
                rsrc = self.source(
                    q,
                    f"fda-recall-{ev or r.get('cfres_id', '')}",
                    f"FDA recall {ev}: {r.get('recalling_firm', '')}",
                    f"https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfRES/res.cfm?id={r.get('cfres_id', '')}",
                    published=d,
                    publisher="U.S. FDA",
                )
                res.sources.append(rsrc)
                reason = " ".join((r.get("reason_for_recall") or "").split())[:180]
                res.facts.append(
                    self.fact(
                        rsrc,
                        f"FDA recall {ev} ({r.get('recall_status', 'status unknown')}), posted {d}, for a "
                        f"{pc} device from {r.get('recalling_firm', '')}: {reason}",
                        entity=r.get("recalling_firm", ""),
                        metric="recall",
                        year=_year(d),
                        location=f"recall {ev}",
                        as_of=d,
                        direction="headwind",
                        geography="US",
                        topics=["regulatory", "risk", "competitor"] + stage_t,
                    )
                )
        return res


def _year(d: str) -> int | None:
    try:
        return int((d or "")[:4])
    except ValueError:
        return None


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
