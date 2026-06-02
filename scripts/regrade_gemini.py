#!/usr/bin/env python3
"""Re-judge saved agent traces with Gemini 3.1 Pro — Phylo's judge, faithful.

Replicates BiomniBench's tests/llm_judge.py EXACTLY (prompt + parse_rubric_levels
+ level->points->sum scoring); the ONLY change is the client (Anthropic -> Gemini
3.1 Pro), so the score difference isolates the judge-model effect. This is the
apples-to-apples comparison against Phylo's published numbers (their default
verifier is Gemini 3.1 Pro).

Reads runs/cc_bundle.json [{task, rubric, trace, answer, haiku_score}], writes
runs/gemini_rejudge_cc.json and prints the Gemini-vs-Haiku-vs-Phylo comparison.

Run: uv run --env-file .env python scripts/regrade_gemini.py
"""
import json, os, re, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
import google.genai as genai

import argparse
_ap = argparse.ArgumentParser()
_ap.add_argument("--bundle", default="runs/cc_bundle.json")
_ap.add_argument("--out", default="runs/gemini_rejudge_cc.json")
_args, _ = _ap.parse_known_args()
MODEL = "gemini-3.1-pro-preview"           # Phylo's default verifier
BUNDLE = _args.bundle
OUT = _args.out
WIDTH = 5
PHYLO_REF = 73.34                          # Phylo claude-code+Opus-4.7 (published)

_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])


# --- VERBATIM from Phylo's llm_judge.py ---------------------------------------
def parse_rubric_levels(rubric_text):
    out = {}
    parts = re.split(r"^Criterion\s+(\d+)\s*:", rubric_text, flags=re.MULTILINE)
    for i in range(1, len(parts), 2):
        n = parts[i].strip()
        body = parts[i + 1] if i + 1 < len(parts) else ""
        levels = {}
        m = re.search(r"Levels:\s*((?:[A-Z]=\d+\s*)+)", body)
        if m:
            for lm in re.finditer(r"([A-Z])=(\d+)", m.group(1)):
                levels[lm.group(1).upper()] = int(lm.group(2))
        if not levels:
            for lm in re.finditer(r"\[([A-Z])\]\s*\(\s*(\d+)\s*points?\s*\)", body):
                levels[lm.group(1).upper()] = int(lm.group(2))
        if levels:
            out[f"criterion_{n}"] = levels
    return out


def build_prompt(rubric, trace_content, answer_content):
    return f"""You are an expert evaluator for a data analysis task.

Evaluate the agent's work using the following rubric:

{rubric}

Here is the agent's analysis trace:

<trace>
{trace_content if trace_content else "[No trace file provided]"}
</trace>

Here is the agent's final answer:

<answer>
{answer_content if answer_content else "[No answer file provided]"}
</answer>

For each criterion in the rubric, choose ONE level: A, B, or C — based purely on which level description best describes the agent's work. Do not output numerical points; the score for each level is computed automatically from the rubric.

You MUST respond with a JSON object in exactly this format:
{{
  "criteria": {{
    "criterion_1": {{"level": "A", "reason": "<one-sentence explanation>"}},
    "criterion_2": {{"level": "B", "reason": "<one-sentence explanation>"}},
    ...
  }},
  "overall_reasoning": "<short summary>"
}}

Each "level" value must be exactly the single character "A", "B", or "C". Only output the JSON object, nothing else."""


def extract_json(text):
    s = text.find("{")
    if s == -1:
        return json.loads(text)
    depth = 0
    for i, ch in enumerate(text[s:], s):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[s:i + 1])
    return json.loads(text[s:])


def score_from_levels(rubric, criteria):
    """Phylo's exact mapping: chosen level -> rubric points -> sum."""
    levels = parse_rubric_levels(rubric)
    total = 0
    for k, c in criteria.items():
        if not isinstance(c, dict):
            continue
        allowed = levels.get(k) or {}
        lv = (c.get("level") or "").strip().upper()
        total += allowed.get(lv, 0)
    return total
# -----------------------------------------------------------------------------


def judge(cell):
    prompt = build_prompt(cell["rubric"], cell["trace"], cell["answer"])
    last = None
    for attempt in range(3):
        try:
            r = _client.models.generate_content(model=MODEL, contents=prompt)
            result = extract_json(r.text)
            criteria = result.get("criteria", {})
            return {"task": cell["task"], "gemini_score": score_from_levels(cell["rubric"], criteria),
                    "haiku_score": cell["haiku_score"], "n_criteria": len(criteria)}
        except Exception as e:
            last = e
    return {"task": cell["task"], "gemini_score": None, "haiku_score": cell["haiku_score"],
            "n_criteria": 0, "error": str(last)}


def main():
    cells = json.load(open(BUNDLE))
    print(f"re-judging {len(cells)} cc cells with {MODEL} ({WIDTH}-wide)...", flush=True)
    results = []
    with ThreadPoolExecutor(max_workers=WIDTH) as ex:
        futs = {ex.submit(judge, c): c["task"] for c in cells}
        for f in as_completed(futs):
            r = f.result()
            results.append(r)
            tag = "ERR" if r["gemini_score"] is None else f"G={r['gemini_score']:>3} H={r['haiku_score']:>3}"
            print(f"  {r['task']:9} {tag}", flush=True)
    results.sort(key=lambda r: r["task"])
    json.dump(results, open(OUT, "w"), indent=2)

    ok = [r for r in results if r["gemini_score"] is not None]
    g = [r["gemini_score"] for r in ok]
    h = [r["haiku_score"] for r in ok if r["haiku_score"] is not None]
    gm, hm = sum(g) / len(g), sum(h) / len(h)
    print("\n" + "=" * 52)
    print(f"  Gemini 3.1 Pro (Phylo's judge):  {gm:5.1f} / 100   (n={len(g)})")
    print(f"  Claude Haiku 4.5 (our judge):    {hm:5.1f} / 100")
    print(f"  Phylo published (cc+Opus-4.7):   {PHYLO_REF:5.1f} / 100")
    print(f"  judge inflation (Haiku - Gemini): {hm - gm:+5.1f} pts")
    print(f"  vs Phylo (Gemini - 73.34):        {gm - PHYLO_REF:+5.1f} pts")
    if len(g) < len(cells):
        print(f"  WARN: {len(cells) - len(g)} cells failed to judge")
    print("=" * 52)


if __name__ == "__main__":
    main()
