"""World Bank indicators, SEC EDGAR company facts and PatentsView patents (primary, tier A)."""

from __future__ import annotations

from collections import Counter

from bfa.calc import fmt_num
from bfa.connectors.base import Connector, ConnectorError, Result
from bfa.schemas import ConnectorQuery, short_hash


class WorldBank(Connector):
    id = "worldbank"
    name = "World Bank Indicators"
    kind = "statistics"
    homepage = "https://data.worldbank.org"

    def run(self, q: ConnectorQuery) -> Result:
        ind, countries = q.params["indicator"], q.params.get("countries", ["WLD"])
        body = self.http.get_json(
            self.id,
            f"https://api.worldbank.org/v2/country/{';'.join(countries)}/indicator/{ind}",
            {"format": "json", "per_page": 500, "mrv": int(q.params.get("mrv", 6))},
        )
        rows = body[1] if isinstance(body, list) and len(body) > 1 and body[1] else []
        res = Result(targeted=True)
        src = self.source(q, f"wb-{ind}", f"World Bank indicator {ind}", f"https://data.worldbank.org/indicator/{ind}")
        res.sources.append(src)
        unit = q.params.get("unit", "")
        for r in rows:
            if r.get("value") is None:
                continue
            name = (r.get("indicator") or {}).get("value", ind)
            country = (r.get("country") or {}).get("value", "")
            year, val = int(r["date"]), float(r["value"])
            res.facts.append(
                self.fact(
                    src,
                    f"World Bank: {name} for {country} was {fmt_num(val, unit)} in {year}.",
                    entity=country,
                    metric=ind,
                    value=val,
                    unit=unit,
                    year=year,
                    geography=country,
                    location=f"{r.get('countryiso3code', '')} {year}",
                    topics=list(q.params.get("topics", ["pestle:economic"])),
                )
            )
        return res


class SecEdgar(Connector):
    id = "sec_edgar"
    name = "SEC EDGAR"
    kind = "filing"
    homepage = "https://www.sec.gov/edgar"
    CONCEPTS = ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "Revenue"]

    def _cik(self, ticker: str) -> str:
        data = self.http.get_json(self.id, "https://www.sec.gov/files/company_tickers.json")
        for row in data.values() if isinstance(data, dict) else data:
            if str(row.get("ticker", "")).upper() == ticker.upper():
                return str(row["cik_str"]).zfill(10)
        raise ConnectorError(f"sec_edgar: ticker {ticker} not found")

    def run(self, q: ConnectorQuery) -> Result:
        ticker, company = q.params["ticker"], q.params.get("company", q.params["ticker"])
        cik = q.params.get("cik") or self._cik(ticker)
        body = self.http.get_json(self.id, f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
        res = Result(targeted=True)
        src = self.source(
            q,
            f"sec-{cik}",
            f"SEC EDGAR company facts: {company}",
            f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}",
        )
        res.sources.append(src)
        facts = body.get("facts", {})
        for taxonomy in ("us-gaap", "ifrs-full"):
            for concept in self.CONCEPTS:
                units = (facts.get(taxonomy, {}).get(concept) or {}).get("units", {})
                series = units.get("USD") or next(iter(units.values()), [])
                annual = [r for r in series if r.get("fp") == "FY" and r.get("form") in ("10-K", "20-F")]
                by_fy = {}
                for r in annual:
                    by_fy[r["fy"]] = r
                for fy in sorted(by_fy)[-3:]:
                    r = by_fy[fy]
                    unit = "USD" if "USD" in units else next(iter(units), "")
                    res.facts.append(
                        self.fact(
                            src,
                            f"{company} reported total revenue of {fmt_num(float(r['val']), unit)} for fiscal "
                            f"{fy} ({r['form']} filed {r.get('filed', '')}).",
                            entity=company,
                            metric="company_revenue",
                            value=float(r["val"]),
                            unit=unit,
                            year=int(fy),
                            location=f"{taxonomy}:{concept} FY{fy}",
                            as_of=r.get("filed", ""),
                            topics=["competitor", "market:revenue"],
                        )
                    )
                if annual:
                    return res
        res.note = "no annual revenue concept found"
        return res


class PatentsView(Connector):
    """USPTO PatentSearch API (key required, 45 requests a minute). Field names follow the v1 reference."""

    id = "patentsview"
    name = "PatentsView (USPTO)"
    kind = "patent"
    key_env = "PATENTSVIEW_API_KEY"
    key_required = True
    homepage = "https://patentsview.org"

    def run(self, q: ConnectorQuery) -> Result:
        text, cpc, since = q.params["text"], q.params.get("cpc", ""), int(q.params.get("from_year", 2015))
        clauses = [{"_text_any": {"patent_abstract": text}}, {"patent_date": {"_gte": f"{since}-01-01"}}]
        if cpc:
            clauses.append({"_begins": {"cpc_current.cpc_group_id": cpc}})
        body = {
            "q": {"_and": clauses},
            "f": ["patent_id", "patent_date", "assignees.assignee_organization"],
            "o": {"size": 1000},
        }
        data = self.http.get_json(
            self.id,
            "https://search.patentsview.org/api/v1/patent/",
            method="POST",
            body=body,
            headers={"X-Api-Key": self.api_key} if self.api_key else {},
        )
        patents = data.get("patents", []) or []
        res = Result(targeted=True)
        src = self.source(
            q,
            f"pv-{short_hash([text, cpc], 8)}",
            f"PatentsView: '{text}' {cpc}",
            "https://search.patentsview.org/docs/",
        )
        res.sources.append(src)
        label = f"mentioning '{text}'" + (f" in CPC {cpc}" if cpc else "")
        years, owners = Counter(), Counter()
        for p in patents:
            if (p.get("patent_date") or "")[:4].isdigit():
                years[int(p["patent_date"][:4])] += 1
            for a in p.get("assignees") or []:
                if a.get("assignee_organization"):
                    owners[a["assignee_organization"]] += 1
        for y in sorted(years):
            res.facts.append(
                self.fact(
                    src,
                    f"PatentsView lists {years[y]} US patents granted in {y} {label}.",
                    metric="patents_per_year",
                    value=float(years[y]),
                    unit="patents",
                    year=y,
                    location=f"grant year {y}",
                    geography="US",
                    topics=["trend:patents", "pestle:technological"],
                )
            )
        for name, n in owners.most_common(8):
            res.facts.append(
                self.fact(
                    src,
                    f"{name} is the assignee on {n} US patents granted since {since} {label}.",
                    entity=name,
                    metric="patents_by_assignee",
                    value=float(n),
                    unit="patents",
                    geography="US",
                    topics=["trend:patents", "competitor"],
                )
            )
        return res
