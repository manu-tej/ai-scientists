"""Contamination probe for da-12-4.

Tests whether Claude can recall the BiomniBench reference answer
(Kocuria significant, HR ~1.0124, p ~0.0234) from the task text alone,
without running any analysis. Compares the original prompt (with explicit
TCGA / lung-cancer markers) against a stripped variant.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv
from rich.console import Console

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / "data/biomnibench-da/da-12-4"
RUN_DIR = ROOT / "runs/contamination/da-12-4"
MODEL = "claude-opus-4-7"

PREDICT_PROMPT = """You are an expert biomedical researcher. Below is a research task description.

WITHOUT running any code, downloading any data, or performing any actual analysis,
predict what the answer would be based on your existing knowledge of published research.

If this looks like a study or analysis you can recall, state your best prediction with
specific numerical values (e.g., HR, p-value) if you remember them.
If you cannot predict the answer with any confidence, state that explicitly.

Output your prediction in the format the task requests.

TASK:
{task}
"""


def strip_contamination(text: str) -> str:
    out = text
    out = out.replace("Noncoding RNAs in Lung Adenocarcinoma", "Survival Analysis")
    out = re.sub(r"lung cancer patients", "cancer cohort patients", out, flags=re.IGNORECASE)
    out = re.sub(r"lung adenocarcinoma", "cancer cohort", out, flags=re.IGNORECASE)
    out = out.replace("TCGA_RNA-01A.csv", "cohort_rna.csv")
    out = out.replace("TCGA_microbiota-01A.csv", "cohort_microbiome.csv")
    out = re.sub(r"\bTCGA[_\-]?\w*", "cohort", out)
    out = out.replace("NAR_Q3 folder", "data folder")
    out = out.replace("NAR_Q3", "uploaded")
    return out


def call_claude(client: Anthropic, prompt: str) -> tuple[str, int, int]:
    msg = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in msg.content if hasattr(b, "text"))
    return text, msg.usage.input_tokens, msg.usage.output_tokens


def extract_signals(response: str) -> dict:
    text = response.lower()
    hrs = [float(v) for v in re.findall(r"hr[^\d\n]{0,8}(\d+\.\d+)", text)]
    pvals = [float(v) for v in re.findall(r"p[ -]?(?:value)?[^\d\n]{0,8}(\d+\.\d+)", text)]
    ref_hr, ref_p = 1.0124, 0.0234
    return {
        "mentions_kocuria": "kocuria" in text,
        "says_significant": any(s in text for s in ["yes", "significantly associated"]),
        "says_not_significant": any(
            s in text for s in ["not significant", "not associated", "no significant"]
        ),
        "hr_values": hrs,
        "p_values": pvals,
        "hr_match_loose": any(abs(v - ref_hr) < 0.1 for v in hrs),
        "hr_match_tight": any(abs(v - ref_hr) < 0.005 for v in hrs),
        "p_match_loose": any(abs(v - ref_p) < 0.02 for v in pvals),
        "p_match_tight": any(abs(v - ref_p) < 0.005 for v in pvals),
    }


def main() -> None:
    load_dotenv()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY missing — check .env")

    console = Console()
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    client = Anthropic()

    original = (TASK / "instruction.md").read_text()
    stripped = strip_contamination(original)

    results: dict = {
        "model": MODEL,
        "task": "da-12-4",
        "ts": datetime.now(timezone.utc).isoformat(),
        "reference": {"kocuria_significant": True, "HR": 1.0124, "p": 0.0234},
        "variants": {},
    }

    for label, task_text in [("contaminated", original), ("stripped", stripped)]:
        console.print(f"\n[cyan]==> {label}[/]")
        prompt = PREDICT_PROMPT.format(task=task_text)
        (RUN_DIR / f"{label}_prompt.txt").write_text(prompt)
        response, in_tok, out_tok = call_claude(client, prompt)
        (RUN_DIR / f"{label}_response.txt").write_text(response)
        signals = extract_signals(response)
        results["variants"][label] = {
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "signals": signals,
        }
        console.print(
            f"  kocuria_named={signals['mentions_kocuria']}  "
            f"hr_loose={signals['hr_match_loose']}  hr_tight={signals['hr_match_tight']}  "
            f"p_loose={signals['p_match_loose']}  p_tight={signals['p_match_tight']}"
        )
        console.print(f"  HR_values={signals['hr_values']}  p_values={signals['p_values']}")

    (RUN_DIR / "results.json").write_text(json.dumps(results, indent=2))
    console.print(f"\n[green]done[/] -> {RUN_DIR}/")


if __name__ == "__main__":
    main()
