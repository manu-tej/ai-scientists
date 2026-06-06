#!/usr/bin/env python3
"""Grade a BixBench-Verified-50 run two ways and aggregate over replicates.

For each task we score every replicate's answer.txt two ways, then aggregate per task:
  - open_acc    : mean OPEN-ANSWER correctness across reps
  - mcq_acc     : mean MCQ correctness across reps
  - open_agree  : run-to-run CONSISTENCY = fraction of reps that agree on the open
                  verdict (1.0 = all reps same; the trust signal accuracy alone hides)

OPEN-ANSWER score per eval_mode:
  str_verifier   -> code: normalized exact match (or ideal contained in answer)
  range_verifier -> code: parse ideal "(lo,hi)"; correct iff ANY number in the answer
                    falls in [lo,hi]
  llm_verifier   -> OpenRouter minimax/minimax-m3 judge: CORRECT / INCORRECT
MCQ score (all tasks): present ideal + 3 distractors (shuffled); MiniMax-M3 picks the option
  best matching the agent's answer; correct iff it picks the ideal.

Numeric-verifier robustness (these brittleness bugs each scored CORRECT answers as 0):
  - thousands separators: "19,159" == "19159"            (str + range)
  - scientific notation : "1.03E-07" parsed as a float   (range bounds + answers)
  - fraction-plus-decimal: "30/41 (0.732)" -> 0.732 is checked, not the numerator 30
    (range scans ALL numbers in the answer, not just the first)

Judge = OpenRouter (OPENROUTER_API_KEY), model BB_JUDGE_MODEL (default minimax/minimax-m3) —
a neutral third party to all three agents, with no daily cap (the BiomniBench baseline
keeps its Gemini judge; this grader is BixBench-only).

Usage:
  uv run --env-file .env python scripts/grade_bixbench.py \
      --tasks runs/bixbench_full \
      --root  runs/bixbench_full_out/claude-code \
      --out   runs/bixbench_full_claude-code_grade.json
"""
from __future__ import annotations
import argparse, json, os, random, re, sys, time, urllib.request, urllib.error
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

KEY = os.environ.get("OPENROUTER_API_KEY")
MODEL = os.environ.get("BB_JUDGE_MODEL", "minimax/minimax-m3")
URL = "https://openrouter.ai/api/v1/chat/completions"


def _or_call(prompt: str, max_tokens: int = 120, json_mode: bool = False) -> str:
    """One OpenRouter chat call with retries/backoff. Returns text or '__ERR__ ...'."""
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    body = json.dumps(payload).encode()
    last = ""
    for attempt in range(5):
        req = urllib.request.Request(URL, data=body, headers={
            "Authorization": f"Bearer {KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://benchbench.local",
            "X-Title": "benchbench-bixbench-grader",
        })
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code in (429, 500, 502, 503, 408):
                time.sleep(2 ** attempt)
                continue
            return f"__ERR__ {e.code}: {e.read().decode()[:160]}"
        except Exception as e:  # noqa: BLE001
            last = str(e)
            time.sleep(2 ** attempt)
    return f"__ERR__ {last}"


def _norm(s: str) -> str:
    # drop thousands-separator commas (e.g. "19,159" == "19159") so str_verifier
    # scores numeric correctness, not formatting — mirrors range_verifier's
    # .replace(",", "") and avoids penalizing an agent for omitting a comma.
    s = re.sub(r"(?<=\d),(?=\d)", "", s)
    return re.sub(r"\s+", " ", s.strip().lower()).rstrip(".")


# number incl. scientific notation (e.g. 1.03E-07); thousands-comma stripped first
_NUM = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def _denorm(s: str) -> str:
    return re.sub(r"(?<=\d),(?=\d)", "", s)  # 19,159 -> 19159, leave "0.7, 0.8" alone


def _all_nums(s: str) -> list[float]:
    return [float(m) for m in _NUM.findall(_denorm(s))]


def open_score(answer: str, ideal: str, mode: str) -> bool | None:
    a = answer.strip()
    if not a:
        return None
    if mode == "str_verifier":
        na, ni = _norm(a), _norm(ideal)
        return na == ni or ni in na
    if mode == "range_verifier":
        # parse "(lo,hi)" per-bound so scientific notation survives (splitting on the
        # comma first, NOT a global number-scan that mis-reads "1.03E-07,1.23E-07").
        bounds = [ns[0] for p in ideal.strip("() ").split(",")
                  if (ns := _all_nums(p))]
        if len(bounds) >= 2:
            lo, hi = sorted(bounds[:2])
            # accept if ANY number in the answer falls in range — the agent often
            # reports the value alongside intermediates (e.g. "30/41 (0.732)").
            vals = _all_nums(a)
            return any(lo <= v <= hi for v in vals) if vals else None
        return None
    # llm_verifier -> MiniMax judge
    out = _or_call(
        "You are grading a computational-biology question.\n"
        f"Reference (ideal) answer: {ideal}\n"
        f"Agent's answer: {a}\n\n"
        "Is the agent's answer equivalent to / consistent with the ideal answer? "
        "Reply on the first line with exactly CORRECT or INCORRECT.")
    if out.startswith("__ERR__"):
        return None
    head = out.splitlines()[0].upper()
    return ("CORRECT" in head) and ("INCORRECT" not in head)


