"""Within-variant consistency probe for da-12-4.

Sends the same contaminated prompt K=5 times, captures predictions, and
measures spread in HR / p-value / Yes-No call. Maps to Rabanser et al.'s
outcome-consistency dimension.
"""
from __future__ import annotations

import json
import os
import re
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv
from rich.console import Console

ROOT = Path(__file__).resolve().parents[1]
PROMPT_FILE = ROOT / "runs/contamination/da-12-4/contaminated_prompt.txt"
RUN_DIR = ROOT / "runs/consistency/da-12-4"
MODEL = "claude-opus-4-7"
K = 5


def parse_prediction(response: str) -> dict:
    """Pull the agent's *predicted* HR / p / Yes-No for Kocuria."""
    text = response.lower()
    # Kocuria-line: prefer the explicit "Kocuria: HR ... p ..." pattern,
    # which is how Claude formats its prediction in the trace's Results section.
    m = re.search(r"kocuria[^\n]*?hr[^\d]{0,8}(\d+\.\d+)[^\n]*?p[^\d]{0,8}(\d+\.\d+)", text)
    hr_predicted, p_predicted = (float(m.group(1)), float(m.group(2))) if m else (None, None)
    # Yes/No call on significance
    if re.search(r"\byes\b[^\n]{0,200}(significant|associated|poor prognosis)", text):
        call = "yes"
    elif re.search(r"\bno\b[^\n]{0,200}(not significant|not associated)", text) or "not significantly" in text:
        call = "no"
    else:
        call = "ambiguous"
    return {"hr_predicted": hr_predicted, "p_predicted": p_predicted, "call": call}


def main() -> None:
    load_dotenv()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY missing")
    console = Console()
    if not PROMPT_FILE.exists():
        sys.exit(f"Run contamination_probe.py first; expected {PROMPT_FILE}")
    prompt = PROMPT_FILE.read_text()
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    client = Anthropic()

    REF_HR, REF_P = 1.0124, 0.0234
    runs = []
    for i in range(1, K + 1):
        console.print(f"\n[cyan]==> run {i}/{K}[/]")
        msg = client.messages.create(
            model=MODEL, max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        response = "".join(b.text for b in msg.content if hasattr(b, "text"))
        (RUN_DIR / f"run_{i:02d}.txt").write_text(response)
        pred = parse_prediction(response)
        runs.append(pred | {"in": msg.usage.input_tokens, "out": msg.usage.output_tokens})
        console.print(f"  call={pred['call']}  HR={pred['hr_predicted']}  p={pred['p_predicted']}")

    # Aggregate stats
    hrs = [r["hr_predicted"] for r in runs if r["hr_predicted"] is not None]
    ps = [r["p_predicted"] for r in runs if r["p_predicted"] is not None]
    calls = [r["call"] for r in runs]
    yes_rate = calls.count("yes") / K

    stats = {
        "K": K,
        "model": MODEL,
        "reference": {"HR": REF_HR, "p": REF_P, "expected_call": "yes"},
        "calls": calls,
        "yes_rate": yes_rate,
        "hr_predicted_values": hrs,
        "p_predicted_values": ps,
        "hr_mean": statistics.mean(hrs) if hrs else None,
        "hr_stdev": statistics.stdev(hrs) if len(hrs) > 1 else None,
        "hr_range": (min(hrs), max(hrs)) if hrs else None,
        "p_mean": statistics.mean(ps) if ps else None,
        "p_stdev": statistics.stdev(ps) if len(ps) > 1 else None,
        "p_range": (min(ps), max(ps)) if ps else None,
        # Outcome consistency a la Rabanser: 1 - sigma^2 / (p(1-p) + eps).
        # Here p = success rate, success = call==yes (since ref==yes).
        "outcome_consistency": (
            1 - (statistics.variance([1 if c == "yes" else 0 for c in calls])
                 / (yes_rate * (1 - yes_rate) + 1e-8))
            if len(set(calls)) > 1 else 1.0
        ),
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    (RUN_DIR / "stats.json").write_text(json.dumps(stats, indent=2))

    console.print("\n[bold]Summary[/]")
    console.print(f"  Calls: {calls}  (yes_rate={yes_rate:.2f})")
    console.print(f"  HR: mean={stats['hr_mean']}, stdev={stats['hr_stdev']}, range={stats['hr_range']}")
    console.print(f"  p:  mean={stats['p_mean']}, stdev={stats['p_stdev']}, range={stats['p_range']}")
    console.print(f"  Reference: HR={REF_HR}, p={REF_P}")
    console.print(f"  Rabanser outcome_consistency = {stats['outcome_consistency']:.3f}")
    console.print(f"\n[green]done[/] -> {RUN_DIR}/")


if __name__ == "__main__":
    main()
