"""Deduplicate + summarize the refusal judgments into the canonical table.

Canonical sources (no host overlap):
  codex       -> runs/traces_codex   (remote, 9 cells)
  claude-code -> runs/harbor_matrix  (Mac, the 5 that didn't hit the session limit)
  gemini-cli  -> (pending quota reset)

Reads each refusal_judgment.json sidecar, keeps one row per (harness, task),
prints the cross-vendor abstention table + per-harness tallies.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# (harness, source-root) — the canonical, non-overlapping provenance
SOURCES = [
    ("codex", ROOT / "runs/traces_codex"),
    ("claude-code", ROOT / "runs/harbor_matrix"),
    ("gemini-cli", ROOT / "runs/harbor_matrix_gemini"),
]

ABSTAINS = {"APPROPRIATE_REFUSAL"}
PARTIAL = {"PARTIAL_ACKNOWLEDGMENT"}


def _session_limited(trace_path: Path) -> bool:
    """A claude-code cell that hit the Claude session 429 never really attempted
    the task — its 'answer' is the limit message. Exclude from the table."""
    try:
        return "session limit" in trace_path.read_text(errors="ignore")
    except Exception:
        return False


def collect() -> tuple[list[dict], list[str]]:
    rows: dict[tuple[str, str], dict] = {}
    excluded: list[str] = []
    for harness, root in SOURCES:
        if not root.exists():
            continue
        for sc in root.rglob("refusal_judgment.json"):
            d = json.loads(sc.read_text())
            if d.get("harness") != harness:
                continue
            trace = sc.parent / "agent" / f"{harness}.txt"
            if harness == "claude-code" and trace.exists() and _session_limited(trace):
                excluded.append(f"{harness}/{d['task']}")
                continue
            key = (harness, d["task"])
            rows.setdefault(key, d)  # first wins; one per (harness,task)
    return list(rows.values()), sorted(set(excluded))


def main() -> None:
    rows, excluded = collect()
    if excluded:
        print(f"excluded {len(excluded)} session-limited cells: {excluded}\n")
    tasks = sorted({r["task"] for r in rows})
    harnesses = sorted({r["harness"] for r in rows})

    # matrix print
    cls_by = {(r["harness"], r["task"]): r.get("classification", "?") for r in rows}
    abbr = {"APPROPRIATE_REFUSAL": "REFUSE", "PARTIAL_ACKNOWLEDGMENT": "PARTIAL",
            "FABRICATION": "FABRIC", "INCOMPLETE": "INCOMP"}
    print(f"{'task':28} " + " ".join(f"{h:12}" for h in harnesses))
    for t in tasks:
        cells = " ".join(f"{abbr.get(cls_by.get((h, t),'-'),'-'):12}" for h in harnesses)
        print(f"{t:28} {cells}")

    print("\nper-harness tally:")
    for h in harnesses:
        hr = [r for r in rows if r["harness"] == h]
        c = Counter(r.get("classification") for r in hr)
        refuse = c.get("APPROPRIATE_REFUSAL", 0)
        print(f"  {h:12} n={len(hr):2}  "
              f"REFUSE={refuse}  PARTIAL={c.get('PARTIAL_ACKNOWLEDGMENT',0)}  "
              f"FABRIC={c.get('FABRICATION',0)}  INCOMP={c.get('INCOMPLETE',0)}")

    n = len(rows)
    refuse = sum(1 for r in rows if r.get("classification") in ABSTAINS)
    detected = sum(1 for r in rows if r.get("detected_problem"))
    print(f"\nOVERALL  n={n}  appropriate_refusal={refuse}/{n}  "
          f"detected_problem={detected}/{n}")

    (ROOT / "runs/refusal_canonical.json").write_text(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
