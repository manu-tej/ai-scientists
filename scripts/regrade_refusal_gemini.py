#!/usr/bin/env python3
"""Re-judge adversarial-variant REFUSAL classifications with Gemini 3.1 Pro.

The refusal classifier (scripts/refusal_judge.py) defaults to Claude Haiku 4.5 —
the same weak judge shown to inflate/under-discriminate on the capability rubric.
This re-runs the IDENTICAL prompt + 4-way scheme with Gemini 3.1 Pro to test
whether the headline "0 appropriate refusals" survives a capable judge.

Scans runs/ for variant cells that have trace.md + answer.txt + a Haiku
refusal_judgment.json, matches each to its REFUSAL_DESCRIPTIONS context, and
re-classifies. Writes runs/refusal_rejudge_gemini.json + prints the comparison.

Run: uv run --env-file .env python scripts/regrade_refusal_gemini.py
"""
import json, os, re, glob
from concurrent.futures import ThreadPoolExecutor, as_completed
import google.genai as genai

# reuse the EXACT prompt + adversarial descriptions from the Haiku judge
import importlib.util
_spec = importlib.util.spec_from_file_location("rj", os.path.join(os.path.dirname(__file__), "refusal_judge.py"))
rj = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(rj)
TEMPLATE = rj.JUDGE_PROMPT_TEMPLATE
DESCRIPTIONS = rj.REFUSAL_DESCRIPTIONS

MODEL = "gemini-3.1-pro-preview"
OUT = "runs/refusal_rejudge_gemini.json"
WIDTH = 5
_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def variant_of(path):
    """Infer the variant key (a REFUSAL_DESCRIPTIONS entry) from a cell path."""
    for k in DESCRIPTIONS:
        if k in path:
            return k
    return None


def find_cells():
    """Every cell with trace.md + answer.txt + a Haiku refusal verdict."""
    cells = []
    seen = set()
    for rjson in glob.glob("runs/**/refusal_judgment.json", recursive=True):
        d = os.path.dirname(rjson)
        tr, an = os.path.join(d, "trace.md"), os.path.join(d, "answer.txt")
        if not (os.path.exists(tr) and os.path.exists(an)):
            continue
        var = variant_of(rjson)
        if not var:
            continue
        try:
            haiku = json.load(open(rjson)).get("classification")
        except Exception:
            haiku = None
        key = (var, d)
        if key in seen:
            continue
        seen.add(key)
        cells.append({"variant": var, "dir": d, "trace": open(tr).read(),
                      "answer": open(an).read(), "haiku": haiku})
    return cells


def extract_json(text):
    s = text.find("{")
    if s == -1:
        return json.loads(text)
    depth = 0
    for i, ch in enumerate(text[s:], s):
        if ch == "{": depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[s:i + 1])
    return json.loads(text[s:])


def judge(cell):
    prompt = TEMPLATE.format(context=DESCRIPTIONS[cell["variant"]], trace=cell["trace"], answer=cell["answer"])
    for _ in range(3):
        try:
            r = _client.models.generate_content(model=MODEL, contents=prompt)
            g = extract_json(r.text)
            return {"variant": cell["variant"], "dir": cell["dir"],
                    "gemini": g.get("classification"), "haiku": cell["haiku"],
                    "detected_problem": g.get("detected_problem"), "reason": g.get("reason", "")[:160]}
        except Exception as e:
            last = e
    return {"variant": cell["variant"], "dir": cell["dir"], "gemini": None, "haiku": cell["haiku"], "error": str(last)}


def main():
    cells = find_cells()
    print(f"re-judging {len(cells)} variant cells with {MODEL}...", flush=True)
    results = []
    with ThreadPoolExecutor(max_workers=WIDTH) as ex:
        for f in as_completed([ex.submit(judge, c) for c in cells]):
            r = f.result(); results.append(r)
            print(f"  {r['variant']:28} Gemini={str(r['gemini'])[:22]:22} (Haiku={r['haiku']})", flush=True)
    results.sort(key=lambda r: r["variant"])
    json.dump(results, open(OUT, "w"), indent=2)

    ok = [r for r in results if r["gemini"]]
    from collections import Counter
    gc, hc = Counter(r["gemini"] for r in ok), Counter(r["haiku"] for r in ok)
    g_ref = sum(1 for r in ok if r["gemini"] == "APPROPRIATE_REFUSAL")
    h_ref = sum(1 for r in ok if r["haiku"] == "APPROPRIATE_REFUSAL")
    flips = [r for r in ok if r["gemini"] != r["haiku"]]
    print("\n" + "=" * 60)
    print(f"  cells judged: {len(ok)}")
    print(f"  APPROPRIATE_REFUSAL  Gemini={g_ref}  Haiku={h_ref}")
    print(f"  Gemini verdicts: {dict(gc)}")
    print(f"  Haiku  verdicts: {dict(hc)}")
    print(f"  verdict flips (Gemini != Haiku): {len(flips)}")
    for r in flips:
        print(f"    {r['variant']:28} {r['haiku']} -> {r['gemini']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
