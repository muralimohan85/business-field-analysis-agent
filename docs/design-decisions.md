# Design decisions

## 1. Facts first, prose second

The unit of the system is a **fact**: one claim, one source, a date, a basis (primary or secondary), a tier (A
official, B reputable secondary, C other, U your upload), a kind (regulator, paper, trial, patent, statistics, filing,
news, upload) and topics. Framework builders read facts and write **statements**, and every statement lists the fact
ids it rests on. A report is a set of sections, each a set of blocks, each a set of statements or a gap.

This makes the governance checkable. "Is this sentence supported?" becomes a lookup, not a judgement call.

## 2. Two kinds of evidence, one switch

*Primary* evidence comes from statistics offices, regulators and registries, filings, papers, patents, trials, and your
own data. *Secondary* evidence covers news, press releases, research firms and the wider web. The primary report is
always complete on its own. The secondary search is a plan amendment: you choose which questions it serves and you
approve it. Its facts are stored with `basis: secondary`, so the same store rebuilds the report with or without them.
Secondary facts never feed a figure in the executive summary (`summary_min_tier`).

Press releases are secondary by default (`press_releases_primary: false`). They come from an interested party.

## 3. Governance against drift

| Drift | Guard |
|---|---|
| The research wanders off the field | Scope lock after approval: a fact must mention a scope term, a targeted query, or be your own data; excluded terms, out-of-brief geographies and old facts are set aside with the reason |
| The agent searches for things nobody asked | Query gate: every query names a plan question, uses a connector planned for it, and shares the plan's vocabulary |
| A model change shifts the output | Models pinned in settings; the manifest records models and prompt version; record and replay repeats a Claude run exactly (Opus 5.5 takes no temperature setting) |
| The same brief gives different evidence | Record and replay: every response is saved by request hash; `replay_test` compares the evidence hash and the statements |
| Spend runs away | Caps per call type and run time; skipped calls are listed |
| A source tries to steer the model | The sanitiser quarantines instruction-like sentences before extraction; the critic rejects statements that read like instructions |

## 4. Deterministic engine by default

The deterministic engine builds every section from templates over the facts. It is reproducible, offline and free,
which makes it the baseline the tests and the evaluation run on. The Claude engine adds value where language matters:
it proposes plan vocabulary and rewrites statements. It does this inside the same contract. The writer gets only the
facts a block already cites, it answers through a fixed tool schema, and the critic decides what stays. A statement
that fails falls back to the deterministic one.

## 5. The calculator owns the numbers

Market sizes, growth rates, scores, counts and sensitivities are **calculated facts**. A calculated fact has a claim,
a value and the ids of its inputs, and its basis is primary only if every input is primary. The numbers check accepts a
figure if it appears in a cited fact or in a calculator input. This is why the bottom-up SAM can be cited even though no
single source states it.

Published market estimates are never averaged. They are shown as a range with their sources.

## 6. Thresholds make gaps visible

A block needs two independent sources (`block_min_facts`), otherwise it carries a gap. A key finding needs three facts
from two kinds of source (`finding_min_facts`, `finding_min_kinds`); below that, it is shown as a signal. Gaps flow into
open questions, which are also the default input for a secondary search. In the demo, the customer segments rest on a
single survey, so each segment block shows its statements *and* a gap. That is the honest picture.

## 7. SWOT is about the subject

Strengths and weaknesses describe your company, so only facts about it count: uploads tagged as capability data, or
facts naming the company. Opportunities and threats describe the field. A fact goes to one side only: what the rivalry
analysis counts as a threat is not also listed as an opportunity. The agreement check enforces this.

## 8. Fictional data never wears a real organisation's name

The workspace could reach only the openFDA API, so the demo needed other evidence to show customer, market and
capability sections working. That evidence comes as two **uploads** from invented companies, and both say on every
page that they are fictional. The demo does not fabricate records attributed to real agencies or databases. Connector
parsing for the other APIs is tested on small synthetic payloads in the API's shape, kept inside the tests.

## 9. Exports share one document model

`render.build_doc` turns a report into a document with numbered citations once. Word, slides, PDF and Markdown are
written from it, so a statement carries the same source numbers in every format. Export is refused while a locked check
fails. Statements from your uploads are marked confidential or removed, as you choose.

## 10. Lessons from building it

* **The critic caught a bug in my own code.** Two findings produced calculated facts with the same claim and different
  inputs. The store's duplicate rule (same claim, same source) silently dropped the second one, so a statement cited a
  fact that did not exist. The citations check removed the statement before it reached the report. The fix was to
  identify calculations by claim *and* inputs.
* **Domain words leak across topics.** "Funding" tagged a public funding programme as a competitor move, and "share"
  tagged "share cases between labs" as rivalry. The topic rules now use phrases ("funding round", "market share").
* **A partial year is not a year.** Decisions dated 2026 are reported as year to date, so the trend compares only full
  years.
