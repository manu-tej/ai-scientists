"""Registry of all variants and their validity status (single source of truth)."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .builder import BuildResult


def write_manifest(results: list[BuildResult], path: str | Path) -> dict:
    rows = []
    for r in results:
        rows.append({
            "name": r.name,
            "emitted": r.emitted,
            "validated": r.all_passed,
            "error": r.error,
            "checks": [{"kind": c.kind, "passed": c.passed, "detail": c.detail} for c in r.checks],
        })
    summary = {
        "total": len(rows),
        "emitted": sum(1 for r in rows if r["emitted"]),
        "validated": sum(1 for r in rows if r["validated"]),
        "failed": [r["name"] for r in rows if not r["emitted"]],
    }
    out = {"summary": summary, "variants": rows}
    Path(path).write_text(json.dumps(out, indent=2))
    return out
