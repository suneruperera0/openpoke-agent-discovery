# Bounded agent discovery: final report

OpenPoke originally inserts the entire persistent-agent roster into each interaction
prompt. The implementation ranks owners, renders at most eight within a 4,096-byte
roster block, and provides search for the rest. Dispatch reuses existing identities;
new responsibilities require explicit creation.

## Final results

### Fresh offline holdout

Both rankers received identical requests, histories and rosters. Recall measures
whether the correct owner survives into the rendered shortlist, after byte trimming.

| Agents | V1 recall | Frozen V2 recall | V2 max roster bytes | Bound violations (both) |
| ---: | ---: | ---: | ---: | ---: |
| 10 | 100% | 100% | 2,371 | 0 |
| 100 | 25% | 90% | 2,380 | 0 |
| 500 | 25% | 86.7% | 2,453 | 0 |

At 500 agents, V1 found 15/60 owners and V2 found 52/60. First-search recall matched
shortlist recall in this run. Source: [fresh holdout JSON](results/retrieval-v2-heldout-once.json).
The historical V1 score of 60% used a different fixture set and is not the baseline
for this comparison.

### Pinned live sanity check

Two routing cases at 500 agents used `anthropic/claude-sonnet-4`. Execution-agent
work was simulated; the Interaction Agent made real model calls.

| Mean per trial, except counts | Original full roster | Frozen V2 |
| --- | ---: | ---: |
| Initial serialized request bytes | 39,248.5 | 17,958.5 |
| Total prompt tokens | 22,533 | 14,479.5 |
| Correct routing | 2/2 | 2/2 |
| New/unnecessary agents | 0 | 0 |
| Evaluator budget-cap failures | 2 | 0 |

Both cases routed correctly in both arms. The baseline then hit the evaluator's
per-trial reservation cap: each baseline trial received two model responses, versus
three for treatment. Token totals therefore describe the observed capped runs,
not equal-completion task costs; latency is also affected by that early exit.
Initial serialized request bytes include system text, tools and request settings;
they are distinct from the roster-block bytes in the offline table.
Total recorded cost: $0.23385. Source: [live JSON](results/live-final-v2-500.json).

The live runner pins original source `5b5f635935a64ab37884c025d70abb0ed731c094`
and treatment `a3baf789773cbd8d92220fc24874b1f7db68793a`. Later robustness changes
in `081cbfe` were not part of that live run; the frozen scorer remains unchanged.

## Reproduce from repository root

Use a full Git checkout so historical source commits are available. For tests,
create a Python 3.10+ environment and install backend dependencies:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r server/requirements.txt
.venv/bin/python -m unittest discover -s evals -p 'test_*.py' -v
```

Offline evaluators use the standard library and need no API keys. Choose fresh
output names to preserve saved evidence:

```bash
.venv/bin/python -m evals.baseline_roster_eval --output evals/results/my-baseline.json
.venv/bin/python -m evals.retrieval_v2_eval --split dev --output evals/results/my-v2-dev.json
.venv/bin/python -m evals.retrieval_v2_eval --split heldout --output evals/results/my-v2-heldout.json
```

The V2 evaluator reads current scorer source and pins V1 to `fd7b71d`. Verify the
hashes in [the scorer freeze manifest](retrieval_v2_freeze.json) and
[holdout freeze manifest](retrieval_v2_holdout_freeze.json) before reproduction.
Reproduction must not become tuning against the holdout. Frozen source docstrings
retain their wording from the time of freezing; the evaluator now supports both splits.

### Live runner prerequisite and optional reproduction

The live runner requires the original upstream commit, which is not an ancestor
of the clean imported fork history. If `git cat-file` fails, fetch that object from
upstream; this only retrieves objects and does not change the checkout:

```bash
git cat-file -e 5b5f635935a64ab37884c025d70abb0ed731c094^{commit}
# Only if the object is missing:
git fetch https://github.com/shlokkhemani/OpenPoke.git 5b5f635935a64ab37884c025d70abb0ed731c094
```

Validate the harness with scripted responses first (no paid model calls):

```bash
.venv/bin/python -m evals.live_routing_eval --sizes 500 --budget 0.30 --output evals/results/my-live-offline.json
```

The following is optional and **makes paid calls**, using `OPENROUTER_API_KEY` from
the environment or `.env`. Reuse the saved evidence unless a new run is needed:

```bash
.venv/bin/python -m evals.live_routing_eval --live --sizes 500 --budget 0.30 --per-trial-budget 0.16 --max-calls 3 --max-tokens 256 --output evals/results/my-live-v2.json
```

## Method and design

Each V2 split contains 14 authored tasks × 3 sizes × 5 seeds = **210 conditions**,
or **420 ranker executions** for the paired comparison. Recall uses 12 unique-owner
tasks × 5 seeds = 60 observations per size. New and ambiguous requests exercise
bounds only. Fixtures use nested rosters with overlapping responsibilities;
metadata comes from production history migration, not expected-owner labels.

The scorer uses field-aware BM25-style scoring, with name weight 1 and responsibility
weight 2, k1=1.2, and b=0.5. It takes the strongest field evidence per term, deduplicates
repeated history evidence, caps the length penalty at 1.5, and gives older user
context half weight. Simple plural folding, a small lexical alias map and a narrow
comma-delimited exclusion rule supplement lexical matching. Exact references and
recent delegation priority remain intact. Names and references are never normalized
for identity. The implementation is standard-library-only.

Development preceded the recorded scorer freeze. The fresh holdout was authored
and hashed after freezing, then evaluated once without further scorer changes.
Source hashes and per-condition fixture hashes are retained in the evidence.

## Evidence index

| Stage | Evidence | Purpose |
| --- | --- | --- |
| Original behavior | [baseline-roster.json](results/baseline-roster.json) | Full-roster context growth |
| Historical V1 | [routing-dev-v3.json](results/routing-dev-v3.json), [routing-heldout-v1.json](results/routing-heldout-v1.json) | First ranker's development and original 60% result |
| V2 development history | [dev-1](results/retrieval-v2-dev-1.json), [dev-2](results/retrieval-v2-dev-2.json) | Intermediate 500-agent recall: 16.7%, then 78.3% |
| Frozen V2 development | [dev-final](results/retrieval-v2-dev-final.json) | Final development recall: 100% at each size |
| Final retrieval quality | [heldout-once](results/retrieval-v2-heldout-once.json) | Fresh paired holdout; primary quality evidence |
| Live sanity check | [live-final-v2-500.json](results/live-final-v2-500.json) | Pinned two-case model run |
| Provenance | [scorer freeze](retrieval_v2_freeze.json), [holdout freeze](retrieval_v2_holdout_freeze.json) | Freeze times and file hashes |

Intermediate result files retain their original scorer hashes; they do not describe
the final scorer. Tests cover directory identity/migration, bounds, pagination,
creation/reuse, iteration limits and the actual prompt-construction path.

## Limitations

- Fixtures are synthetic and single-author; seeds are correlated repetitions, not
  independent language-understanding examples.
- V2 missed the targets of 95% at 100 and 90% at 500 agents. At 500 it missed five
  semantic-paraphrase and three topic-switch conditions. Lexical aliases and the
  narrow exclusion heuristic do not provide general semantic understanding.
- The live check covers two existing-owner cases, with owners named in the request
  or preceding context. It does not establish general routing accuracy, live creation
  quality or execution-agent task quality; the budget cap also limits cost comparisons.
- The bound applies to the roster block, not the complete conversation. This addresses
  roster-context growth, not every form of agent overload.
