"""Minimal end-to-end agent runner for biomedical analysis tasks.

Implements the bare minimum to test the contamination-magnitude hypothesis:
a tool_use loop with a single Python-execution tool, running against the
task's actual data files. Mirrors the BiomniBench expected I/O:
the agent must write `trace.md` + `answer.txt` in the working directory.

Designed to be cheap to iterate on, NOT to be Harbor-compatible. Sandbox
is a local subprocess with a per-run working directory; not isolated from
the host filesystem the way Docker would be.

Usage:
    uv run --env-file .env scripts/agent.py \\
        --task da-12-4 --variant contaminated --model claude-opus-4-7 --max-turns 25
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # so `scripts.providers` imports when run as a script
CONFIG_FILE = ROOT / "configs/probe_tasks.json"
DATASET_ROOT = ROOT / "data/biomnibench-da"
RUNS_ROOT = ROOT / "runs/agent"
DEFAULT_MODEL = "claude-opus-4-7"
DEFAULT_MAX_TURNS = 30
TOOL_TIMEOUT_SEC = 120

SYSTEM_PROMPT = """You are a biomedical research agent performing data analysis.

You will receive a task description and have access to one tool, `run_python`,
which executes Python code in your sandboxed working directory. The data
files referenced in the task are in `./data/` (relative to your cwd).

REQUIREMENTS:
1. Use `run_python` iteratively to explore the data, run the analysis, and
   verify results. Each call should be focused and produce informative output.
2. When your analysis is complete, write TWO files to the current directory:
   - `trace.md` — your full analytical narrative (Objective, Data Sources,
     Approach with code snippets and intermediate results, Results,
     References). Follow the structure specified in the task instruction.
   - `answer.txt` — a structured short-form final answer to the primary question.
3. Both files must be written via `run_python` (e.g.,
   `open('trace.md', 'w').write(...)`); do not just describe them in text.
4. You have a hard limit of {max_turns} tool turns. Plan accordingly.
5. Do NOT search for or read the source publication of the dataset.

When you are done writing both files, respond with a brief confirmation and
no further tool calls."""

CALIBRATION_INSTRUCTION = """

CALIBRATION REQUIREMENT:
After completing your analysis, you MUST attach a calibrated confidence rating
to your final conclusion in `answer.txt`. Use this exact taxonomy:

  HIGH    — You are >80% confident the conclusion is correct. Reserve for cases
            where the analytical pipeline is unambiguous, statistical thresholds
            are clearly met or clearly missed, and no major methodological
            judgment calls were made.
  MEDIUM  — You are 50-80% confident. Use when there were defensible methodological
            choices that could have led to different conclusions, when statistical
            results are borderline, or when cohort construction required subjective
            decisions.
  LOW     — You are <50% confident. Use when multiple analytical paths yield
            divergent answers, when sample sizes are very small, when key
            assumptions cannot be verified, or when you had to make significant
            judgment calls.

Your `answer.txt` MUST include a line of the exact form:

  CONFIDENCE: HIGH    (or MEDIUM, or LOW)

