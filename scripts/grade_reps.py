#!/usr/bin/env python3
"""Grade the REMAINING replicate traces per task (the ones bench/grade.py's
resolve_cell did NOT pick), reuse the prior single-rep scores, and aggregate
per task:
  - median  normalized -> robust capability
  - pop. SD normalized -> run-to-run consistency (0 = identical, higher = flakier)

Cost-saving: skips the one rep already judged in --prev (identified by replicating
resolve_cell's exact pick on the unchanged tree), so only ~2 reps/task are judged.

Reuses bench/grade.py's EXACT judging primitives so scores match the single-rep path.

Run from repo root:
  uv run --env-file .env python scripts/grade_reps.py \
      --root runs/cap3/antigravity-cli \
      --prev runs/cap3_antigravity-cli.json \
      --out  runs/cap3_antigravity-cli_reps.json
"""
import argparse, json, os, statistics, sys, time, urllib.error, urllib.request
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, "bench")
import grade as G  # bench/grade.py — import side-effect-free (main is __main__-guarded)

ap = argparse.ArgumentParser()
ap.add_argument("--root", type=Path, required=True)
ap.add_argument("--prev", type=Path, default=None, help="prior single-rep grade JSON to reuse")
ap.add_argument("--out", type=Path, required=True)
ap.add_argument("--data-root", type=Path, default=Path("data/biomnibench-da"))
ap.add_argument("--model", default=G.DEFAULT_MODEL,
                help="judge model; 'openrouter:<slug>' uses OpenRouter (e.g. openrouter:minimax/minimax-m3)")
ap.add_argument("--width", type=int, default=8)
ap.add_argument("--votes", type=int, default=1,
                help="judge each rep N times and average the normalized score (de-noises the "
                     "~+/-0.07 MiniMax judge variance). Default 1 (single draw). Use 5 for a "
                     "stable score of record.")
ap.add_argument("--limit", type=int, default=0, help="grade only first N tasks (0=all; for testing)")
args = ap.parse_args()


def _openrouter_backend(slug):
    """OpenRouter judge backend (OpenAI-compatible). Neutral third-party judge,
    no Gemini daily cap. Returns the model's raw text for a rubric prompt."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        sys.exit("OPENROUTER_API_KEY not set (needed for an openrouter: judge)")
    url = "https://openrouter.ai/api/v1/chat/completions"

    def call(prompt):
        body = json.dumps({"model": slug, "messages": [{"role": "user", "content": prompt}],
                           "temperature": 0, "max_tokens": 8000,
                           "response_format": {"type": "json_object"}}).encode()
        last = ""
        for attempt in range(5):
            req = urllib.request.Request(url, data=body, headers={
                "Authorization": f"Bearer {key}", "Content-Type": "application/json",
                "HTTP-Referer": "https://benchbench.local", "X-Title": "benchbench-judge"})
            try:
                with urllib.request.urlopen(req, timeout=180) as r:
                    return json.load(r)["choices"][0]["message"]["content"]
            except urllib.error.HTTPError as e:
                last = f"HTTP {e.code}"
                if e.code in (429, 500, 502, 503, 408):
                    time.sleep(2 ** attempt); continue
                raise
            except Exception as e:  # noqa: BLE001
                last = str(e); time.sleep(2 ** attempt)
        raise RuntimeError(f"openrouter retries exhausted: {last}")
    return call


backend = (_openrouter_backend(args.model.split(":", 1)[1])
           if args.model.startswith("openrouter:") else G.make_backend(args.model))

# prior per-task score (the rep resolve_cell picked) -> reuse, don't re-grade
prev = {}
if args.prev and args.prev.exists():
    for e in json.load(open(args.prev)):
        if e.get("normalized") is not None:
            prev[e["task"]] = e["normalized"]
print(f"reusing {len(prev)} prior single-rep scores from {args.prev}")


def picked_rep_dir(cell):
    """Reproduce resolve_cell's choice: sorted run dirs, reversed, first with a
    usable surface; the trace's rep dir is what grade.py already judged."""
    runs = sorted([d for d in cell.iterdir() if d.is_dir()])
    for run in reversed(runs):
        tf = next((p for p in run.rglob("artifacts/trace.md")), None)
        af = next((p for p in run.rglob("artifacts/answer.txt")), None)
        if tf or af:
            return (tf or af).parent.parent
    return None


def rep_surfaces(rep_dir):
    """(trace, answer) for one rep dir, with the same agent-log fallback grade.py's
    resolve_cell uses: if artifacts/trace.md (or answer.txt) is missing, extract it
    from agent/<harness>.txt. Lets a rep that wrote an answer but no trace still be
    graded (e.g. codex/da-24-3)."""
    art = rep_dir / "artifacts"
    af, tf = art / "answer.txt", art / "trace.md"
    answer = af.read_text(errors="replace") if af.exists() else ""
    trace = tf.read_text(errors="replace") if tf.exists() else ""
    if not trace or not answer:
        agent_dir = rep_dir / "agent"
        if agent_dir.is_dir():
            for lf in sorted(agent_dir.glob("*.txt")):
                fn = G._EXTRACTORS.get(lf.stem)
                if fn:
                    ext_trace, ext_answer = fn(lf.read_text(errors="replace"))
                    trace = trace or ext_trace
                    answer = answer or ext_answer
                    break
    return trace, answer


