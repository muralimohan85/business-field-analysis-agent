"""The evidence store: one SQLite file per run.

Every sentence in the report cites fact ids that exist here. Sources keep their basis
(primary or secondary), tier and any text the sanitiser quarantined. Facts keep the
source, date, scope decision and the facts a calculated value was computed from.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from bfa.schemas import BlockedQuery, Fact, Source, short_hash

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
  id TEXT PRIMARY KEY, connector TEXT, basis TEXT, tier TEXT, kind TEXT, title TEXT, url TEXT, publisher TEXT,
  published TEXT, fetched TEXT, query_id TEXT, text TEXT, quarantined TEXT, fictional INTEGER
);
CREATE TABLE IF NOT EXISTS facts (
  id TEXT PRIMARY KEY, source_id TEXT, claim TEXT, entity TEXT, metric TEXT, value REAL, unit TEXT, year INTEGER,
  geography TEXT, topics TEXT, basis TEXT, tier TEXT, kind TEXT, as_of TEXT, location TEXT, direction TEXT,
  in_scope INTEGER, scope_note TEXT, inputs TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(id UNINDEXED, claim, entity, topics);
CREATE TABLE IF NOT EXISTS blocked (
  id INTEGER PRIMARY KEY AUTOINCREMENT, connector TEXT, text TEXT, question_id TEXT, reason TEXT, at TEXT
);
CREATE TABLE IF NOT EXISTS calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT, step TEXT, tool TEXT, args TEXT, result TEXT, at TEXT
);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
"""

_FACT_COLS = (
    "id",
    "source_id",
    "claim",
    "entity",
    "metric",
    "value",
    "unit",
    "year",
    "geography",
    "topics",
    "basis",
    "tier",
    "kind",
    "as_of",
    "location",
    "direction",
    "in_scope",
    "scope_note",
    "inputs",
)


