"""Connector parsing. openFDA uses the real recorded snapshot; the others use small synthetic payloads in each
API's shape (fake companies, example values) so parsing is tested without a network."""

from bfa.config import load_config
from bfa.connectors.base import Http
from bfa.connectors.markets import WorldBank
from bfa.connectors.regulatory import OpenFDA
from bfa.connectors.science import ClinicalTrials, PubMed
from bfa.connectors.web import classify_domain
from bfa.schemas import ConnectorQuery


class FakeHttp(Http):
    def __init__(self, answer):
        super().__init__(mode="live", snapshot="test")
        self.answer = answer

    def get_json(self, connector, url, params=None, headers=None, method="GET", body=None, secret_params=()):
        self.calls.append({"connector": connector, "url": url, "mode": "fake", "fetched": "2026-11-25"})
        return self.answer(url, params or {}, body)


def test_openfda_snapshot_parses():
    c = OpenFDA(Http(mode="replay", snapshot="digital-pathology-real"))
    res = c.run(
        ConnectorQuery(
            connector="openfda",
            question_id="Q-competitors",
            text="510(k) QKQ",
            params={"endpoint": "510k", "product_code": "QKQ", "stage": "viewing", "targeted": True},
        )
    )
    assert res.targeted and res.facts
    assert any(f.metric == "decision" and f.entity for f in res.facts)
    assert all(f.basis == "primary" and f.tier == "A" for f in res.facts)


def test_pubmed_counts_per_year():
    def answer(url, params, body):
        return {"esearchresult": {"count": str(100 + int(params["mindate"]) % 10)}}

    c = PubMed(FakeHttp(answer))
    res = c.run(
        ConnectorQuery(
            connector="pubmed",
            question_id="Q-trends",
            text="pubmed",
            params={"term": '"digital pathology"', "years": [2021, 2022, 2023, 2024, 2025], "targeted": True},
        )
    )
    facts = [f for f in res.facts if f.metric == "papers_per_year"]
    assert [f.year for f in facts] == [2021, 2022, 2023, 2024, 2025]
    assert facts[-1].value == 105 and "105 papers" in facts[-1].claim


def test_worldbank_values():
    def answer(url, params, body):
        return [
            {"page": 1},
            [
                {
                    "country": {"value": "Exampleland"},
                    "countryiso3code": "EXL",
                    "date": "2024",
                    "value": 123.4,
                    "indicator": {"value": "Example indicator"},
                }
            ],
        ]

    c = WorldBank(FakeHttp(answer))
    res = c.run(
        ConnectorQuery(
            connector="worldbank",
            question_id="Q-pestle",
            text="wb",
            params={
                "indicator": "SH.XPD.CHEX.PC.CD",
                "countries": ["EXL"],
                "unit": "USD",
                "topic": "pestle:economic",
                "targeted": True,
            },
        )
    )
    assert res.facts and res.facts[0].value == 123.4 and "pestle:economic" in res.facts[0].topics


def test_clinicaltrials_totals():
    def answer(url, params, body):
        return {
            "totalCount": 2,
            "studies": [
                {
                    "protocolSection": {
                        "identificationModule": {"nctId": "NCT00000001", "briefTitle": "Example AI pathology study"},
                        "statusModule": {"startDateStruct": {"date": "2024-03"}},
                        "sponsorCollaboratorsModule": {
                            "leadSponsor": {"name": "Acme Pathology Inc", "class": "INDUSTRY"}
                        },
                    }
                },
                {
                    "protocolSection": {
                        "identificationModule": {"nctId": "NCT00000002", "briefTitle": "Second example"},
                        "statusModule": {"startDateStruct": {"date": "2025-01"}},
                        "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Example University", "class": "OTHER"}},
                    }
                },
            ],
        }

    c = ClinicalTrials(FakeHttp(answer))
    res = c.run(
        ConnectorQuery(
            connector="clinicaltrials",
            question_id="Q-trends",
            text="ct",
            params={"term": "digital pathology", "targeted": True},
        )
    )
    assert any(f.metric == "trials_total" and f.value == 2 for f in res.facts)


def test_domain_classification():
    official = load_config().sources.official_domains
    assert classify_domain("www.accessdata.fda.gov", official)[0] == "primary"
    assert classify_domain("news.example.com", official)[0] == "secondary"
