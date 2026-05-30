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

from anthropic import Anthropic
from dotenv import load_dotenv
from rich.console import Console

ROOT = Path(__file__).resolve().parents[1]
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
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY missing")

    console = Console()
    client = Anthropic()
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
    # Use blocks form so we can attach cache_control to the system prompt.
    # The system prompt + tool definitions + first user instruction are
    # identical across every turn within a run, so caching them turns those
    # ~5-6K tokens of fixed prefix into 10%-billed cache reads after turn 1.
    system = [{"type": "text", "text": system_text,
               "cache_control": {"type": "ephemeral"}}]
    tools = [{**RUN_PYTHON_TOOL, "cache_control": {"type": "ephemeral"}}]
    messages = [{"role": "user", "content": [
        {"type": "text", "text": instruction,
         "cache_control": {"type": "ephemeral"}}
    ]}]
    total_in_tok = 0
    total_cache_create_tok = 0
    total_cache_read_tok = 0
    total_out_tok = 0
    transcript = []

    for turn in range(1, args.max_turns + 1):
        # Retry-with-backoff on 429s; the org-wide TPM cap is shared across
        # concurrent agent runs and the bucket refills in seconds.
        import time as _time
        from anthropic import RateLimitError as _RateLimitError, APIStatusError as _APIStatusError
        backoff_s = 8.0
        attempts = 0
        while True:
            try:
                resp = client.messages.create(
                    model=args.model,
                    max_tokens=8192,
                    system=system,
                    tools=tools,
                    messages=messages,
                )
                break
            except (_RateLimitError, _APIStatusError) as e:
                attempts += 1
                code = getattr(e, "status_code", None)
                if code is not None and code not in (429, 503, 529) and not isinstance(e, _RateLimitError):
                    raise
                if attempts > 6:
                    raise
                wait = backoff_s
                console.print(f"[yellow]  turn {turn}: rate-limited ({code}); sleeping {wait:.0f}s (attempt {attempts}/6)[/]")
                _time.sleep(wait)
                backoff_s = min(backoff_s * 1.8, 60.0)
        total_in_tok += resp.usage.input_tokens
        total_out_tok += resp.usage.output_tokens
        # Cache stats (Anthropic returns these on every response when caching is in use)
        total_cache_create_tok += getattr(resp.usage, "cache_creation_input_tokens", 0) or 0
        total_cache_read_tok += getattr(resp.usage, "cache_read_input_tokens", 0) or 0

        assistant_blocks = []
        tool_calls_this_turn = []
        for block in resp.content:
            assistant_blocks.append(block.to_dict() if hasattr(block, "to_dict") else block.model_dump())
            if block.type == "text":
                snippet = block.text.strip().replace("\n", " ")[:120]
                console.print(f"[dim]  turn {turn}:[/] {snippet}")
            elif block.type == "tool_use":
                tool_calls_this_turn.append(block)
        messages.append({"role": "assistant", "content": resp.content})

        transcript.append({
            "turn": turn,
            "stop_reason": resp.stop_reason,
            "in_tokens": resp.usage.input_tokens,
            "out_tokens": resp.usage.output_tokens,
        })

        if resp.stop_reason == "end_turn":
            console.print(f"[yellow]  end_turn at turn {turn}[/]")
            break
        if resp.stop_reason == "max_tokens" and tool_calls_this_turn:
            # The response was cut off mid-tool-call; the partial tool_use block
            # is unusable. Drop the broken assistant turn and nudge the model
            # to retry with a shorter response.
            console.print(f"[yellow]  turn {turn}: max_tokens hit with partial tool_use — retrying[/]")
            messages.pop()  # remove the malformed assistant message we just appended
            messages.append({"role": "user",
                              "content": "Your previous response was cut off. Please continue with a SHORTER tool call (just the next focused step, not multiple operations bundled)."})
            continue
        if resp.stop_reason != "tool_use" or not tool_calls_this_turn:
            console.print(f"[yellow]  stop_reason={resp.stop_reason} — exiting[/]")
            break

        tool_results = []
        for tc in tool_calls_this_turn:
            code = tc.input.get("code", "")
            console.print(f"[blue]  run_python[/] ({len(code)} chars)")
            (sandbox / f"_tool_calls").mkdir(exist_ok=True)
            (sandbox / "_tool_calls" / f"turn_{turn:02d}_{tc.id[-8:]}.py").write_text(code)
            result = run_python(code, sandbox)
            content = format_tool_result(result)
            (sandbox / "_tool_calls" / f"turn_{turn:02d}_{tc.id[-8:]}.out").write_text(content)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tc.id,
                "content": content,
                "is_error": result["returncode"] != 0,
            })
        messages.append({"role": "user", "content": tool_results})
    else:
        console.print(f"[red]  hit max_turns ({args.max_turns})[/]")

    # Save final state
    meta = {
        "task": args.task,
        "variant": variant_label,
        "base_variant": args.variant,
        "calibrate": args.calibrate,
        "model": args.model,
        "max_turns": args.max_turns,
        "turns_used": len(transcript),
        "stop_reason": transcript[-1]["stop_reason"] if transcript else None,
        "tokens": {"input_total": total_in_tok, "output_total": total_out_tok,
                   "cache_creation_total": total_cache_create_tok,
                   "cache_read_total": total_cache_read_tok},
        "produced_trace": (sandbox / "trace.md").exists(),
        "produced_answer": (sandbox / "answer.txt").exists(),
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    (sandbox / "meta.json").write_text(json.dumps(meta, indent=2))
    (sandbox / "transcript.json").write_text(json.dumps(transcript, indent=2))

    console.print(f"\n[bold]Summary[/]")
    console.print(f"  turns: {len(transcript)} / {args.max_turns}")
    console.print(f"  tokens: in={total_in_tok:,} out={total_out_tok:,}  "
                  f"cache_read={total_cache_read_tok:,} cache_create={total_cache_create_tok:,}")
    console.print(f"  produced trace.md: {meta['produced_trace']}")
    console.print(f"  produced answer.txt: {meta['produced_answer']}")
    console.print(f"\n[green]done[/] -> {sandbox}/")


if __name__ == "__main__":
    main()
