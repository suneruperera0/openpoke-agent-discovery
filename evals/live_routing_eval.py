"""Capped paired live-model routing pilot. External execution tools are simulated."""
from __future__ import annotations
import argparse
import asyncio
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tarfile
import tempfile
import time
from types import SimpleNamespace
from urllib.request import urlopen, Request

ROOT = Path(__file__).resolve().parents[1]
BASE = "5b5f635935a64ab37884c025d70abb0ed731c094"
# Treatment is pinned to the frozen field-aware BM25 V2 commit for reproducible provenance,
# instead of copying the mutable working tree.
TREATMENT = "a3baf789773cbd8d92220fc24874b1f7db68793a"
MODEL = "anthropic/claude-sonnet-4"
INPUT_PER_M = 3.0
OUTPUT_PER_M = 15.0

# Frozen before live execution. These are distinct from development/held-out retrieval tasks.
CASES = [
    {"id": "final-explicit-orchid", "request": "Ask the Orchid launch coordinator to continue the launch readiness update.",
     "owner": "Orchid launch coordinator", "history": "Own Project Orchid launch readiness updates with Elena. Launch code ORC-719."},
    {"id": "final-contextual-raven", "request": "Continue that follow-up with the agreed owner.",
     "context": "We previously assigned Marcus's Raven compliance renewal to the regulatory notebook.",
     "owner": "regulatory notebook", "history": "Own Raven compliance renewals with Marcus. Filing reference RVN-204."},
]

def distractors(size, seed, target):
    rng = random.Random(seed)
    projects = ["Orchid", "Raven", "Juniper", "Quartz", "Nimbus", "Topaz"]
    people = ["Elena", "Marcus", "Hana", "Dev", "Sofia"]
    duties = ["invoice review", "launch catering", "compliance audit", "weekly notes", "delivery plan"]
    rows = [(target["owner"], target["history"])]
    while len(rows) < size:
        i = len(rows); p, person, duty = rng.choice(projects), rng.choice(people), rng.choice(duties)
        rows.append((f"{p} {person} {duty} #{i}", f"Own {p} {duty} with {person}. Reference {p[:3].upper()}-{100+i}."))
    rng.shuffle(rows)
    return rows

def estimated_cost(usage):
    return usage.get("prompt_tokens", 0) / 1_000_000 * INPUT_PER_M + usage.get("completion_tokens", 0) / 1_000_000 * OUTPUT_PER_M

def reported_cost(usage):
    value = usage.get("cost")
    return float(value) if isinstance(value, (int, float)) else estimated_cost(usage)

def post_openrouter(key, payload):
    req = Request("https://openrouter.ai/api/v1/chat/completions", data=json.dumps(payload).encode(),
                  headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=60) as response:
            return json.loads(response.read())
    except Exception as exc:
        detail = getattr(exc, "read", lambda: b"")().decode(errors="replace")
        raise RuntimeError(f"OpenRouter call failed: {type(exc).__name__}: {detail[:1000]}") from exc

def write_history(data_dir, name, history):
    slug = "".join(c.lower() if c.isalnum() else "-" for c in name.strip()).strip("-")
    while "--" in slug: slug = slug.replace("--", "-")
    path = data_dir / "execution_agents" / f"{slug or 'agent'}.log"
    safe = history.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    path.write_text(f'<agent_request timestamp="2026-09-01 09:00:00">{safe}</agent_request>\n')

