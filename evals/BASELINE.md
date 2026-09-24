# Baseline: full agent roster growth

The original OpenPoke Interaction Agent inserts every existing Execution Agent
name into an `<active_agents>` block on each request. This offline evaluation
extracts that renderer from the clean source snapshot corresponding to pinned
upstream commit `5b5f635935a64ab37884c025d70abb0ed731c094` and measures the UTF-8 size of the
rendered block at 10, 100, and 500 agents.

It makes no model or network calls and does not import the bounded-routing
implementation.

```bash
.venv/bin/python -m evals.baseline_roster_eval \
  --output evals/results/my-baseline-roster.json
```

Expected result:

```text
Original OpenPoke — full agent roster
-------------------------------------
 10 agents  ->     501 bytes
100 agents  ->   4,905 bytes
500 agents  ->  24,964 bytes
```

The saved JSON contains all 105 measurements: seven representative roster
cases, three roster sizes, and five shuffled distractor seeds.

Use a fresh output filename to preserve the tracked `results/baseline-roster.json`.
