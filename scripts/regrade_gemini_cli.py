#!/usr/bin/env python3
"""Re-judge the cc traces with gemini-cli (subscription OAuth) instead of the
google-genai API — to test whether the judge score depends on the access path.

Same Phylo prompt + scoring as scripts/regrade_gemini.py; only the call changes
(google-genai client -> `gemini` CLI). Waits out the subscription quota: probes
with a trivial call and only starts the batch once the quota has reset.

Run: GEMINI_FORCE_OAUTH=1 GEMINI_CLI_TRUST_WORKSPACE=true \
     python3 scripts/regrade_gemini_cli.py
"""
import json, os, re, subprocess, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor, as_completed

# reuse the verbatim Phylo prompt + scoring from the API re-judge
import importlib.util
_spec = importlib.util.spec_from_file_location("rg", os.path.join(os.path.dirname(__file__), "regrade_gemini.py"))
# regrade_gemini constructs a genai.Client at import (needs GEMINI_API_KEY); guard it
os.environ.setdefault("GEMINI_API_KEY", "unused-for-cli")
try:
    rg = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(rg)
    build_prompt, score_from_levels, extract_json = rg.build_prompt, rg.score_from_levels, rg.extract_json
except Exception:
    # fallback: inline copies if import side-effects fail
    raise

MODEL = "gemini-3.1-pro-preview"
BUNDLE = "runs/cc_bundle.json"
OUT = "runs/gemini_cli_rejudge_cc.json"
API_REF = 74.7      # google-genai API judge (this run's comparison target)
HAIKU_REF = 91.7
PHYLO_REF = 73.34
WIDTH = 3           # CLI is heavy; keep concurrency modest
# Use the API key (Ultra-funded quota) via gemini-cli, NOT the throttled Code
# Assist OAuth. settings.json selectedType must be "gemini-api-key".
ENV = {**os.environ, "GEMINI_CLI_TRUST_WORKSPACE": "true"}


def gemini_cli(prompt):
    """One gemini-cli call; returns (text, quota_exhausted_bool)."""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(prompt); path = f.name
    try:
        with open(path) as fin:
            p = subprocess.run(["gemini", "-m", MODEL], stdin=fin, env=ENV,
                               capture_output=True, text=True, timeout=240)
        out, err = p.stdout, p.stderr
        if "QUOTA_EXHAUSTED" in err or "QUOTA_EXHAUSTED" in out:
            return None, True
        return out, False
    finally:
        os.unlink(path)


def wait_for_quota(max_hours=4):
    """Probe until the subscription quota is available."""
    deadline = None
    probes = 0
    while True:
        txt, exhausted = gemini_cli('Reply with exactly: {"ok": true}')
        probes += 1
        if not exhausted and txt and "ok" in txt:
            print(f"quota available (after {probes} probe(s)).", flush=True)
            return True
        print(f"  quota still exhausted (probe {probes}); sleeping 900s...", flush=True)
        time.sleep(900)
        if probes > max_hours * 4:
            print("gave up waiting for quota.", flush=True)
            return False


def judge(cell):
    prompt = build_prompt(cell["rubric"], cell["trace"], cell["answer"])
    for _ in range(3):
        txt, exhausted = gemini_cli(prompt)
        if exhausted:
            time.sleep(300); continue
        try:
            criteria = extract_json(txt).get("criteria", {})
            return {"task": cell["task"], "cli_score": score_from_levels(cell["rubric"], criteria),
                    "haiku_score": cell["haiku_score"], "n_criteria": len(criteria)}
        except Exception as e:
            last = e
    return {"task": cell["task"], "cli_score": None, "haiku_score": cell["haiku_score"], "n_criteria": 0}


def main():
    cells = json.load(open(BUNDLE))
    print(f"gemini-cli re-judge of {len(cells)} cc cells (waiting on subscription quota)...", flush=True)
    if not wait_for_quota():
        sys.exit("quota never cleared")
    results = []
    with ThreadPoolExecutor(max_workers=WIDTH) as ex:
        futs = {ex.submit(judge, c): c["task"] for c in cells}
        for f in as_completed(futs):
            r = f.result(); results.append(r)
            tag = "ERR" if r["cli_score"] is None else f"CLI={r['cli_score']:>3} H={r['haiku_score']:>3}"
            print(f"  {r['task']:9} {tag}", flush=True)
    results.sort(key=lambda r: r["task"])
    json.dump(results, open(OUT, "w"), indent=2)

    ok = [r for r in results if r["cli_score"] is not None]
    c = [r["cli_score"] for r in ok]
    cm = sum(c) / len(c) if c else 0
    print("\n" + "=" * 54)
    print(f"  gemini-cli (subscription OAuth):  {cm:5.1f} / 100   (n={len(c)})")
    print(f"  google-genai API (gemini-3.1-pro):{API_REF:5.1f} / 100")
    print(f"  Claude Haiku 4.5:                 {HAIKU_REF:5.1f} / 100")
    print(f"  Phylo published:                  {PHYLO_REF:5.1f} / 100")
    print(f"  CLI vs API (access-path effect):  {cm - API_REF:+5.1f} pts")
    if len(c) < len(cells):
        print(f"  WARN: {len(cells) - len(c)} cells failed")
    print("=" * 54)


if __name__ == "__main__":
    main()
