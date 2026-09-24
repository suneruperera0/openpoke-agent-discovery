# Historical V1: bounded discovery evaluation

This report records the first lexical-IDF ranker (`lexical-idf-v2`), before BM25 V2.
For the current implementation and final evidence, start with the
[final report](RETRIEVAL_V2.md).

The first implementation replaced the original full roster with a bounded shortlist
and on-demand search. Its evaluation showed that bounding context worked, but owner
retrieval weakened as the roster grew. That finding motivated V2.

## Historical results

| Split | Agents | Name-only shortlist / search recall | Enriched shortlist / search recall | Max enriched roster bytes | Mean original roster bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| Development | 10 | 84% / 40% | 100% / 100% | 2,570 | 503 |
| Development | 100 | 40% / 40% | 100% / 100% | 2,801 | 4,907 |
| Development | 500 | 40% / 40% | 100% / 100% | 2,909 | 24,966 |
| Held-out | 10 | 80% / 20% | 100% / 100% | 2,684 | 501 |
| Held-out | 100 | 20% / 20% | 92% / 92% | 2,938 | 4,905 |
| Held-out | 500 | 20% / 20% | 60% / 60% | 3,083 | 24,964 |

Sources: [development JSON](results/routing-dev-v3.json) and
[held-out JSON](results/routing-heldout-v1.json). This historical 60% is not the
baseline score on V2's fresh holdout; that separate paired comparison is 25% → 86.7%.

## Method

14 authored tasks, seven per split, cover explicit owners, follow-ups, paraphrases,
overlapping work, old owners, new responsibilities and ambiguity. Each task runs
at 10/100/500 agents with five seeds: 105 conditions per split, 210 total, each
scored in name-only and metadata-enriched variants. Unique-owner recall excludes
new and ambiguous tasks (25 eligible observations per size per split).

Queries use the actual request plus bounded recent-user context. Enriched shortlist
and first-search recall matched in this experiment; name-only recall sometimes
differed because shortlist explicit-name prioritization uses the latest request.
Original full-roster bytes were measured with the original renderer; they are not
a real-model routing score. Development preceded the historical held-out run.

## Reproduce the historical version

The evaluator loads the working tree's `directory.py`. Running it on final `main`
uses BM25 V2 and will not reproduce this table. From the current repo root, create
a separate checkout of the historical evaluation commit:

```bash
git worktree add --detach ../OpenPoke-v1-evidence e47c2bf
```

Then enter that checkout and run with Python 3.10+ (standard library only):

```bash
cd ../OpenPoke-v1-evidence
python3 -m evals.routing_eval --split dev --output evals/results/my-routing-dev.json
python3 -m evals.routing_eval --split heldout --output evals/results/my-routing-heldout.json
```

Use an unused worktree path and fresh output names. This preserves your current
checkout and tracked results. The evaluator extracts the original renderer from
clean imported baseline `659e03c7…`, corresponding to upstream `5b5f635…`.
Do not tune retrieval using this historical holdout. Shared test instructions,
limitations and the evidence index are in the [final report](RETRIEVAL_V2.md).
