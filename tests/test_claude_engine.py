"""The Claude engine with a fake client: good statements are kept, bad ones fall back to the deterministic text."""

from bfa.checks import Critic
from bfa.connectors.base import Http
from bfa.engines.claude import ClaudeCaller, ClaudePlanner, ClaudeWriter, merge_proposal
from bfa.planner import build_plan


class FakeMessages:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def create(self, **kw):
        self.calls.append(kw)
        return {
            "content": [{"type": "tool_use", "name": kw["tools"][0]["name"], "input": self.answer(kw)}],
            "usage": {"input_tokens": 100, "output_tokens": 20},
        }


class FakeClient:
    def __init__(self, answer):
        self.messages = FakeMessages(answer)


def test_writer_keeps_grounded_and_drops_bad(demo_run, tmp_path):
    import json

    rep = demo_run.report.model_copy(deep=True)
    sec = rep.sections["regulatory"]
    blk = next(b for b in sec.blocks if b.statements and not b.gap)
    good = blk.statements[0]

    def answer(kw):
        payload = json.loads(kw["messages"][0]["content"])
        out = []
        for b in payload["blocks"]:
            if b["key"] == blk.key:
                out.append(
                    {
                        "key": b["key"],
                        "statements": [
                            {"text": good.text, "fact_ids": good.fact_ids, "judgement": False},
                            {
                                "text": "FDA has cleared 999 such devices.",
                                "fact_ids": good.fact_ids,
                                "judgement": False,
                            },
                        ],
                    }
                )
        return {"blocks": out}

    client = FakeClient(answer)
    caller = ClaudeCaller(Http(mode="live", snapshot="test"), client)
    critic = Critic(store=demo_run.store, cfg=demo_run.cfg)
    w = ClaudeWriter(demo_run.cfg, caller, critic)
    w.rewrite(rep)
    texts = [s.text for s in blk.statements]
    new_blk = next(b for b in rep.sections["regulatory"].blocks if b.key == blk.key)
    assert good.text in [s.text for s in new_blk.statements]
    assert not any("999" in s.text for s in new_blk.statements)
    assert texts  # original untouched
    kw = client.messages.calls[0]
    assert kw["tool_choice"] == {"type": "auto"}  # Opus 5.5 rejects forced tool choice
    assert "temperature" not in kw  # and non-default sampling
    assert kw["tools"][0]["strict"] and "Use only the facts given" in kw["system"]


def test_writer_cannot_cite_outside_its_block(demo_run):
    rep = demo_run.report.model_copy(deep=True)
    some_other = "ASM-A1"

    def answer(kw):
        import json

        payload = json.loads(kw["messages"][0]["content"])
        return {
            "blocks": [
                {
                    "key": b["key"],
                    "statements": [
                        {
                            "text": "Assumption A1 (yours): share digitised.",
                            "fact_ids": [some_other],
                            "judgement": False,
                        }
                    ],
                }
                for b in payload["blocks"]
            ]
        }

    caller = ClaudeCaller(Http(mode="live", snapshot="test"), FakeClient(answer))
    w = ClaudeWriter(demo_run.cfg, caller, Critic(store=demo_run.store, cfg=demo_run.cfg))
    w.rewrite(rep, skip=tuple(k for k in rep.sections if k != "pestle"))
    for b in rep.sections["pestle"].blocks:
        assert all(some_other not in s.fact_ids for s in b.statements)


def test_planner_proposes_vocabulary_only(brief, cfg):
    plan = build_plan(brief, cfg)
    answer = {"keywords": ["slide digitisation"], "scope_terms": ["virtual microscopy"], "exclude_terms": ["dental"]}
    caller = ClaudeCaller(Http(mode="live", snapshot="test"), FakeClient(lambda kw: answer))
    prop = ClaudePlanner(cfg, caller).propose(brief, plan)
    merged = merge_proposal(plan, prop)
    assert "virtual microscopy" in merged.scope_terms and "dental" in merged.exclude_terms
    assert not merged.approved


class RejectingMessages:
    """Behaves like the API for a key without credit (or any 400): every call raises."""

    def __init__(self):
        self.calls = 0

    def create(self, **kw):
        self.calls += 1

        class BadRequest(Exception):
            status_code = 400
            body = {"error": {"type": "invalid_request_error", "message": "Your credit balance is too low."}}

        raise BadRequest("Error code: 400")


def test_api_error_falls_back_to_deterministic_text(brief, cfg, tmp_path):
    from bfa.pipeline import run
    from tests.conftest import TODAY

    class Client:
        messages = RejectingMessages()

    r = run(brief, cfg, engine="claude", client=Client(), auto_approve=True, today=TODAY, workspace=tmp_path)
    assert all(c.passed for c in r.report.checks)
    assert r.report.summary and any("credit balance is too low" in n for n in r.manifest.notes)
    assert Client.messages.calls <= 2  # planner once, writer once: it stops asking after the first refusal


def test_temperature_and_strict_rejections_are_retried(demo_run):
    from bfa.engines.claude import ClaudeCaller

    class Msgs:
        def __init__(self):
            self.seen = []

        def create(self, **kw):
            self.seen.append(dict(kw))

            class E(Exception):
                status_code = 400

            if "temperature" in kw:
                e = E()
                e.body = {"error": {"message": "temperature is not supported for this model"}}
                raise e
            if kw["tools"][0].get("strict"):
                e = E()
                e.body = {"error": {"message": "strict tool use is not available"}}
                raise e
            return {"content": [{"type": "tool_use", "name": kw["tools"][0]["name"], "input": {"blocks": []}}]}

    class C:
        messages = Msgs()

    caller = ClaudeCaller(Http(mode="live", snapshot="test"), C())
    from bfa.engines.claude import WRITER_TOOL

    assert caller.tool_call("claude-opus-5-5", "s", WRITER_TOOL, {"x": 1}, temperature=0.2) == {"blocks": []}
    assert len(C.messages.seen) == 3
