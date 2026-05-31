"""Declarative variant specification (loaded from YAML)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Op:
    """One perturbation applied to the base data to remove answer-critical signal."""
    kind: str            # drop_columns | drop_rows_by_value | subset_to_single_group | anonymize_column | reduce_n
    params: dict = field(default_factory=dict)


@dataclass
class SignalCheck:
    """One assertion the built variant must satisfy to count as unanswerable."""
    kind: str            # no_column_matching | single_value_in | no_value_matching | max_rows | column_absent
    params: dict = field(default_factory=dict)


@dataclass
class VariantSpec:
    name: str
    benchmark: str
    base_task: str
    expected_behavior: str               # refuse | caveat_underpowered
    ops: list[Op] = field(default_factory=list)
    required_signal: list[SignalCheck] = field(default_factory=list)
    notes: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "VariantSpec":
        return cls(
            name=d["name"],
            benchmark=d["benchmark"],
            base_task=d["base_task"],
            expected_behavior=d.get("expected_behavior", "refuse"),
            ops=[Op(kind=o["kind"], params={k: v for k, v in o.items() if k != "kind"})
                 for o in d.get("ops", [])],
            required_signal=[SignalCheck(kind=c["kind"], params={k: v for k, v in c.items() if k != "kind"})
                             for c in d.get("required_signal", [])],
            notes=d.get("notes", ""),
        )

    @classmethod
    def from_yaml(cls, path: str | Path) -> "VariantSpec":
        return cls.from_dict(yaml.safe_load(Path(path).read_text()))
