"""Science and trials: PubMed, OpenAlex, ClinicalTrials.gov (primary, tier A).

These connectors count rather than read: papers per year, works per year, studies per
start year and per sponsor. Counts are facts; trends are computed from them in code.
"""

from __future__ import annotations

from collections import Counter

from bfa.connectors.base import Connector, Result
from bfa.schemas import ConnectorQuery, short_hash


class PubMed(Connector):
    id = "pubmed"
    name = "PubMed (NCBI E-utilities)"
    kind = "paper"
    key_env = "NCBI_API_KEY"
    homepage = "https://pubmed.ncbi.nlm.nih.gov"

    def run(self, q: ConnectorQuery) -> Result:
        term = q.params["term"]
        res = Result(targeted=True)
        src = self.source(
            q,
            f"pubmed-{short_hash(term, 8)}",
            f"PubMed search: {term}",
            f"https://pubmed.ncbi.nlm.nih.gov/?term={term.replace(' ', '+')}",
        )
        res.sources.append(src)
        for year in q.params.get("years", []):
            params = {
                "db": "pubmed",
                "term": term,
                "retmode": "json",
                "retmax": 0,
                "datetype": "pdat",
                "mindate": year,
                "maxdate": year,
            }
            if self.api_key:
                params["api_key"] = self.api_key
            body = self.http.get_json(
                self.id,
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                params,
                secret_params=("api_key",),
            )
            n = int((body.get("esearchresult") or {}).get("count", 0))
            res.facts.append(
                self.fact(
                    src,
                    f"PubMed indexes {n:,} papers matching '{term}' published in {year}.",
                    metric="papers_per_year",
                    value=float(n),
                    unit="papers",
                    year=int(year),
                    location=f"esearch {year}",
                    topics=["trend:papers", "pestle:technological"],
                )
            )
        return res


class OpenAlex(Connector):
    id = "openalex"
    name = "OpenAlex"
    kind = "paper"
    key_env = "OPENALEX_API_KEY"
    key_required = True  # required for all requests since 13 Feb 2026
    homepage = "https://openalex.org"

    def run(self, q: ConnectorQuery) -> Result:
        search, since = q.params["search"], int(q.params.get("from_year", 2015))
        res = Result(targeted=True)
        src = self.source(
            q,
            f"openalex-{short_hash(search, 8)}",
            f"OpenAlex works: {search}",
            f"https://openalex.org/works?search={search.replace(' ', '%20')}",
        )
        res.sources.append(src)
        base = {"search": search, "filter": f"from_publication_date:{since}-01-01"}
        if self.api_key:
            base["api_key"] = self.api_key
        years = self.http.get_json(
            self.id,
            "https://api.openalex.org/works",
            {**base, "group_by": "publication_year"},
            secret_params=("api_key",),
        )
        for g in years.get("group_by", []):
            y, n = int(g["key"]), int(g["count"])
            res.facts.append(
                self.fact(
                    src,
                    f"OpenAlex lists {n:,} works matching '{search}' published in {y}.",
                    metric="works_per_year",
                    value=float(n),
                    unit="works",
                    year=y,
                    location=f"group_by year {y}",
                    topics=["trend:papers", "pestle:technological"],
                )
            )
        inst = self.http.get_json(
            self.id,
            "https://api.openalex.org/works",
            {**base, "group_by": "authorships.institutions.lineage"},
            secret_params=("api_key",),
        )
        for g in inst.get("group_by", [])[:10]:
            name, n = g.get("key_display_name", g.get("key")), int(g["count"])
            res.facts.append(
                self.fact(
                    src,
                    f"{name} is an author institution on {n:,} works matching '{search}' since {since}.",
                    entity=name,
                    metric="works_by_institution",
                    value=float(n),
                    unit="works",
                    location="group_by institution",
                    topics=["trend:institutions", "ecosystem"],
                )
            )
        return res


class ClinicalTrials(Connector):
    id = "clinicaltrials"
    name = "ClinicalTrials.gov"
    kind = "trial"
    homepage = "https://clinicaltrials.gov"

    def run(self, q: ConnectorQuery) -> Result:
        term = q.params["term"]
        params = {
            "query.term": term,
            "pageSize": min(int(q.params.get("page_size", 100)), 1000),
            "countTotal": "true",
            "fields": "NCTId,BriefTitle,OverallStatus,StartDate,LeadSponsorName,LeadSponsorClass,Phase,StudyType",
        }
        body = self.http.get_json(self.id, "https://clinicaltrials.gov/api/v2/studies", params)
        studies = body.get("studies", [])
        total = int(body.get("totalCount", len(studies)))
        res = Result(targeted=True)
        src = self.source(
            q,
            f"ctgov-{short_hash(term, 8)}",
            f"ClinicalTrials.gov search: {term}",
            f"https://clinicaltrials.gov/search?term={term.replace(' ', '+')}",
        )
        res.sources.append(src)
        res.facts.append(
            self.fact(
                src,
                f"ClinicalTrials.gov lists {total:,} studies matching '{term}'.",
                metric="trials_total",
                value=float(total),
                unit="studies",
                topics=["trend:trials", "pestle:technological"],
            )
        )
        years, sponsors, industry = Counter(), Counter(), set()
        for s in studies:
            p = s.get("protocolSection", {})
            start = (p.get("statusModule", {}).get("startDateStruct") or {}).get("date", "")
            if start[:4].isdigit():
                years[int(start[:4])] += 1
            lead = p.get("sponsorCollaboratorsModule", {}).get("leadSponsor", {})
            if lead.get("name"):
                sponsors[lead["name"]] += 1
                if lead.get("class") == "INDUSTRY":
                    industry.add(lead["name"])
        for y in sorted(years):
            res.facts.append(
                self.fact(
                    src,
                    f"{years[y]} of the {len(studies)} retrieved studies matching '{term}' started in {y}.",
                    metric="trials_started",
                    value=float(years[y]),
                    unit="studies",
                    year=y,
                    location=f"start year {y}",
                    topics=["trend:trials"],
                )
            )
        for name, n in sponsors.most_common(8):
            topics = ["trend:trials", "ecosystem"] + (["competitor"] if name in industry else [])
            res.facts.append(
                self.fact(
                    src,
                    f"{name} is the lead sponsor of {n} of the retrieved studies matching "
                    f"'{term}'" + (" (industry sponsor)." if name in industry else "."),
                    entity=name,
                    metric="trials_by_sponsor",
                    value=float(n),
                    unit="studies",
                    topics=topics,
                )
            )
        return res
