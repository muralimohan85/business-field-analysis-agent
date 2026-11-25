"""Connector plumbing: polite HTTP with record and replay.

Modes
  live    call the API
  record  call the API and save each response under data/snapshots/<snapshot>/<connector>/
  replay  read saved responses only (no network); a missing response is reported, never invented

Every connector turns raw API records into Sources and Facts with plain code. No model
reads or rewrites a structured record, so a database number reaches the report unchanged.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlencode

from bfa.config import DATA_DIR
from bfa.schemas import ConnectorQuery, Fact, Source, now_iso, short_hash

SNAPSHOT_DIR = DATA_DIR / "snapshots"


class SnapshotMissing(RuntimeError):
    pass


class ConnectorError(RuntimeError):
    pass


def contact_agent() -> str:
    email = os.environ.get("BFA_CONTACT_EMAIL", "bfa-agent@example.com")
    return f"business-field-analysis-agent/0.1 ({email})"


@dataclass
class Http:
    mode: str = "replay"  # live | record | replay
    snapshot: str = "default"
    min_interval: dict = field(default_factory=dict)  # connector -> seconds between calls
    _last: dict = field(default_factory=dict)
    calls: list = field(default_factory=list)

    def _path(self, connector: str, key: str) -> Path:
        return SNAPSHOT_DIR / self.snapshot / connector / f"{key}.json"

    def get_json(
        self,
        connector: str,
        url: str,
        params: dict | None = None,
        headers: dict | None = None,
        method: str = "GET",
        body: dict | None = None,
        secret_params: tuple = (),
    ) -> dict | list:
        public = {k: v for k, v in (params or {}).items() if k not in secret_params}
        key = short_hash({"u": url, "p": public, "b": body}, 16)
        path = self._path(connector, key)
        shown = url + ("?" + urlencode(public, doseq=True) if public else "")
        if self.mode == "replay":
            if not path.exists():
                raise SnapshotMissing(f"{connector}: no recorded response for {shown}")
            data = json.loads(path.read_text())
            self.calls.append({"connector": connector, "url": shown, "mode": "replay", "fetched": data["fetched"]})
            return data["body"]
        import httpx

        gap = self.min_interval.get(connector, 0.34)
        wait = self._last.get(connector, 0) + gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        hdrs = {"User-Agent": contact_agent(), "Accept": "application/json", **(headers or {})}
        r = None
        for attempt in range(2):  # one retry for a transient server error
            try:
                if method == "POST":
                    r = httpx.post(url, params=params, json=body, headers=hdrs, timeout=30)
                else:
                    r = httpx.get(url, params=params, headers=hdrs, timeout=30, follow_redirects=True)
            except httpx.HTTPError as exc:
                if attempt:
                    raise ConnectorError(f"{connector}: {exc}") from exc
                time.sleep(2)
                continue
            if r.status_code < 500:
                break
            time.sleep(2)
        self._last[connector] = time.monotonic()
        if r.status_code == 404:
            body_json: dict | list = {"results": [], "_status": 404}
        elif r.status_code >= 400:
            raise ConnectorError(f"{connector}: HTTP {r.status_code} for {shown}")
        else:
            body_json = r.json()
        fetched = now_iso()
        self.calls.append({"connector": connector, "url": shown, "mode": self.mode, "fetched": fetched})
        if self.mode == "record":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"url": shown, "fetched": fetched, "body": body_json}, indent=1))
        return body_json

    def snapshot_date(self, connector: str) -> str:
        d = SNAPSHOT_DIR / self.snapshot / connector
        if not d.exists():
            return ""
        dates = sorted(json.loads(p.read_text()).get("fetched", "")[:10] for p in d.glob("*.json"))
        return dates[-1] if dates else ""


@dataclass
class Result:
    sources: list[Source] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    targeted: bool = True  # structured lookup aimed at the field (scope lock trusts it)
    note: str = ""


class Connector:
    id = "base"
    name = "Base"
    basis = "primary"
    tier = "A"
    kind = "statistics"
    key_env = ""  # environment variable holding an API key
    key_required = False
    key_hint = "free key"
    homepage = ""

    def __init__(self, http: Http):
        self.http = http

    @property
    def api_key(self) -> str:
        return os.environ.get(self.key_env, "") if self.key_env else ""

    def available(self) -> tuple[bool, str]:
        if self.key_required and not self.api_key and self.http.mode != "replay":
            return False, f"set {self.key_env} ({self.key_hint})"
        return True, ""

    def run(self, q: ConnectorQuery) -> Result:  # pragma: no cover - interface
        raise NotImplementedError

    # helpers -------------------------------------------------------------
    def source(
        self,
        q: ConnectorQuery,
        sid: str,
        title: str,
        url: str,
        published: str = "",
        publisher: str = "",
        text: str = "",
        kind: str | None = None,
        basis: str | None = None,
        tier: str | None = None,
    ) -> Source:
        return Source(
            id=sid,
            connector=self.id,
            basis=basis or self.basis,
            tier=tier or self.tier,
            kind=kind or self.kind,
            title=title,
            url=url,
            publisher=publisher or self.name,
            published=published,
            fetched=now_iso(),
            query_id=q.question_id,
            text=text,
        )

    def fact(self, src: Source, claim: str, **kw) -> Fact:
        fid = kw.pop("fid", None) or f"{self.id.upper()[:4]}-{short_hash([src.id, claim], 8)}"
        return Fact(
            id=fid,
            source_id=src.id,
            claim=claim,
            basis=src.basis,
            tier=src.tier,
            kind=src.kind,
            as_of=kw.pop("as_of", src.published or src.fetched[:10]),
            **kw,
        )
