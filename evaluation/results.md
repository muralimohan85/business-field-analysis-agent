# Evaluation results

Demo run `2026-11-25-fe1025` (recorded openFDA snapshot + fictional sample uploads), deterministic engine.

## Critic: seeded faults

| Fault | Seeded | Caught |
|---|---|---|
| number changed | 143 | 143 (100%) |
| citation removed | 224 | 224 (100%) |
| cites a secondary fact | 60 | 60 (100%) |
| instruction injected | 224 | 224 (100%) |
| cites a set-aside fact | 60 | 60 (100%) |
| unsupported claim | 60 | 60 (100%) |
| estimates averaged | 60 | 60 (100%) |

False alarms on the 224 original statements: **0**. Numbers traced: 282.

## Query gate: drift

- Planned queries passed: **28/28**
- Drifting queries blocked: **22/22**

## Replay

- Same evidence (fact hash `64882fd2167e7c88`): **True**
- Same statements (224): **True**

Report checks passed: 10/10.
