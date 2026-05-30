from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from . import DATA_ROOT


@dataclass(frozen=True)
class Task:
    task_id: str
    root: Path

    @property
    def instruction(self) -> str:
        return (self.root / "instruction.md").read_text()

    @property
    def config(self) -> dict:
        path = self.root / "task.toml"
        return tomllib.loads(path.read_text()) if path.exists() else {}

    @property
    def rubric_dir(self) -> Path:
        return self.root / "tests"

    @property
    def env_dir(self) -> Path:
        return self.root / "environment"


def list_tasks(root: str | Path = DATA_ROOT) -> list[Task]:
    root = Path(root)
    if not root.exists():
        return []
    return [
        Task(task_id=p.name, root=p)
        for p in sorted(root.iterdir())
        if p.is_dir() and p.name.startswith("da-")
    ]


def load_task(task_id: str, root: str | Path = DATA_ROOT) -> Task:
    path = Path(root) / task_id
    if not path.exists():
        raise FileNotFoundError(f"Task not found: {path}")
    return Task(task_id=task_id, root=path)
