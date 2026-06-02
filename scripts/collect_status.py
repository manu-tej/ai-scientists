#!/usr/bin/env python3
"""Host-local status collector for the benchbench base-matrix runs.

Emits a JSON blob describing this host's progress: scored tasks per agent,
live harbor cells (with agent-log size as a liveness proxy), recent scores,
a billing scan (apiKeySource=ANTHROPIC_API_KEY => a cell that BILLED), and
whether the run arms are alive. Designed to run identically on the Mac and on
serene; the web server merges the two.

Usage: collect_status.py --root <runs/harbor_base_matrix> --host <label>
"""
import argparse, glob, json, os, re, subprocess, time

AGENTS = ("codex", "claude-code")
TOTAL = 50  # benchmark target denominator


def _run(cmd):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15).stdout
    except Exception:
        return ""


def scored_tasks(root, agent):
    """Map task -> {score, mtime} for every task with a verifier reward.json."""
    out = {}
    base = os.path.join(root, agent)
    if not os.path.isdir(base):
        return out
    for task in sorted(os.listdir(base)):
        hits = glob.glob(os.path.join(base, task, "*", "*", "verifier", "reward.json"))
        if not hits:
            continue
        newest = max(hits, key=lambda p: os.path.getmtime(p))
        # Honest count: a cell is only "scored" if the agent produced a real
        # answer. A reward.json with no/empty answer.txt is POISON (agent hit a
        # usage/session limit or crashed; verifier scored the empty attempt 0).
        ans = os.path.join(os.path.dirname(newest), "answer.txt")
        if not (os.path.exists(ans) and os.path.getsize(ans) > 1):
            continue
        score = None
        try:
            with open(newest) as fh:
                score = json.load(fh).get("score")
        except Exception:
            m = re.search(r"\d+", open(newest).read() or "")
            score = int(m.group()) if m else None
        out[task] = {"score": score, "mtime": os.path.getmtime(newest)}
    return out


def live_cells(root):
    """Parse running harbor procs into {agent, task, log_bytes, log_age_s}."""
    cells = []
    ps = _run("pgrep -af 'bin/harbor run' 2>/dev/null || pgrep -lf 'harbor run' 2>/dev/null")
    for line in ps.splitlines():
        if "grep" in line:
            continue
        mt = re.search(r"harbor_base_tasks/(\S+)", line)
        ma = re.search(r"--agent\s+(\S+)", line)
        if not (mt and ma):
            continue
        task, agent = mt.group(1).rstrip("/"), ma.group(1)
        logs = glob.glob(os.path.join(root, agent, task, "*", "*", "agent", "*.txt"))
        log_bytes, log_age = 0, None
        if logs:
            newest = max(logs, key=lambda p: os.path.getmtime(p))
            log_bytes = os.path.getsize(newest)
            log_age = round(time.time() - os.path.getmtime(newest), 1)
        cells.append({"agent": agent, "task": task, "log_bytes": log_bytes, "log_age_s": log_age})
    return cells


def recent_scores(root, limit=12):
    rows = []
    for agent in AGENTS:
        for task, info in scored_tasks(root, agent).items():
            rows.append({"agent": agent, "task": task, "score": info["score"], "mtime": info["mtime"]})
    rows.sort(key=lambda r: r["mtime"], reverse=True)
    return rows[:limit]


def billing_scan(root):
    """Count agent logs that authenticated via the API key (i.e. BILLED)."""
    n, examples = 0, []
    for f in glob.glob(os.path.join(root, "**", "agent", "*.txt"), recursive=True):
        try:
            with open(f, "r", errors="ignore") as fh:
                if '"apiKeySource":"ANTHROPIC' in fh.read():
                    n += 1
                    if len(examples) < 3:
                        examples.append(os.path.relpath(f, root))
        except Exception:
            pass
    return {"billed_cells": n, "examples": examples, "status": "clean" if n == 0 else "BILLING"}


VARIANTS = [
    "da-12-4_drop_survival", "da-12-4_tiny_n", "da-5-1_drop_pdac", "da-5-1_drop_tier",
    "da-13-3_drop_pvalues", "da-13-3_drop_pct_fat", "da-17-1_drop_disease",
    "da-20-1_drop_cell_line", "da-20-1_single_cell_type",
]
VARIANT_K = 3
VARIANT_ROOT = "runs/harbor_matrix_serene"   # <agent>/<variant>/rep<N>/<ts>/<cell>/agent/*.txt


def variant_progress():
    """Per-agent completed reps across the 9 adversarial variants.

    A rep counts as DONE when its cell has a non-empty answer.txt artifact
    (verification is disabled for variants — refusal is judged offline). Also
    reports total target (9 variants x K) and any live variant cell.
    """
    out = {}
    if not os.path.isdir(VARIANT_ROOT):
        return {"present": False}
    for ag in AGENTS:
        done = 0
        per = {}
        for v in VARIANTS:
            reps = 0
            for rep in range(1, VARIANT_K + 1):
                # variants run with --disable-verification, so NO answer.txt is
                # copied out — the only deliverable is the agent trace
                # (agent/<harness>.txt). "done" = trace produced AND the harbor
                # run finalized (result.json written, so it's not mid-flight).
                rep_dir = os.path.join(VARIANT_ROOT, ag, v, f"rep{rep}")
                trace = glob.glob(os.path.join(rep_dir, "*", "*", "agent", "*.txt"))
                final = glob.glob(os.path.join(rep_dir, "*", "result.json"))
                if trace and final and any(os.path.getsize(t) > 200 for t in trace):
                    reps += 1
            per[v] = reps
            done += reps
        out[ag] = {"done": done, "total": len(VARIANTS) * VARIANT_K, "per_variant": per}
    out["present"] = True
    return out


def variant_live():
    """Live variant harbor cells (path under harbor_tasks = the adversarial set)."""
    cells = []
    ps = _run("pgrep -af 'bin/harbor run' 2>/dev/null")
    for line in ps.splitlines():
        if "grep" in line or "harbor_base_tasks" in line:
            continue
        mt = re.search(r"harbor_tasks/(\S+)", line)
        ma = re.search(r"--agent\s+(\S+)", line)
        if mt and ma and any(v in mt.group(1) for v in VARIANTS):
            cells.append({"agent": ma.group(1), "variant": mt.group(1).rstrip("/")})
    return cells


def arms_alive():
    return {
        "until_complete": bool(_run("pgrep -f run_until_complete.sh").strip()),
        "mac_cc": bool(_run("pgrep -f run_mac_cc.sh").strip()),
        "variant_paired": bool(_run("pgrep -f run_variant_paired.sh").strip()),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--host", default="local")
    a = ap.parse_args()
    root = os.path.expanduser(a.root)
    agents = {}
    for ag in AGENTS:
        st = scored_tasks(root, ag)
        agents[ag] = {"scored": len(st), "total": TOTAL, "tasks": sorted(st.keys())}
    print(json.dumps({
        "host": a.host,
        "updated": time.time(),
        "agents": agents,
        "live": live_cells(root),
        "recent_scores": recent_scores(root),
        "billing": billing_scan(root),
        "arms": arms_alive(),
        "variants": variant_progress(),
        "variant_live": variant_live(),
    }))


if __name__ == "__main__":
    main()
