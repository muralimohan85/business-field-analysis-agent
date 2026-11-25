"""Spend is capped (rule 9). At the cap the run stops that kind of call cleanly and lists what it skipped."""

from __future__ import annotations

import time

from bfa.config import SEARCH_FEE_PER_1000, LimitsCfg


class BudgetExceeded(RuntimeError):
    pass


class Budget:
    def __init__(self, limits: LimitsCfg):
        self.caps = {
            "web_searches": limits.web_searches,
            "secondary_searches": limits.secondary_searches,
            "fetches": limits.fetches,
        }
        self.used = {k: 0 for k in self.caps}
        self.records = 0
        self.tokens = {"input": 0, "output": 0}
        self.skipped: list[str] = []
        self.started = time.monotonic()
        self.max_seconds = limits.run_minutes * 60

    def can(self, kind: str, n: int = 1) -> bool:
        return self.used.get(kind, 0) + n <= self.caps.get(kind, 10**9)

    def spend(self, kind: str, n: int = 1, what: str = "") -> None:
        if time.monotonic() - self.started > self.max_seconds:
            self.skipped.append(f"{what or kind}: run time cap reached")
            raise BudgetExceeded("run time cap reached")
        if not self.can(kind, n):
            self.skipped.append(f"{what or kind}: {kind} cap of {self.caps[kind]} reached")
            raise BudgetExceeded(f"{kind} cap of {self.caps[kind]} reached")
        self.used[kind] = self.used.get(kind, 0) + n

    def add_tokens(self, input_tokens: int, output_tokens: int) -> None:
        self.tokens["input"] += input_tokens
        self.tokens["output"] += output_tokens

    def search_fees(self) -> float:
        n = self.used["web_searches"] + self.used["secondary_searches"]
        return round(n * SEARCH_FEE_PER_1000 / 1000, 2)

    def as_dict(self) -> dict:
        return {
            "caps": self.caps,
            "used": self.used,
            "records": self.records,
            "tokens": self.tokens,
            "search_fees_usd": self.search_fees(),
            "skipped": self.skipped,
        }
