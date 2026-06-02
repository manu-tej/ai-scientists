#!/usr/bin/env python3
"""Re-judge the cc traces with a Claude model (Sonnet/Haiku) — Phylo's judge,
faithful. Phylo's tests/llm_judge.py IS the Anthropic client, so this is the
most faithful Claude comparison: same prompt + scoring, only --model changes.

Run: uv run --env-file .env python scripts/regrade_anthropic.py --model claude-sonnet-4-6
"""
import argparse, json, os, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
import anthropic

# reuse the verbatim Phylo prompt + scoring from the API re-judge
import importlib.util
os.environ.setdefault("GEMINI_API_KEY", "unused")
_spec = importlib.util.spec_from_file_location("rg", os.path.join(os.path.dirname(__file__), "regrade_gemini.py"))
rg = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(rg)
build_prompt, score_from_levels, extract_json = rg.build_prompt, rg.score_from_levels, rg.extract_json

BUNDLE = "runs/cc_bundle.json"
GEMINI_API_REF, GEMINI_CLI_REF, PHYLO_REF = 74.7, 72.4, 73.34
_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def judge(cell, model):
    prompt = build_prompt(cell["rubric"], cell["trace"], cell["answer"])
    last = None
    for _ in range(3):
        try:
            r = _client.messages.create(model=model, max_tokens=8192,
                                        messages=[{"role": "user", "content": prompt}])
            criteria = extract_json(r.content[0].text).get("criteria", {})
            return {"task": cell["task"], "score": score_from_levels(cell["rubric"], criteria),
                    "haiku_incontainer": cell["haiku_score"], "n_criteria": len(criteria)}
        except Exception as e:
            last = e
    return {"task": cell["task"], "score": None, "haiku_incontainer": cell["haiku_score"], "error": str(last)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="claude-sonnet-4-6")
    ap.add_argument("--width", type=int, default=6)
    a = ap.parse_args()
    cells = json.load(open(BUNDLE))
    out = f"runs/anthropic_rejudge_{a.model.replace('.', '_')}.json"
    print(f"re-judging {len(cells)} cc cells with {a.model} ({a.width}-wide)...", flush=True)
    results = []
    with ThreadPoolExecutor(max_workers=a.width) as ex:
        futs = {ex.submit(judge, c, a.model): c["task"] for c in cells}
        for f in as_completed(futs):
            r = f.result(); results.append(r)
            tag = "ERR" if r["score"] is None else f"{a.model.split('-')[1][:3]}={r['score']:>3} Hic={r['haiku_incontainer']:>3}"
            print(f"  {r['task']:9} {tag}", flush=True)
    results.sort(key=lambda r: r["task"])
    json.dump(results, open(out, "w"), indent=2)

    ok = [r for r in results if r["score"] is not None]
    s = [r["score"] for r in ok]
    sm = sum(s) / len(s) if s else 0
    print("\n" + "=" * 56)
    print(f"  {a.model} (this run):        {sm:5.1f} / 100  (n={len(s)})")
    print(f"  Gemini API (3.1-pro):          {GEMINI_API_REF:5.1f} / 100")
    print(f"  Gemini CLI (3.1-pro):          {GEMINI_CLI_REF:5.1f} / 100")
    print(f"  Phylo published:               {PHYLO_REF:5.1f} / 100")
    print(f"  {a.model} vs Gemini API:  {sm - GEMINI_API_REF:+5.1f} pts")
    if len(s) < len(cells):
        print(f"  WARN: {len(cells) - len(s)} cells failed")
    print("=" * 56)


if __name__ == "__main__":
    main()
