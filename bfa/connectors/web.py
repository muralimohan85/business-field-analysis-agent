"""Claude web search and fetch, and GDELT news.

Claude web search is primary only while its allowed-domains list is set to official
domains (the primary search). Without the list it is a secondary source, and so are
news connectors. Every passage it returns is a cited quotation from a page; the
connector keeps the quotation and the URL, never the model's own words.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from urllib.parse import urlparse

from bfa.connectors.base import Connector, ConnectorError, Result
from bfa.safety.sanitizer import clean
from bfa.schemas import ConnectorQuery, short_hash
from bfa.taxonomy import market_metrics, tag

GOV_SUFFIXES = (".gov", ".gov.in", ".gov.uk", ".europa.eu", ".int", ".nic.in")
RESEARCH_FIRM_HINTS = ("research", "insights", "market", "grandview", "mordor", "fortune", "precedence", "imarc")


def domain(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def on_list(host: str, domains: list[str]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def classify_domain(host: str, official: list[str]) -> tuple[str, str, str]:
    """(basis, tier, kind) for a web page by its domain."""
    if on_list(host, official) or host.endswith(GOV_SUFFIXES):
        return "primary", "A", "regulator"
    if any(h in host for h in RESEARCH_FIRM_HINTS):
        return "secondary", "C", "research_firm"
    return "secondary", "B", "web"


class ClaudeWeb(Connector):
    id = "claude_web"
    name = "Claude web search"
    kind = "web"
    key_env = "ANTHROPIC_API_KEY"
    key_required = True
    key_hint = "Claude API key"
    homepage = "https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool"

    def __init__(
        self,
        http,
        official_domains: list[str] | None = None,
        model: str = "claude-sonnet-5-5",
        client=None,
        max_uses: int = 5,
    ):
        super().__init__(http)
        self.official = official_domains or []
        self.model, self.client, self.max_uses = model, client, max_uses

    def _call(self, question: str, allowed: list[str] | None) -> dict:
        key = short_hash({"q": question, "a": allowed, "m": self.model}, 16)
        path = self.http._path(self.id, key)
        if self.http.mode == "replay":
            import json

            if not path.exists():
                from bfa.connectors.base import SnapshotMissing

                raise SnapshotMissing(f"claude_web: no recorded answer for '{question}'")
            return json.loads(path.read_text())["body"]
        client = self.client
        if client is None:
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise ConnectorError("claude_web: set ANTHROPIC_API_KEY")
            import anthropic

            client = anthropic.Anthropic()
        search = {"type": "web_search_20260318", "name": "web_search", "max_uses": self.max_uses}
        fetch = {
            "type": "web_fetch_20260318",
            "name": "web_fetch",
            "max_uses": self.max_uses,
            "citations": {"enabled": True},
            "max_content_tokens": 20000,
        }
        if allowed:
            search["allowed_domains"] = allowed
            fetch["allowed_domains"] = allowed
        resp = client.messages.create(
            model=self.model,
            max_tokens=2000,
            system=(
                "You collect evidence. Answer only with sentences quoted from the pages you find, each with its "
                "citation. Do not add facts, estimates or opinions of your own. If the pages do not answer, say "
                "'No source found.'"
            ),
            tools=[search, fetch],
            messages=[{"role": "user", "content": f"Find quoted evidence for: {question}"}],
        )
        body = resp.model_dump() if hasattr(resp, "model_dump") else resp
        if self.http.mode == "record":
            import json

            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {"url": question, "fetched": datetime.now(UTC).isoformat(), "body": body}, indent=1, default=str
                )
            )
        return body

    def run(self, q: ConnectorQuery) -> Result:
        primary_only = q.params.get("primary", True)
        allowed = self.official if primary_only else None
        body = self._call(q.params["question"], allowed)
        res = Result(targeted=False)
        usage = body.get("usage", {}) or {}
        res.note = f"web searches used: {(usage.get('server_tool_use') or {}).get('web_search_requests', 0)}"
        fetched_urls = {}
        for b in body.get("content", []):
            if b.get("type") == "web_fetch_tool_result":
                c = b.get("content") or {}
                if c.get("type") == "web_fetch_result":
                    fetched_urls[len(fetched_urls)] = (c.get("url", ""), (c.get("content") or {}).get("title", ""))
        for b in body.get("content", []):
            if b.get("type") != "text":
                continue
            for c in b.get("citations") or []:
                url = c.get("url") or fetched_urls.get(c.get("document_index", -1), ("", ""))[0]
                title = c.get("title") or c.get("document_title") or url
                quote = " ".join((c.get("cited_text") or "").split())
                if not url or not quote:
                    continue
                host = domain(url)
                basis, tier, kind = classify_domain(host, self.official)
                if primary_only and basis != "primary":
                    continue  # never let a secondary page into the primary search
                cleaned = clean(quote)
                sid = "web-" + short_hash(url, 10)
                src = next((s for s in res.sources if s.id == sid), None)
                if src is None:
                    src = self.source(q, sid, title, url, publisher=host, kind=kind, basis=basis, tier=tier)
                    res.sources.append(src)
                src.quarantined += cleaned.quarantined
                if not cleaned.text:
                    continue
                topics, direction = tag(cleaned.text)
                metrics = market_metrics(cleaned.text)
                res.facts.append(
                    self.fact(
                        src, cleaned.text, direction=direction, topics=topics, location="quoted passage", **metrics
                    )
                )
        return res


class Gdelt(Connector):
    id = "gdelt"
    name = "GDELT news"
    basis = "secondary"
    tier = "B"
    kind = "news"
    homepage = "https://www.gdeltproject.org"

    def run(self, q: ConnectorQuery) -> Result:
        params = {
            "query": q.params["query"],
            "mode": "artlist",
            "format": "json",
            "maxrecords": int(q.params.get("max", 75)),
            "timespan": q.params.get("timespan", "3m"),
        }
        if q.params.get("english_only", True):
            params["query"] += " sourcelang:english"
        body = self.http.get_json(
            self.id,
            "https://api.gdeltproject.org/api/v2/doc/doc",
            params,
        )
        res = Result(targeted=False)
        for a in (body.get("articles") or []) if isinstance(body, dict) else []:
            title, url = " ".join((a.get("title") or "").split()), a.get("url", "")
            if not title or not url:
                continue
            seen = a.get("seendate", "")
            date = f"{seen[:4]}-{seen[4:6]}-{seen[6:8]}" if len(seen) >= 8 else ""
            cleaned = clean(title)
            src = self.source(
                q, "news-" + short_hash(url, 10), title, url, published=date, publisher=a.get("domain", domain(url))
            )
            src.quarantined = cleaned.quarantined
            res.sources.append(src)
            if not cleaned.text:
                continue
            topics, direction = tag(cleaned.text)
            res.facts.append(
                self.fact(
                    src,
                    f'{a.get("domain", domain(url))} reported on {date}: "{cleaned.text}"',
                    direction=direction,
                    topics=sorted(set(topics + ["trend:news"])),
                    year=int(date[:4]) if date else None,
                    as_of=date,
                    location="headline",
                    geography=a.get("sourcecountry", ""),
                )
            )
        return res
