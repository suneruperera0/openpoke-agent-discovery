"""Paired development-only v1/v2 retrieval comparison; no model calls."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import subprocess
import tempfile
import time
from evals.retrieval_v2_fixtures import TASKS, fixture, transcript

ROOT = Path(__file__).resolve().parents[1]
V1_COMMIT = 'fd7b71d3713237a0f0f60ef5871c1589b9ce01e0'
SOURCE = 'server/services/execution/directory.py'


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def evaluate(split="dev"):
    if split == "heldout":
        from evals import retrieval_v2_holdout as fixtures
    else:
        from evals import retrieval_v2_fixtures as fixtures
    TASKS, fixture, transcript = fixtures.TASKS, fixtures.fixture, fixtures.transcript
    rows = []
    old = subprocess.check_output(['git','show',f'{V1_COMMIT}:{SOURCE}'],cwd=ROOT)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        old_path = tmp/'v1.py'; old_path.write_bytes(old)
        modules = {'v1':module(old_path,'v1'), 'v2':module(ROOT/SOURCE,'v2')}
        for task in TASKS:
            for seed in range(5):
                pool = fixture(task,seed)
                for size in (10,100,500):
                    entries = pool[:size].copy()
                    random.Random(seed + size).shuffle(entries)
                    histories = dict(entries)
                    identity = hashlib.sha256(json.dumps(entries).encode()).hexdigest()
                    for variant, mod in modules.items():
                        path = tmp/f'{task["id"]}-{seed}-{size}-{variant}'/'roster.json'
                        path.parent.mkdir(); path.write_text(json.dumps([n for n,_ in entries]))
                        d = mod.AgentDirectory(path, history_loader=lambda n: [histories[n]])
                        if task.get('recent'):
                            # Pin an unrelated existing agent identically without
                            # wall-clock-dependent metadata or adding label text.
                            unrelated = next(n for n,_ in entries if n != task['owner'])
                            d.recent_refs = [mod.reference(unrelated)]; d._write()
                        start = time.perf_counter()
                        block = d.shortlist(task['request'], transcript(task))
                        ms = (time.perf_counter()-start)*1000
                        candidates = json.loads(block.split('\n',1)[1].rsplit('\n',1)[0])['candidates']
                        query = mod.retrieval_query(task['request'],transcript(task))
                        search = d.search(query)['candidates']
                        ref = mod.reference(task['owner']) if task['owner'] else None
                        refs = [c['ref'] for c in candidates]
                        violation = len(refs) > 8 or len(block.encode()) > 4096
                        rows.append(dict(task=task['id'],seed=seed,size=size,variant=variant,
                            fixture_sha256=identity,expected_ref=ref,candidate_refs=refs,
                            shortlist_recall=ref in refs if ref else None,
                            first_search_recall=ref in [c['ref'] for c in search] if ref else None,
                            bound_violation=violation,roster_bytes=len(block.encode()),candidate_count=len(refs),latency_ms=round(ms,3)))
    summary=[]
    for size in (10,100,500):
        for variant in ('v1','v2'):
            group=[r for r in rows if r['size']==size and r['variant']==variant]
            eligible=[r for r in group if r['expected_ref']]
            summary.append(dict(size=size,variant=variant,eligible=len(eligible),
                shortlist_recall=sum(r['shortlist_recall'] for r in eligible)/len(eligible),
                first_search_recall=sum(r['first_search_recall'] for r in eligible)/len(eligible),
                bound_violations=sum(r["bound_violation"] for r in group),
                max_roster_bytes=max(r['roster_bytes'] for r in group),
                misses_by_task={t['id']:sum(r['shortlist_recall'] is False for r in eligible if r['task']==t['id']) for t in TASKS if t['owner']}))
    return dict(split=split,v1_commit=V1_COMMIT,
        v2_sha256=hashlib.sha256((ROOT/SOURCE).read_bytes()).hexdigest(),
        fixtures_sha256=hashlib.sha256(Path(fixtures.__file__).read_bytes()).hexdigest(),
        authored_tasks=len(TASKS),conditions=len(rows)//2,ranker_executions=len(rows),
        summary=summary,runs=rows)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--split',choices=['dev','heldout'],default='dev')
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.output.exists(): p.error('Evidence exists; choose a new filename')
    report=evaluate(args.split)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='runs'},indent=2))

if __name__=='__main__': main()