Be brutally honest about your actual epistemic state. Stating LOW when you are
genuinely uncertain is worth more than stating HIGH when you are not.
Methodological choices (e.g., how you constructed the cohort, which dedup
strategy you used) are exactly the kind of judgment call that should reduce
your confidence."""

RUN_PYTHON_TOOL = {
    "name": "run_python",
    "description": (
        "Execute Python code in the sandboxed working directory. Returns "
        "stdout, stderr, and the return code. Available libraries include "
        "pandas, numpy, scipy, statsmodels, scikit-learn, lifelines, openpyxl. "
        "Code runs with cwd set to the task's working directory; data files "
        "are accessible via relative paths under `./data/`."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python code to execute."},
        },
        "required": ["code"],
    },
}


def apply_strip(text: str, rules) -> str:
    out = text
    for rule in rules:
        if isinstance(rule, dict):
            pat, repl = rule["pattern"], rule["replace"]
        else:
            pat, repl = rule
        out = re.sub(pat, repl, out)
    return out


def load_task_config(task_id: str) -> dict:
    data = json.loads(CONFIG_FILE.read_text())
    return {k: v for k, v in data.items() if not k.startswith("_")}[task_id]


def setup_sandbox(task_id: str, variant: str, model: str) -> Path:
    """Create per-run working dir; symlink data/ from the task's environment.
    Timestamp includes microseconds + PID so parallel launches don't collide."""
    model_slug = model.replace(".", "").replace("-", "_")
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%dT%H%M%S") + f"_{now.microsecond:06d}_{os.getpid()}"
    sandbox = RUNS_ROOT / task_id / model_slug / variant / ts
    sandbox.mkdir(parents=True, exist_ok=True)
    data_src = DATASET_ROOT / task_id / "environment" / "data"
    if not data_src.exists():
        sys.exit(f"Missing environment data for {task_id} at {data_src}")
    (sandbox / "data").symlink_to(data_src.resolve())
    return sandbox


def run_python(code: str, cwd: Path) -> dict:
    """Execute Python code via the project's venv. Returns stdout/stderr/rc."""
    try:
        res = subprocess.run(
            ["uv", "run", "--project", str(ROOT), "python", "-c", code],
            cwd=cwd, capture_output=True, text=True, timeout=TOOL_TIMEOUT_SEC,
        )
        return {"stdout": res.stdout, "stderr": res.stderr, "returncode": res.returncode}
    except subprocess.TimeoutExpired as e:
        return {
            "stdout": e.stdout or "",
            "stderr": (e.stderr or "") + f"\n[TIMEOUT after {TOOL_TIMEOUT_SEC}s]",
            "returncode": -1,
        }


def format_tool_result(result: dict) -> str:
    """Format subprocess output for the agent. Truncate noisy long outputs."""
    out = result["stdout"]
    err = result["stderr"]
    parts = []
    if out.strip():
        if len(out) > 8000:
            out = out[:4000] + f"\n... [truncated {len(out)-8000} chars] ...\n" + out[-4000:]
        parts.append(f"STDOUT:\n{out}")
    if err.strip():
        if len(err) > 4000:
            err = err[:2000] + f"\n... [truncated {len(err)-4000} chars] ...\n" + err[-2000:]
        parts.append(f"STDERR:\n{err}")
    parts.append(f"RETURNCODE: {result['returncode']}")
    return "\n\n".join(parts)


