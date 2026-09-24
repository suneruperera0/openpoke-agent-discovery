"""Measure full-roster prompt growth in the pinned original OpenPoke code."""
from __future__ import annotations

import argparse
import ast
from html import escape
import json
from pathlib import Path
import random
import subprocess
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
BASELINE_COMMIT = "5b5f635935a64ab37884c025d70abb0ed731c094"
BASELINE_SOURCE_COMMIT = "659e03c7a45e418f403200e6b36623d297b37626"
SIZES = (10, 100, 500)
SEEDS = range(5)

# Held-out-style owners used only to make representative rosters. The evaluator
# never calls a model and never imports the bounded-routing implementation.
CASES = [
    ("ops::Nacre/returns", None),
    ("case-42", None),
    ("Facilities notebook", None),
    ("support-17", None),
    ("closed-notes-6", None),
    (None, None),
    ("Priya incident desk", "Priya procurement desk"),
]
PROJECTS = ["Cedar", "Birch", "Harbor", "Atlas", "Nacre", "Sequoia", "Lumen", "Solstice"]
CONTACTS = ["Maya", "Leo", "Inez", "Omar", "Priya", "Noor"]
DUTIES = ["invoice approval", "travel booking", "weekly reporting", "delivery scheduling", "budget planning", "access audit"]


def original_renderer():
    """Extract the renderer directly from the pinned baseline commit."""
    source = subprocess.check_output(
        ["git", "show", f"{BASELINE_SOURCE_COMMIT}:server/agents/interaction_agent/agent.py"],
        cwd=ROOT,
        text=True,
    )
    function = next(
        node for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == "_render_active_agents"
    )
    code = compile(ast.Module(body=[function], type_ignores=[]), "pinned-baseline", "exec")

    def render(names: list[str]) -> str:
        env = {
            "escape": escape,
            "get_agent_roster": lambda: SimpleNamespace(
                load=lambda: None,
                get_agents=lambda: names,
            ),
        }
        exec(code, env)
        return "<active_agents>\n" + env["_render_active_agents"]() + "\n</active_agents>"

    return render


def roster(owner: str | None, alternate: str | None, size: int, seed: int) -> list[str]:
    rng = random.Random(seed)
    names = [name for name in (owner, alternate) if name]
    while len(names) < size:
        index = len(names)
        names.append(
            f"{rng.choice(PROJECTS)} {rng.choice(CONTACTS)} {rng.choice(DUTIES)} #{index}"
        )
    rng.shuffle(names)
    return names


def evaluate() -> dict:
    render = original_renderer()
    runs = []
    for case_index, (owner, alternate) in enumerate(CASES):
        for size in SIZES:
            for seed in SEEDS:
                names = roster(owner, alternate, size, seed)
                runs.append({
                    "case": case_index,
                    "agents": size,
                    "seed": seed,
                    "roster_bytes": len(render(names).encode("utf-8")),
                })
    summary = []
    for size in SIZES:
        values = [run["roster_bytes"] for run in runs if run["agents"] == size]
        summary.append({
            "agents": size,
            "executions": len(values),
            "mean_roster_bytes": round(sum(values) / len(values)),
            "min_roster_bytes": min(values),
            "max_roster_bytes": max(values),
        })
    return {
        "evaluation": "original full-agent roster growth",
        "baseline_commit": BASELINE_COMMIT,
        "baseline_source_commit": BASELINE_SOURCE_COMMIT,
        "authored_roster_cases": len(CASES),
        "shuffled_seeds": len(SEEDS),
        "total_executions": len(runs),
        "summary": summary,
        "runs": runs,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("Original OpenPoke — full agent roster")
    print("-------------------------------------")
    for row in result["summary"]:
        print(f'{row["agents"]:>3} agents  ->  {row["mean_roster_bytes"]:>6,} bytes')


if __name__ == "__main__":
    main()
