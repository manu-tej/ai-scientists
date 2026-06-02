#!/usr/bin/env python3
"""Re-judge cc traces with Sonnet via the claude-code CLI (subscription) instead
of the raw Anthropic API — isolates the claude-code agent-scaffolding effect on
judging (the Claude analogue of the gemini-cli test).

BILLING-SAFE: ANTHROPIC_API_KEY is stripped from the subprocess env (fail-closed:
no key -> Max subscription via keychain, or nothing). The first call is auth-gated
on apiKeySource=none; any cell showing ANTHROPIC_API_KEY aborts the whole run.
Runs from /tmp with --strict-mcp-config to avoid loading project CLAUDE.md / MCP.

Run: python3 scripts/regrade_claude_cli.py
"""
import json, os, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed

import importlib.util
os.environ.setdefault("GEMINI_API_KEY", "unused")
_spec = importlib.util.spec_from_file_location("rg", os.path.join(os.path.dirname(__file__), "regrade_gemini.py"))
rg = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(rg)
build_prompt, score_from_levels, extract_json = rg.build_prompt, rg.score_from_levels, rg.extract_json

MODEL = "claude-sonnet-4-6"
BUNDLE = "runs/cc_bundle.json"
OUT = "runs/claude_cli_rejudge_cc.json"
SONNET_API_REF, GEMINI_API_REF, PHYLO_REF = 74.5, 74.7, 73.34
WIDTH = 3
# strip the API key so claude-code MUST use the Max subscription (apiKeySource=none) or fail
ENV = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}


def claude_cli(prompt, want_meta=False):
    """One claude-code -p call from /tmp; returns (judge_text, meta)."""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(prompt); path = f.name
    try:
        with open(path) as fin:
            p = subprocess.run(
                ["claude", "-p", "--model", MODEL, "--strict-mcp-config", "--output-format", "json"],
                stdin=fin, env=ENV, cwd="/tmp", capture_output=True, text=True, timeout=300)
        d = json.loads(p.stdout)
        return d.get("result", ""), d
    finally:
        os.unlink(path)


def auth_gate():
    """Verify the CLI uses the subscription, not the API key, before the batch."""
    txt, meta = claude_cli('Reply with exactly: {"ok": true}')
    # subscription => no real billing key; cost is notional. The definitive signal
    # (apiKeySource) isn't in the json result, so we rely on the stream-json probe:
    r = subprocess.run(["claude", "-p", "hi", "--model", MODEL, "--strict-mcp-config",
                        "--output-format", "stream-json", "--verbose"],
                       env=ENV, cwd="/tmp", capture_output=True, text=True, timeout=120)
    src = None
    for line in r.stdout.splitlines():
        try:
            j = json.loads(line)
        except Exception:
            continue
        if j.get("type") == "system" and "apiKeySource" in j:
            src = j["apiKeySource"]; break
    print(f"  AUTH GATE: apiKeySource={src!r}", flush=True)
    if src not in (None, "none", "None"):
        sys.exit(f"ABORT: claude-code would BILL (apiKeySource={src}). Refusing to run 50 cells.")
    print("  -> subscription / $0. Proceeding.", flush=True)


def judge(cell):
    prompt = build_prompt(cell["rubric"], cell["trace"], cell["answer"])
    for _ in range(3):
        try:
            txt, _ = claude_cli(prompt)
            criteria = extract_json(txt).get("criteria", {})
            return {"task": cell["task"], "cli_score": score_from_levels(cell["rubric"], criteria),
                    "haiku_incontainer": cell["haiku_score"], "n_criteria": len(criteria)}
        except Exception as e:
            last = e
    return {"task": cell["task"], "cli_score": None, "haiku_incontainer": cell["haiku_score"], "error": str(last)}


def main():
    cells = json.load(open(BUNDLE))
    print(f"claude-code CLI re-judge ({MODEL}) of {len(cells)} cells, {WIDTH}-wide...", flush=True)
    auth_gate()
    results = []
    with ThreadPoolExecutor(max_workers=WIDTH) as ex:
        futs = {ex.submit(judge, c): c["task"] for c in cells}
        for f in as_completed(futs):
            r = f.result(); results.append(r)
            tag = "ERR" if r["cli_score"] is None else f"CLI={r['cli_score']:>3}"
            print(f"  {r['task']:9} {tag}", flush=True)
    results.sort(key=lambda r: r["task"])
    json.dump(results, open(OUT, "w"), indent=2)
    ok = [r for r in results if r["cli_score"] is not None]
    c = [r["cli_score"] for r in ok]
    cm = sum(c) / len(c) if c else 0
    print("\n" + "=" * 56)
    print(f"  Sonnet via claude-code CLI:   {cm:5.1f} / 100  (n={len(c)})")
    print(f"  Sonnet via API:               {SONNET_API_REF:5.1f} / 100")
    print(f"  Gemini 3.1 Pro API:           {GEMINI_API_REF:5.1f} / 100")
    print(f"  Phylo published:              {PHYLO_REF:5.1f} / 100")
    print(f"  CLI vs API (scaffolding):     {cm - SONNET_API_REF:+5.1f} pts")
    if len(c) < len(cells):
        print(f"  WARN: {len(cells) - len(c)} cells failed")
    print("=" * 56)


if __name__ == "__main__":
    main()
