# OpenPoke — Bounded Persistent Agent Discovery

This was built on top of the open-source
[OpenPoke](https://github.com/shlokkhemani/OpenPoke) project. I investigated one
concrete source of **agent overload**: the Interaction Agent receives the *full*
list of persistent Execution Agents on every request, so routing context grows
with the number of agents.

My solution replaces the full-roster prompt injection with a **bounded, ranked
shortlist** backed by a searchable agent directory, and improves which owners make
that shortlist using field-aware BM25-style retrieval — without giving up the
context bound.

## Presentation

- [View the take-home presentation (Google Slides)](https://docs.google.com/presentation/d/1ZxnuOo8bORoD9-M61jySKCTDu8VSOv_MrAuojnHjoCg/edit?usp=sharing)
- [Download / view the PDF in this repo](docs/takehome-presentation.pdf)

## The problem

OpenPoke inserts every persistent agent into the Interaction Agent prompt on each
request, so the roster block grows linearly with the roster:

| Agents | Roster context |
| ---: | ---: |
| 10 | ~501 B |
| 100 | ~4.9 KB |
| 500 | ~25 KB |

```
Original:
  User request → Interaction Agent → (every persistent agent injected)

Mine:
  User request → rank relevant agents → bounded shortlist → Interaction Agent
                                                   ↘ search full directory if needed
```

## The solution

A searchable persistent **`AgentDirectory`** that renders only a small ranked
shortlist into the prompt, while keeping the full directory reachable on demand:

- Searchable persistent agent directory with **stable agent refs**
- **At most 8 candidates** in the initial shortlist
- **At most 4,096 UTF-8 bytes** for the initial roster block
- On-demand **full-directory search** when the shortlist is insufficient
- **Deliberate agent creation** — unknown names are not silently created; new
  responsibilities require an explicit `create_agent` step
- **Field-aware BM25-style retrieval** to rank likely owners within that bound

Core implementation: [`server/services/execution/directory.py`](server/services/execution/directory.py).

## Results

### Retrieval quality — fresh holdout

The scorer was frozen before the holdout was authored, then V1 and V2 were run
once on the same unseen cases. **Recall here is retrieval recall**: whether the
known correct existing owner appeared in the top-8 shortlist — *not* model routing
accuracy.

| Agents | V1 recall | V2 recall | V2 roster block |
| ---: | ---: | ---: | ---: |
| 10 | 100% | 100% | 2.37 KB |
| 100 | 25% | 90% | 2.38 KB |
| 500 | 25% | 86.7% | 2.45 KB |

At 500 agents, correct-owner top-8 shortlist recall improved from **25% to 86.7%**
on the fresh holdout, while the rendered roster block stayed around **2.45 KB**
(vs ~25 KB for the original full roster) with zero context-bound violations.

Evidence: [`evals/results/retrieval-v2-heldout-once.json`](evals/results/retrieval-v2-heldout-once.json).

### Live model sanity check

Two routing cases at 500 agents, `anthropic/claude-sonnet-4`, with execution-agent
work simulated and the Interaction Agent making real model calls.

| Metric | Original | V2 |
| --- | ---: | ---: |
| Correct owner | 2/2 | 2/2 |
| Initial context | 39.25 KB | 17.96 KB |
| Observed prompt tokens | 22.53k | 14.48k |
| Evaluation-budget failures | 2 | 0 |

Same correct routing in both live cases, with **~54% less initial context** and
**~36% fewer observed prompt tokens**.

> **This is a 2-case live sanity check, not a large-scale benchmark.** The two
> baseline failures were evaluation-budget-cap failures that occurred *after* the
> correct owner was already selected — the baseline did not route incorrectly.
> Because the baseline stopped early at the budget cap, its trials completed fewer
> model responses than V2's, so the token totals describe observed capped runs,
> not an equal-completion efficiency comparison.

Evidence: [`evals/results/live-final-v2-500.json`](evals/results/live-final-v2-500.json).

## Evaluation methodology

```
development fixtures → improve V2 → freeze scorer → author fresh holdout
                                  → freeze holdout → run V1 and V2 on the same unseen cases
```

Freezing the scorer before authoring the holdout, and recording file hashes at each
step, keeps the V1→V2 comparison honest and prevents tuning against the holdout.

Key files:

- Baseline context growth: [`evals/BASELINE.md`](evals/BASELINE.md), [`evals/results/baseline-roster.json`](evals/results/baseline-roster.json)
- Historical V1 held-out result: [`evals/results/routing-heldout-v1.json`](evals/results/routing-heldout-v1.json)
- Scorer freeze manifest: [`evals/retrieval_v2_freeze.json`](evals/retrieval_v2_freeze.json)
- Fresh holdout fixtures: [`evals/retrieval_v2_holdout.py`](evals/retrieval_v2_holdout.py)
- Holdout freeze manifest: [`evals/retrieval_v2_holdout_freeze.json`](evals/retrieval_v2_holdout_freeze.json)
- Fresh holdout result: [`evals/results/retrieval-v2-heldout-once.json`](evals/results/retrieval-v2-heldout-once.json)
- Live sanity-check result: [`evals/results/live-final-v2-500.json`](evals/results/live-final-v2-500.json)

Full write-up: [`evals/RETRIEVAL_V2.md`](evals/RETRIEVAL_V2.md). Historical V1
report (pre-BM25 lexical ranker): [`evals/ROUTING_README.md`](evals/ROUTING_README.md).

## Run the offline evaluation

The offline tests and evaluators use the standard library and need no API keys or
Gmail connection:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r server/requirements.txt
.venv/bin/python -m unittest discover -s evals -p 'test_*.py' -v
```

## Limitations

- Evaluation data is synthetic.
- Random seeds are correlated repetitions, not independent real-world tasks.
- The live sanity check contains only two cases.
- BM25-style retrieval remains lexical and can miss semantic paraphrases.
- This addresses one concrete source of agent overload, not the whole problem.

**Potential next step:** hybrid lexical + semantic retrieval, evaluated against a
new frozen holdout.

## Upstream / attribution

This project builds on the open-source **OpenPoke** project by
[@shlokkhemani](https://github.com/shlokkhemani):
<https://github.com/shlokkhemani/OpenPoke>. OpenPoke is itself an open-source take
on [The Interaction Company](https://interaction.co/about)'s Poke assistant.

The original application code, architecture, and license are the work of the
OpenPoke authors. My take-home contribution is the bounded agent-discovery
implementation (`server/services/execution/directory.py` and the surrounding
interaction-agent wiring), the evaluation harnesses and evidence under `evals/`,
and this documentation. The upstream [`LICENSE`](LICENSE) (MIT) is preserved
unchanged.