class Store:
    def __init__(self, path: str | Path = ":memory:"):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    # ------------------------------------------------------------------ sources
    def add_source(self, s: Source) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO sources VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                s.id,
                s.connector,
                s.basis,
                s.tier,
                s.kind,
                s.title,
                s.url,
                s.publisher,
                s.published,
                s.fetched,
                s.query_id,
                s.text,
                json.dumps(s.quarantined),
                int(s.fictional),
            ),
        )
        self.db.commit()

    def source(self, sid: str) -> Source | None:
        r = self.db.execute("SELECT * FROM sources WHERE id=?", (sid,)).fetchone()
        return self._source(r) if r else None

    def sources(self, basis: str | None = None) -> list[Source]:
        q, args = "SELECT * FROM sources", ()
        if basis:
            q, args = q + " WHERE basis=?", (basis,)
        return [self._source(r) for r in self.db.execute(q + " ORDER BY connector, published", args)]

    @staticmethod
    def _source(r: sqlite3.Row) -> Source:
        d = dict(r)
        d["quarantined"] = json.loads(d["quarantined"] or "[]")
        d["fictional"] = bool(d["fictional"])
        return Source(**d)

    # ------------------------------------------------------------------ facts
    def add_fact(self, f: Fact) -> str:
        """Insert a fact. A fact with the same claim from the same connector corroborates the first one."""
        if f.source_id != "calculator":  # a calculation is identified by its claim and its inputs (the id)
            dup = self.db.execute(
                "SELECT id FROM facts WHERE claim=? AND source_id=?", (f.claim, f.source_id)
            ).fetchone()
            if dup:
                return dup["id"]
        row = f.model_dump()
        row["topics"] = json.dumps(f.topics)
        row["inputs"] = json.dumps(f.inputs)
        row["in_scope"] = int(f.in_scope)
        self.db.execute(
            f"INSERT OR REPLACE INTO facts VALUES ({','.join('?' * len(_FACT_COLS))})",
            tuple(row[c] for c in _FACT_COLS),
        )
        self.db.execute("DELETE FROM facts_fts WHERE id=?", (f.id,))
        self.db.execute("INSERT INTO facts_fts VALUES (?,?,?,?)", (f.id, f.claim, f.entity, " ".join(f.topics)))
        self.db.commit()
        return f.id

    def fact(self, fid: str) -> Fact | None:
        r = self.db.execute("SELECT * FROM facts WHERE id=?", (fid,)).fetchone()
        return self._fact(r) if r else None

    def facts(
        self,
        *,
        in_scope: bool | None = True,
        basis: str | None = None,
        topic: str | None = None,
        include_secondary: bool = True,
    ) -> list[Fact]:
        q, args = "SELECT * FROM facts WHERE 1=1", []
        if in_scope is not None:
            q += " AND in_scope=?"
            args.append(int(in_scope))
        if basis:
            q += " AND basis=?"
            args.append(basis)
        elif not include_secondary:
            q += " AND basis='primary'"
        out = [self._fact(r) for r in self.db.execute(q + " ORDER BY id", args)]
        if topic:
            out = [f for f in out if any(t == topic or t.startswith(topic + ":") for t in f.topics)]
        return out

    def search(self, query: str, limit: int = 20, include_secondary: bool = True) -> list[Fact]:
        terms = [t for t in "".join(c if c.isalnum() else " " for c in query).split() if len(t) > 2]
        if not terms:
            return []
        match = " OR ".join(f'"{t}"' for t in terms)
        rows = self.db.execute(
            "SELECT id FROM facts_fts WHERE facts_fts MATCH ? ORDER BY rank LIMIT ?", (match, limit * 3)
        ).fetchall()
        out = []
        for r in rows:
            f = self.fact(r["id"])
            if f and f.in_scope and (include_secondary or f.basis == "primary"):
                out.append(f)
        return out[:limit]

    @staticmethod
    def _fact(r: sqlite3.Row) -> Fact:
        d = dict(r)
        d["topics"] = json.loads(d["topics"] or "[]")
        d["inputs"] = json.loads(d["inputs"] or "[]")
        d["in_scope"] = bool(d["in_scope"])
        return Fact(**d)

    def fact_hash(self) -> str:
        """Hash of the in-scope facts' claims and values: the replay test compares this."""
        rows = self.db.execute("SELECT claim, value FROM facts WHERE in_scope=1 ORDER BY claim").fetchall()
        return short_hash([[r["claim"], r["value"]] for r in rows], 16)

    # ------------------------------------------------------------------ governance logs
    def log_blocked(self, b: BlockedQuery) -> None:
        self.db.execute(
            "INSERT INTO blocked (connector, text, question_id, reason, at) VALUES (?,?,?,?,?)",
            (b.connector, b.text, b.question_id, b.reason, b.at),
        )
        self.db.commit()

    def blocked(self) -> list[BlockedQuery]:
        return [
            BlockedQuery(**{k: r[k] for k in ("connector", "text", "question_id", "reason", "at")})
            for r in self.db.execute("SELECT * FROM blocked ORDER BY id")
        ]

    def log_call(self, step: str, tool: str, args: dict, result: str, at: str) -> None:
        self.db.execute(
            "INSERT INTO calls (step, tool, args, result, at) VALUES (?,?,?,?,?)",
            (step, tool, json.dumps(args, default=str), result[:500], at),
        )
        self.db.commit()

    def calls(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT step, tool, args, result, at FROM calls ORDER BY id")]

    def set(self, key: str, value) -> None:
        self.db.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (key, json.dumps(value, default=str)))
        self.db.commit()

    def get(self, key: str, default=None):
        r = self.db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(r["value"]) if r else default

    def counts(self) -> dict:
        one = lambda q: self.db.execute(q).fetchone()[0]  # noqa: E731
        return {
            "sources": one("SELECT COUNT(*) FROM sources"),
            "facts": one("SELECT COUNT(*) FROM facts WHERE in_scope=1"),
            "primary_facts": one("SELECT COUNT(*) FROM facts WHERE in_scope=1 AND basis='primary'"),
            "secondary_facts": one("SELECT COUNT(*) FROM facts WHERE in_scope=1 AND basis='secondary'"),
            "set_aside": one("SELECT COUNT(*) FROM facts WHERE in_scope=0"),
            "blocked": one("SELECT COUNT(*) FROM blocked"),
        }
