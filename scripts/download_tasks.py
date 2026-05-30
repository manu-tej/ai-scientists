"""Selectively download BiomniBench-DA tasks.

Usage:
    # Just rubrics + instructions for the first 5 tasks (no big data files):
    uv run scripts/download_tasks.py --rubrics-only --limit 5

    # Full task (includes environment/ — can be many GB per task):
    uv run scripts/download_tasks.py --task-id da-1-3
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from huggingface_hub import HfApi, snapshot_download
from rich.console import Console

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ai_scientists import DATASET_REPO, DATA_ROOT  # noqa: E402

console = Console()


def list_remote_task_ids(token: str | None) -> list[str]:
    api = HfApi(token=token)
    files = api.list_repo_files(DATASET_REPO, repo_type="dataset")
    ids = sorted({f.split("/")[0] for f in files if f.startswith("da-")})
    return ids


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", help="Download a single task in full (incl. environment/)")
    parser.add_argument("--limit", type=int, default=5, help="How many tasks to download")
    parser.add_argument(
        "--rubrics-only",
        action="store_true",
        help="Skip environment/ — pull only instruction.md, task.toml, tests/",
    )
    parser.add_argument("--list", action="store_true", help="Just list remote task IDs and exit")
    args = parser.parse_args()

    token = os.environ.get("HF_TOKEN")
    if not token:
        console.print("[yellow]HF_TOKEN not set — gated dataset will fail. See .env.example[/]")

    if args.list:
        for tid in list_remote_task_ids(token):
            console.print(tid)
        return

    if args.task_id:
        targets = [args.task_id]
    else:
        targets = list_remote_task_ids(token)[: args.limit]

    allow_patterns = None
    if args.rubrics_only:
        allow_patterns = ["*/instruction.md", "*/task.toml", "*/tests/*"]

    for tid in targets:
        console.print(f"[cyan]→[/] {tid}")
        snapshot_download(
            repo_id=DATASET_REPO,
            repo_type="dataset",
            local_dir=DATA_ROOT,
            allow_patterns=[f"{tid}/*"] if not args.rubrics_only
            else [f"{tid}/instruction.md", f"{tid}/task.toml", f"{tid}/tests/*"],
            token=token,
        )

    console.print(f"[green]done[/] → {DATA_ROOT}/")


if __name__ == "__main__":
    main()