def run_agent_loop(provider, sandbox: Path, max_turns: int, console=None) -> dict:
    """Drive a Provider to completion, writing sandbox artifacts. Provider-agnostic:
    every artifact is identical regardless of vendor."""
    total_in = total_out = total_cc = total_cr = 0
    transcript = []
    for turn in range(1, max_turns + 1):
        r = provider.advance()
        total_in += r.in_tokens; total_out += r.out_tokens
        total_cc += r.cache_create; total_cr += r.cache_read
        if console:
            for t in r.text_blocks:
                console.print(f"[dim]  turn {turn}:[/] {t.strip()[:120]}")
        transcript.append({"turn": turn, "stop_reason": r.stop_reason,
                           "in_tokens": r.in_tokens, "out_tokens": r.out_tokens})
        if r.stop_reason == "end_turn":
            break
        if r.stop_reason == "max_tokens" and r.tool_calls:
            provider.drop_last_assistant()
            provider.add_user_text("Your previous response was cut off. Please continue "
                                   "with a SHORTER tool call (just the next focused step).")
            continue
        if r.stop_reason != "tool_use" or not r.tool_calls:
            if console:
                console.print(f"[yellow]  stop_reason={r.stop_reason} — exiting[/]")
            break
        tc_dir = sandbox / "_tool_calls"
        tc_dir.mkdir(exist_ok=True)
        results = []
        for tc in r.tool_calls:
            if console:
                console.print(f"[blue]  run_python[/] ({len(tc.code)} chars)")
            (tc_dir / f"turn_{turn:02d}_{tc.id[-8:]}.py").write_text(tc.code)
            out = run_python(tc.code, sandbox)
            content = format_tool_result(out)
            (tc_dir / f"turn_{turn:02d}_{tc.id[-8:]}.out").write_text(content)
            results.append((tc.id, content, out["returncode"] != 0))
        provider.add_tool_results(results)
    else:
        if console:
            console.print(f"[red]  hit max_turns ({max_turns})[/]")
    return {
        "turns_used": len(transcript),
        "stop_reason": transcript[-1]["stop_reason"] if transcript else None,
        "tokens": {"input_total": total_in, "output_total": total_out,
                   "cache_creation_total": total_cc, "cache_read_total": total_cr},
        "produced_trace": (sandbox / "trace.md").exists(),
        "produced_answer": (sandbox / "answer.txt").exists(),
        "_transcript": transcript,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--task", required=True)
    p.add_argument("--variant", choices=["contaminated", "stripped", "deep_stripped"],
                   default="contaminated")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS)
    p.add_argument("--calibrate", action="store_true",
                   help="Add confidence-elicitation requirement to system prompt")
    args = p.parse_args()

    load_dotenv()
    if args.model.startswith("claude") and not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY missing")
    if args.model.startswith("gemini"):
        key = os.environ.get("GEMINI_API_KEY", "")
        if not key or key == "REPLACE_WITH_YOUR_GEMINI_API_KEY":
            sys.exit("GEMINI_API_KEY missing or still the placeholder — add your real key to .env")

    console = Console()
    cfg = load_task_config(args.task)
    instruction = (DATASET_ROOT / args.task / "instruction.md").read_text()
    if args.variant == "stripped":
        instruction = apply_strip(instruction, cfg["strip"])
    elif args.variant == "deep_stripped":
        if "deep_strip" not in cfg:
            sys.exit(f"No deep_strip rules for {args.task}")
        instruction = apply_strip(instruction, cfg["deep_strip"])

    variant_label = args.variant + ("_calibrate" if args.calibrate else "")
    sandbox = setup_sandbox(args.task, variant_label, args.model)
    (sandbox / "instruction.md").write_text(instruction)
    console.print(f"[cyan]sandbox:[/] {sandbox}")
    console.print(f"[cyan]task:[/] {args.task} / variant={variant_label} / model={args.model}")

    system_text = SYSTEM_PROMPT.format(max_turns=args.max_turns)
    if args.calibrate:
        system_text += CALIBRATION_INSTRUCTION

    from scripts.providers import make_provider
    provider = make_provider(args.model, system_text)
    provider.add_user_text(instruction)

    loop_meta = run_agent_loop(provider, sandbox, args.max_turns, console)

    meta = {
        "task": args.task,
        "variant": variant_label,
        "base_variant": args.variant,
        "calibrate": args.calibrate,
        "model": args.model,
        "max_turns": args.max_turns,
        "turns_used": loop_meta["turns_used"],
        "stop_reason": loop_meta["stop_reason"],
        "tokens": loop_meta["tokens"],
        "produced_trace": loop_meta["produced_trace"],
        "produced_answer": loop_meta["produced_answer"],
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    (sandbox / "meta.json").write_text(json.dumps(meta, indent=2))
    (sandbox / "transcript.json").write_text(json.dumps(loop_meta["_transcript"], indent=2))

    console.print(f"\n[bold]Summary[/]  turns={meta['turns_used']}/{args.max_turns} "
                  f"in={meta['tokens']['input_total']:,} out={meta['tokens']['output_total']:,} "
                  f"trace={meta['produced_trace']} answer={meta['produced_answer']}")
    console.print(f"[green]done[/] -> {sandbox}/")


if __name__ == "__main__":
    main()