async def worker(args):
    sys.path.insert(0, str(Path.cwd()))
    from server.config import get_settings
    from server.agents.interaction_agent import runtime as ir, tools as it
    from server.services.execution import get_agent_roster

    case = next(c for c in CASES if c["id"] == args.case)
    settings = get_settings(); settings.openrouter_api_key = "live-eval"; settings.interaction_agent_model = MODEL
    if hasattr(settings, "conversation_summary_threshold"): settings.conversation_summary_threshold = 0
    calls, usages, estimated, events, selected, request_bytes = 0, [], 0.0, [], [], []
    origin = time.monotonic()

    async def model_call(*, model, messages, system=None, api_key=None, tools=None, **kwargs):
        nonlocal calls, estimated
        calls += 1
        if calls > args.max_calls: raise RuntimeError("evaluation model-call cap reached")
        body = {"model": model, "messages": ([{"role":"system","content":system}] if system else []) + messages,
                "tools": tools, "stream": False, "max_tokens": args.max_tokens}
        encoded_bytes = len(json.dumps(body, ensure_ascii=False).encode())
        request_bytes.append(encoded_bytes)
        approx_input = max(1, encoded_bytes // 4)
        reserve = 2 * approx_input / 1_000_000 * INPUT_PER_M + args.max_tokens / 1_000_000 * OUTPUT_PER_M
        if estimated + reserve > args.trial_budget:
            raise RuntimeError("trial budget reservation exceeded")
        estimated += reserve
        if args.live:
            result = await asyncio.to_thread(post_openrouter, os.environ["OPENROUTER_API_KEY"], body)
        elif calls == 1:
            result = {"choices":[{"finish_reason":"tool_calls","message":{"role":"assistant","content":None,
                "tool_calls":[{"id":"offline-1","type":"function","function":{"name":"send_message_to_agent",
                "arguments":json.dumps({"agent_name":case["owner"],"instructions":case["request"]})}}]}}],
                "usage":{"prompt_tokens":approx_input,"completion_tokens":20}}
        else:
            result = {"choices":[{"finish_reason":"stop","message":{"role":"assistant","content":"Done."}}],
                      "usage":{"prompt_tokens":approx_input,"completion_tokens":2}}
        usage = result.get("usage") or {}
        usages.append(usage)
        events.append({"event":"model", "call":calls, "usage":usage, "finish_reason":(result.get("choices") or [{}])[0].get("finish_reason")})
        return result
    ir.request_chat_completion = model_call

    class Batch:
        async def execute_agent(self, name, instructions):
            selected.append(name)
            events.append({"event":"dispatch", "name":name})
            return SimpleNamespace(success=True)
    it._EXECUTION_BATCH_MANAGER = Batch()

    # Baseline and treatment both use their own unmodified tool handler. Only execution is fake.
    runtime = ir.InteractionAgentRuntime()
    if case.get("context"):
        runtime.conversation_log.record_user_message(case["context"])
        runtime.conversation_log.record_reply("Understood.")
    result = await runtime.execute(case["request"])
    await asyncio.sleep(0)
    roster = get_agent_roster(); roster.load()
    names = roster.get_agents()
    actual = sum(reported_cost(u) for u in usages) if args.live else 0.0
    estimate = sum(estimated_cost(u) for u in usages)
    prompt_tokens = sum(u.get("prompt_tokens", 0) for u in usages)
    correct = bool(selected) and selected[0] == case["owner"]
    created = [n for n in names if n not in args.original_names]
    failure_type = None
    if result.error and "trial budget reservation" in result.error: failure_type = "evaluation_budget_cap"
    elif result.error and "OpenRouter call failed" in result.error: failure_type = "provider_infrastructure"
    elif result.error: failure_type = "interaction_error"
    elif not selected: failure_type = "no_dispatch"
    elif not correct: failure_type = "wrong_owner"
    elif created: failure_type = "unnecessary_creation"
    return {"condition":args.condition, "case":args.case, "size":args.size, "seed":args.seed,
            "expected_owner":case["owner"], "selected_agents":selected,
            "correct_owner":correct, "new_agents_created":len(created), "created_agent_names":created,
            "duplicate_or_new_agent":bool(created), "failure_type":failure_type,
            "interaction_success":result.success, "interaction_error":result.error,
            "model_calls":calls, "prompt_tokens":prompt_tokens,
            "completion_tokens":sum(u.get("completion_tokens",0) for u in usages),
            "first_request_context_bytes":request_bytes[0] if request_bytes else 0,
            "request_context_bytes":request_bytes,
            "reported_cost_usd":actual, "estimated_cost_usd":estimate, "reserved_cost_usd":estimated,
            "latency_seconds":round(time.monotonic()-origin,3), "events":events}

def prepare_server(condition, destination):
    commit = TREATMENT if condition == "treatment" else BASE
    archive = subprocess.check_output(["git","archive","--format=tar",commit,"server"], cwd=ROOT)
    tar_path = destination / "source.tar"; tar_path.write_bytes(archive)
    with tarfile.open(tar_path) as tar: tar.extractall(destination)
    tar_path.unlink()

def run_trial(args, condition, case, size, seed, remaining):
    entries = distractors(size, seed, case)
    with tempfile.TemporaryDirectory(prefix="openpoke-live-routing-") as tmp:
        tmp = Path(tmp); prepare_server(condition, tmp)
        data = tmp / "server/data"; (data/"execution_agents").mkdir(parents=True)
        (data/"conversation").mkdir(parents=True)
        (data/"execution_agents/roster.json").write_text(json.dumps([n for n,_ in entries]))
        for name, history in entries: write_history(data, name, history)
        result = tmp / "result.json"
        cmd = [sys.executable, str(Path(__file__).resolve()), "--worker", "--condition", condition,
               "--case", case["id"], "--size", str(size), "--seed", str(seed), "--output", str(result),
               "--max-calls", str(args.max_calls), "--max-tokens", str(args.max_tokens),
               "--trial-budget", str(min(remaining, args.per_trial_budget)), "--original-names", json.dumps([n for n,_ in entries])]
        if args.live: cmd.append("--live")
        env = dict(os.environ); env["PYTHONPATH"] = str(tmp)
        proc = subprocess.run(cmd, cwd=tmp, env=env, capture_output=True, text=True, timeout=180)
        if proc.returncode: raise RuntimeError(proc.stderr.replace(env.get("OPENROUTER_API_KEY", ""), "[REDACTED]")[:3000])
        return json.loads(result.read_text())

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--worker",action="store_true",help=argparse.SUPPRESS); p.add_argument("--condition")
    p.add_argument("--live", action="store_true", help="Make paid OpenRouter calls (default is offline validation)")
    p.add_argument("--resume", action="store_true", help="Resume incomplete pairs; preserve infrastructure attempts")
    p.add_argument("--case"); p.add_argument("--size",type=int); p.add_argument("--seed",type=int,default=917)
    p.add_argument("--output",type=Path,required=True); p.add_argument("--budget",type=float,default=.65)
    p.add_argument("--per-trial-budget",type=float,default=.16); p.add_argument("--trial-budget",type=float,default=.16)
    p.add_argument("--max-calls",type=int,default=3); p.add_argument("--max-tokens",type=int,default=256)
    p.add_argument("--sizes",default="10,100,500",help="Comma-separated roster sizes to run (subset of 10,100,500)")
    p.add_argument("--original-names",type=json.loads,default=[])
    args=p.parse_args()
    if args.worker:
        args.output.write_text(json.dumps(asyncio.run(worker(args)),indent=2)); return
    if args.output.exists() and not args.resume: p.error("output exists; use a fresh filename or --resume")
    key=os.environ.get("OPENROUTER_API_KEY") if args.live else "offline"
    if args.live and not key:
        for line in (ROOT/".env").read_text().splitlines():
            if line.strip().startswith("OPENROUTER_API_KEY="): key=line.split("=",1)[1].strip().strip("\"'")
    if not key: p.error("OPENROUTER_API_KEY missing")
    os.environ["OPENROUTER_API_KEY"]=key
    sizes=[int(s) for s in args.sizes.split(",") if s.strip()]
    invalid=[s for s in sizes if s not in (10,100,500)]
    if not sizes or invalid: p.error(f"--sizes must be a comma-separated subset of 10,100,500 (got {args.sizes!r})")
    order=[(c,s,z) for c in CASES for s in sizes for z in ("baseline","treatment")]
    random.Random(917).shuffle(order)
    if args.resume:
        report=json.loads(args.output.read_text())
        report.setdefault("infrastructure_attempts", [])
        kept=[]
        for run in report["runs"]:
            if run.get("failure_type") == "provider_infrastructure" or (
                run.get("prompt_tokens", 0) == 0 and "OpenRouter call failed" in str(run.get("interaction_error"))):
                report["infrastructure_attempts"].append(run)
            else: kept.append(run)
        report["runs"]=kept
        report.pop("stopped_reason", None)
    else:
        report={"kind":"live paired routing pilot" if args.live else "offline live-runner validation",
                "paid_calls":args.live, "baseline_commit":BASE, "treatment_commit":TREATMENT, "model":MODEL,
                "budget_usd":args.budget, "per_trial_budget_usd":args.per_trial_budget,
                "max_calls":args.max_calls,"max_tokens":args.max_tokens,"seed":917,"cases":CASES,"runs":[]}
    spent=sum(r.get("reported_cost_usd",0) for r in report["runs"])
    completed={(r["condition"],r["case"],r["size"],r["seed"]) for r in report["runs"]}
    for case,size,condition in order:
        if (condition,case["id"],size,917) in completed: continue
        remaining=args.budget-spent
        if remaining <= 0: break
        try:
            run=run_trial(args,condition,case,size,917,remaining)
        except Exception as exc:
            report["stopped_reason"]=str(exc).replace(key,"[REDACTED]"); break
        report["runs"].append(run); spent += run["reported_cost_usd"]
        report["reported_total_cost_usd"]=spent
        args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_text(json.dumps(report,indent=2)+"\n")
        print(condition,case["id"],size,"correct=",run["correct_owner"],"tokens=",run["prompt_tokens"],"cost=",round(run["reported_cost_usd"],5),flush=True)
        if args.live and run["interaction_error"] and "OpenRouter" in run["interaction_error"]:
            report["stopped_reason"]="provider error"; break
    args.output.write_text(json.dumps(report,indent=2)+"\n")

if __name__=="__main__": main()