def mcq_score(answer: str, ideal: str, distractors: list, seed: int) -> bool | None:
    a = answer.strip()
    if not a:
        return None
    rng = random.Random(seed)
    opts = [ideal] + list(distractors)
    rng.shuffle(opts)
    correct = opts.index(ideal) + 1
    lines = "\n".join(f"{i + 1}. {o}" for i, o in enumerate(opts))
    out = _or_call(
        "An agent answered a question. Pick which numbered option below best matches the agent's "
        "answer (by meaning/value, not exact wording).\n"
        f"Agent's answer: {a}\n\nOptions:\n{lines}\n\n"
        f'Reply with JSON only: {{"option": <the integer 1-{len(opts)} that best matches>}}.',
        max_tokens=400, json_mode=True)
    if out.startswith("__ERR__"):
        return None
    pick = None
    try:
        pick = int(json.loads(out).get("option"))
    except Exception:  # noqa: BLE001
        m = re.findall(r"\d+", out)
        pick = int(m[-1]) if m else None
    return (pick == correct) if pick is not None else None


def resolve_reps(task_dir: Path) -> list[tuple[str, str]]:
    """Return (rep_id, answer_text) for every answer.txt under the task's run dir."""
    out = []
    for af in sorted(task_dir.rglob("artifacts/answer.txt")):
        try:
            out.append((af.parent.parent.name, af.read_text(errors="replace")))
        except Exception:
            pass
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", required=True, type=Path, help="task tree (has <id>/tests/grading.json)")
    ap.add_argument("--root", required=True, type=Path, help="run output dir, e.g. runs/<x>/antigravity-cli")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--width", type=int, default=6, help="judge concurrency")
    args = ap.parse_args()
    if not KEY:
        sys.exit("OPENROUTER_API_KEY not set (uv run --env-file .env ...)")

    # build (task, rep, grading) work items
    work = []
    for cell in sorted(args.root.iterdir()):
        if not cell.is_dir():
            continue
        tid = cell.name
        gj = args.tasks / tid / "tests" / "grading.json"
        if not gj.exists():
            print(f"  SKIP {tid}: no grading.json")
            continue
        g = json.loads(gj.read_text())
        for i, (rep_id, ans) in enumerate(resolve_reps(cell)):
            work.append((tid, rep_id, i, ans, g))
    print(f"grading {len(work)} reps across "
          f"{len({w[0] for w in work})} tasks | judge={MODEL} width={args.width}", flush=True)

    def run_one(item):
        tid, rep_id, i, ans, g = item
        op = open_score(ans, g["ideal"], g.get("eval_mode"))
        mc = mcq_score(ans, g["ideal"], g.get("distractors", []), seed=hash((tid, i)) & 0xFFFF)
        return tid, {"rep": rep_id, "eval_mode": g.get("eval_mode"),
                     "answer": ans.strip()[:120], "open_correct": op, "mcq_correct": mc}

    per_task: dict[str, list] = {}
    with ThreadPoolExecutor(max_workers=args.width) as ex:
        futs = [ex.submit(run_one, w) for w in work]
        done = 0
        for fu in as_completed(futs):
            tid, rec = fu.result()
            per_task.setdefault(tid, []).append(rec)
            done += 1
            if done % 5 == 0:
                print(f"  {done}/{len(work)}", flush=True)

    results = []
    for tid in sorted(per_task):
        reps = per_task[tid]
        opens = [r["open_correct"] for r in reps if r["open_correct"] is not None]
        mcqs = [r["mcq_correct"] for r in reps if r["mcq_correct"] is not None]
        results.append({
            "task": tid,
            "eval_mode": reps[0]["eval_mode"],
            "n_reps": len(reps),
            "open_acc": round(sum(opens) / len(opens), 3) if opens else None,
            "mcq_acc": round(sum(mcqs) / len(mcqs), 3) if mcqs else None,
            # consistency: do reps agree on the open verdict? (1.0 = all same)
            "open_agree": round(max(opens.count(True), opens.count(False)) / len(opens), 3) if len(opens) > 1 else None,
            "reps": reps,
        })

    args.out.parent.mkdir(parents=True, exist_ok=True)
    json.dump(results, open(args.out, "w"), indent=1)

    oa = [r["open_acc"] for r in results if r["open_acc"] is not None]
    ma = [r["mcq_acc"] for r in results if r["mcq_acc"] is not None]
    ag = [r["open_agree"] for r in results if r["open_agree"] is not None]
    print("\n=== PER-TASK ===")
    for r in results:
        print(f"  {r['task']:12} {r['eval_mode']:14} open={r['open_acc']} mcq={r['mcq_acc']} "
              f"agree={r['open_agree']}  ans={r['reps'][0]['answer'][:40]!r}")
    print(f"\nTASKS={len(results)} reps={sum(r['n_reps'] for r in results)}")
    print(f"OPEN-ANSWER accuracy (mean over tasks) = {sum(oa)/len(oa):.4f}" if oa else "OPEN: n/a")
    print(f"MCQ accuracy         (mean over tasks) = {sum(ma)/len(ma):.4f}" if ma else "MCQ: n/a")
    if ag:
        print(f"CONSISTENCY (mean per-task open-agreement) = {sum(ag)/len(ag):.4f}  [1.0=reps always agree]")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
