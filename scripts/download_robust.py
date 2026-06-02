"""Stall-proof BiomniBench-DA task downloader.

Root-cause fix for the hang we hit: snapshot_download has NO socket timeout, so a
stalled HF connection waits forever. Here we:
  - set HF_HUB_DOWNLOAD_TIMEOUT so a dead chunk RAISES instead of hanging,
  - enable hf_transfer (parallel chunked download + native retry) when available,
  - wrap each task in a bounded retry loop (resumable: cached files are skipped),
  - skip tasks already complete on disk,
  - print one progress line per task so a watcher can track it.

Usage:
    HF_TOKEN=... uv run --with huggingface_hub --with hf_transfer \
        scripts/download_robust.py --need /path/need.txt --data data/biomnibench-da
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# MUST be set before importing huggingface_hub
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "30")   # seconds/chunk -> no infinite hang
os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "1")  # fast parallel backend

from huggingface_hub import snapshot_download  # noqa: E402
from huggingface_hub.utils import HfHubHTTPError  # noqa: E402

REPO = "phylobio/BiomniBench-DA"


def complete(task_dir: Path) -> bool:
    # A task is complete only if its data dir actually holds files. An empty
    # environment/data (left by a partial/interrupted pull) must NOT count as
    # done, or the task silently ships with no data.
    data = task_dir / "environment" / "data"
    has_data = data.is_dir() and any(p.is_file() for p in data.rglob("*"))
    return (task_dir / "environment" / "Dockerfile").exists() and has_data


def fetch(tid: str, data_root: Path, token: str | None, tries: int = 6) -> bool:
    for attempt in range(1, tries + 1):
        try:
            snapshot_download(
                repo_id=REPO,
                repo_type="dataset",
                local_dir=str(data_root),
                allow_patterns=[f"{tid}/*"],
                token=token,
                max_workers=8,
            )
            return True
        except (HfHubHTTPError, OSError, TimeoutError) as e:
            wait = min(2 ** attempt, 60)
            print(f"  [{tid}] attempt {attempt}/{tries} failed: {type(e).__name__}: "
                  f"{str(e)[:80]} -> retry in {wait}s", flush=True)
            time.sleep(wait)
    return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--need", type=Path, required=True, help="file with one task id per line")
    ap.add_argument("--data", type=Path, default=Path("data/biomnibench-da"))
    args = ap.parse_args()
    token = os.environ.get("HF_TOKEN")
    if not token:
        print("WARNING: HF_TOKEN unset (gated repo may 401)", flush=True)

    ids = [l.strip() for l in args.need.read_text().splitlines() if l.strip()]
    args.data.mkdir(parents=True, exist_ok=True)
    print(f"need {len(ids)} tasks; backend hf_transfer={os.environ.get('HF_HUB_ENABLE_HF_TRANSFER')} "
          f"timeout={os.environ.get('HF_HUB_DOWNLOAD_TIMEOUT')}s", flush=True)

    ok, skip, fail = 0, 0, []
    for i, tid in enumerate(ids, 1):
        if complete(args.data / tid):
            skip += 1
            print(f"[{i}/{len(ids)}] SKIP {tid} (already complete)", flush=True)
            continue
        t0 = time.time()
        if fetch(tid, args.data, token):
            ok += 1
            sz = sum(f.stat().st_size for f in (args.data / tid).rglob("*") if f.is_file())
            print(f"[{i}/{len(ids)}] OK {tid} {sz/1e6:.0f}MB in {time.time()-t0:.0f}s", flush=True)
        else:
            fail.append(tid)
            print(f"[{i}/{len(ids)}] FAIL {tid} (exhausted retries)", flush=True)

    print(f"DONE ok={ok} skip={skip} fail={len(fail)} {fail}", flush=True)
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