def judge(rubric, trace, answer):
    """Normalized score for one rep. With --votes N, judge N times and return the MEAN to
    average out MiniMax-3's ~+/-0.07 run-to-run noise (default N=1 = single draw, prior behavior)."""
    prompt = G.build_prompt(rubric, trace, answer)
    mx = G.rubric_max(rubric)
    if not mx:
        return None
    votes = []
    for v in range(max(1, args.votes)):
        last = None
        for _ in range(3):                      # retry transient API/parse errors within a vote
            try:
                criteria = G.extract_json(backend(prompt)).get("criteria", {})
                votes.append(round(G.score_from_levels(rubric, criteria) / mx, 4))
                break
            except Exception as e:  # noqa: BLE001
                last = e
        else:
            print(f"    judge error (vote {v + 1}/{args.votes}): {last}", file=sys.stderr)
    if not votes:
        return None
    return round(sum(votes) / len(votes), 4)    # mean over the successful votes


# --- build work list: every rep EXCEPT the one already in prev --------------
tasks = sorted([d for d in args.root.iterdir() if d.is_dir()])
if args.limit:
    tasks = tasks[:args.limit]
work = []                       # (task, rep_id, rubric, trace, answer)
reused = {}                     # task -> normalized (the skipped/prior rep)
for cell in tasks:
    task = cell.name
    rf = G.rubric_of(task, args.data_root)
    if not rf.exists():
        print(f"{task}: no rubric -> skip")
        continue
    rubric = rf.read_text()
    skip = picked_rep_dir(cell) if task in prev else None
    if skip is not None:
        reused[task] = prev[task]
    # every rep dir (has artifacts/ and/or agent/), so reps missing trace.md but
    # carrying an agent log are recovered via rep_surfaces' fallback.
    rep_dirs = sorted({p.parent for p in cell.rglob("artifacts") if p.is_dir()} |
                      {p.parent for p in cell.rglob("agent") if p.is_dir()})
    for rep_dir in rep_dirs:
        if skip is not None and rep_dir == skip:
            continue            # already judged by grade.py -> reuse prev
        trace, answer = rep_surfaces(rep_dir)
        if not trace.strip():
            continue            # nothing to rubric-grade
        work.append((task, rep_dir.name, rubric, trace, answer))

print(f"grading {len(work)} remaining reps across {len(tasks)} tasks "
      f"(reusing {len(reused)} prior) | model={args.model} width={args.width}", flush=True)


def run_item(it):
    task, rep_id, rubric, trace, answer = it
    return task, rep_id, judge(rubric, trace, answer)


per_rep = {t: [{"rep": "prev(grade.py)", "norm": n}] for t, n in reused.items()}
with ThreadPoolExecutor(max_workers=args.width) as ex:
    futs = [ex.submit(run_item, it) for it in work]
    done = 0
    for fu in as_completed(futs):
        task, rep_id, norm = fu.result()
        per_rep.setdefault(task, []).append({"rep": rep_id, "norm": norm})
        done += 1
        if done % 10 == 0:
            print(f"  {done}/{len(work)}", flush=True)

# --- aggregate per task ----------------------------------------------------
results = []
for task in sorted(per_rep):
    reps = per_rep[task]
    norms = [r["norm"] for r in reps if r["norm"] is not None]
    results.append({
        "task": task, "n_reps": len(norms), "norms": sorted(norms),
        "median": round(statistics.median(norms), 4) if norms else None,
        "mean": round(statistics.mean(norms), 4) if norms else None,
        "sd": round(statistics.pstdev(norms), 4) if len(norms) > 1 else 0.0,
        "min": min(norms) if norms else None, "max": max(norms) if norms else None,
        "reps": reps,
    })

args.out.parent.mkdir(parents=True, exist_ok=True)
json.dump(results, open(args.out, "w"), indent=1)

med = [r["median"] for r in results if r["median"] is not None]
sd = [r["sd"] for r in results if r["n_reps"] > 1]
print("\n=== PER-TASK: norms -> median, sd ===")
for r in results:
    flag = "" if r["n_reps"] == 3 else f"   <-- n_reps={r['n_reps']}"
    print(f"  {r['task']:12s} {r['norms']}  median={r['median']}  sd={r['sd']}{flag}")
print(f"\nTASKS={len(results)}  reps_total={sum(r['n_reps'] for r in results)}  newly_graded={len(work)}")
print(f"CAPABILITY  (mean of per-task medians) = {sum(med)/len(med):.4f}")
print(f"CONSISTENCY (mean per-task SD)         = {sum(sd)/len(sd):.4f}   [0=identical reps, higher=flakier]")
print(f"wrote {args.out}")
