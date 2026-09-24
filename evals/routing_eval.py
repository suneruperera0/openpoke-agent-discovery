"""Offline retrieval benchmark. Does not import the app or call a model."""
import argparse
import ast
from collections import defaultdict
import hashlib
from html import escape
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace

from evals.routing_fixtures import TASKS, fixture, transcript

ROOT = Path(__file__).resolve().parents[1]
BASELINE_COMMIT = "5b5f635935a64ab37884c025d70abb0ed731c094"
BASELINE_SOURCE_COMMIT = "659e03c7a45e418f403200e6b36623d297b37626"
SOURCE = ROOT / "server/services/execution/directory.py"


def directory_module():
    spec = importlib.util.spec_from_file_location("routing_directory", SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def baseline_renderer():
    source = subprocess.check_output(["git", "show", f"{BASELINE_SOURCE_COMMIT}:server/agents/interaction_agent/agent.py"], cwd=ROOT, text=True)
    # Execute the pinned rendering function with only the roster dependency replaced.
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "_render_active_agents")
    code = compile(ast.Module(body=[node], type_ignores=[]), "pinned-baseline", "exec")
    def render(names):
        env = {"escape": escape, "get_agent_roster": lambda: SimpleNamespace(load=lambda: None, get_agents=lambda: names)}
        exec(code, env)
        return '<active_agents>\n' + env["_render_active_agents"]() + '\n</active_agents>'
    return render


def seed_directory(module, path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([n for n, _ in entries]))
    histories = dict(entries)
    return module.AgentDirectory(path, history_loader=lambda n: [histories[n]])


def evaluate(split):
    mod, render, runs = directory_module(), baseline_renderer(), []
    for task in [t for t in TASKS if t["split"] == split]:
        for size in (10, 100, 500):
            for seed in range(5):
                entries = fixture(task, size, seed)
                with tempfile.TemporaryDirectory(prefix="routing-retrieval-") as tmp:
                    directory = seed_directory(mod, Path(tmp)/"roster.json", entries)
                    query = mod.retrieval_query(task["request"], transcript(task))
                    variants = {}
                    for enriched in (False, True):
                        block = directory.shortlist(task["request"], transcript(task), enriched)
                        shortlist = json.loads(block.split('\n', 1)[1].rsplit('\n', 1)[0])["candidates"]
                        search = directory.search(query, enriched=enriched)["candidates"]
                        owner = mod.reference(task["name"]) if task["name"] else None
                        variants["enriched" if enriched else "name_only"] = {
                            "shortlist_refs": [r["ref"] for r in shortlist], "search_refs": [r["ref"] for r in search],
                            "shortlist_recall": owner in [r["ref"] for r in shortlist] if owner else None,
                            "first_search_recall": owner in [r["ref"] for r in search] if owner else None,
                            "roster_bytes": len(block.encode())}
                    runs.append({"split": split, "family": task["family"], "size": size, "seed": seed,
                        "query": query, "expected_name": task["name"], "baseline_roster_bytes": len(render([n for n, _ in entries]).encode()),
                        "baseline_owner_available": bool(task["name"]), "variants": variants})
    return runs


def summary(runs):
    rows = []
    for size in (10, 100, 500):
        group = [r for r in runs if r["size"] == size]
        if not group:
            continue
        for variant in ("name_only", "enriched"):
            eligible = [r for r in group if r["family"] not in ("new", "ambiguous")]
            rows.append({"size": size, "variant": variant, "unambiguous_cases": len(eligible),
                         "shortlist_recall": sum(r["variants"][variant]["shortlist_recall"] for r in eligible)/len(eligible),
                         "first_search_recall": sum(r["variants"][variant]["first_search_recall"] for r in eligible)/len(eligible),
                         "max_roster_bytes": max(r["variants"][variant]["roster_bytes"] for r in group),
                         "mean_baseline_bytes": round(sum(r["baseline_roster_bytes"] for r in group)/len(group))})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["dev", "heldout"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output exists; choose a fresh evidence filename")
    runs = evaluate(args.split)
    result = {"kind": "offline retrieval, not model routing", "baseline_commit": BASELINE_COMMIT, "baseline_source_commit": BASELINE_SOURCE_COMMIT,
              "ranker_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
              "fixtures_sha256": hashlib.sha256((ROOT/'evals/routing_fixtures.py').read_bytes()).hexdigest(),
              "distinct_authored_tasks": 7, "fixture_executions": len(runs), "summary": summary(runs), "runs": runs}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k != "runs"}, indent=2))


if __name__ == "__main__":
    main()
