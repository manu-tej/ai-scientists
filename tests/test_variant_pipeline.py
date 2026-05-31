"""Correctness tests for the adversarial-variant pipeline (ops + the validator gate).

Uses small synthetic fixtures — no downloads, no big files.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from openpyxl import Workbook

from benchmarks.variant_pipeline import (
    VariantSpec, build_variant, validate, get_adapter, UnsupportedFormat,
)
from benchmarks.variant_pipeline.adapters import TabularAdapter
from benchmarks.variant_pipeline.ops import apply_op
from benchmarks.variant_pipeline.spec import Op


# --------------------------------------------------------------------------- #
# Fixtures: a base data dir mimicking a multi-row-header CSV + an xlsx         #
# --------------------------------------------------------------------------- #

@pytest.fixture
def base_data(tmp_path: Path) -> Path:
    d = tmp_path / "base"
    d.mkdir()
    # CSV with a 3-row preamble then header at row 3 (like da-13-3)
    (d / "table.csv").write_text(
        "Title row\n"
        "subtitle\n"
        "\n"
        "protein_id,estimate_Percent_Fat,adj.p.value_Percent_Fat,estimate_Breast_Volume,adj.p.value_Breast_Volume\n"
        "P1,0.5,0.01,0.3,0.20\n"
        "P2,0.2,0.30,0.1,0.04\n"
    )
    # XLSX with a 'tier' column spread across two sheets (like da-5-1)
    wb = Workbook()
    s2a = wb.active
    s2a.title = "S2A"
    s2a.append(["Gene", "Assigned Tier", "Family"])
    s2a.append(["GART", "Tier1", "kinase"])
    s2b = wb.create_sheet("S2B")
    s2b.append(["Drug", "Target", "Tier"])
    s2b.append(["d1", "GART", "Tier1"])
    wb.save(d / "mmc.xlsx")
    # CSV with a grouping column (like da-3-4 Response)
    (d / "resp.csv").write_text("patient,Response,TMB\nA,R,10\nB,NR,3\nC,R,8\n")
    return d


# --------------------------------------------------------------------------- #
# Adapter / ops                                                                #
# --------------------------------------------------------------------------- #

def test_csv_drop_columns_preserves_preamble(base_data: Path):
    apply_op(Op("drop_columns", {"file": "table.csv", "header_row": 3,
                                 "columns": ["estimate_Percent_Fat", "adj.p.value_Percent_Fat"]}), base_data)
    cols = TabularAdapter(base_data / "table.csv").list_columns(header_row=3)
    assert "estimate_Percent_Fat" not in cols
    assert "adj.p.value_Percent_Fat" not in cols
    assert "estimate_Breast_Volume" in cols  # the OTHER measure survives
    # preamble still present (file still starts with the title)
    assert (base_data / "table.csv").read_text().startswith("Title row")


def test_xlsx_drop_columns_all_sheets(base_data: Path):
    apply_op(Op("drop_columns", {"file": "mmc.xlsx", "sheet": "S2A", "columns": ["Assigned Tier"]}), base_data)
    apply_op(Op("drop_columns", {"file": "mmc.xlsx", "sheet": "S2B", "columns": ["Tier"]}), base_data)
    ad = TabularAdapter(base_data / "mmc.xlsx")
    assert "Assigned Tier" not in ad.list_columns(sheet="S2A")
    assert "Tier" not in ad.list_columns(sheet="S2B")


def test_subset_to_single_group(base_data: Path):
    apply_op(Op("subset_to_single_group", {"file": "resp.csv", "column": "Response", "keep_value": "R"}), base_data)
    vals = set(TabularAdapter(base_data / "resp.csv").column_values("Response"))
    assert vals == {"R"}


# --------------------------------------------------------------------------- #
# Validator gate                                                               #
# --------------------------------------------------------------------------- #

def test_validator_catches_tier_left_in_other_sheet(base_data: Path):
    # Only drop from S2A (the original bug) -> Tier remains in S2B -> must FAIL.
    apply_op(Op("drop_columns", {"file": "mmc.xlsx", "sheet": "S2A", "columns": ["Assigned Tier"]}), base_data)
    spec = VariantSpec.from_dict({
        "name": "t", "benchmark": "b", "base_task": "x", "expected_behavior": "refuse",
        "required_signal": [{"kind": "no_column_matching", "file": "mmc.xlsx",
                             "scope": "all_sheets", "pattern": r"(?i)\btier\b"}],
    })
    results = validate(spec, base_data)
    assert results[0].passed is False  # Tier still in S2B


def test_validator_passes_when_tier_fully_gone(base_data: Path):
    apply_op(Op("drop_columns", {"file": "mmc.xlsx", "sheet": "S2A", "columns": ["Assigned Tier"]}), base_data)
    apply_op(Op("drop_columns", {"file": "mmc.xlsx", "sheet": "S2B", "columns": ["Tier"]}), base_data)
    spec = VariantSpec.from_dict({
        "name": "t", "benchmark": "b", "base_task": "x", "expected_behavior": "refuse",
        "required_signal": [{"kind": "no_column_matching", "file": "mmc.xlsx",
                             "scope": "all_sheets", "pattern": r"(?i)\btier\b"}],
    })
    assert validate(spec, base_data)[0].passed is True


def test_validator_no_value_matching_catches_leak(base_data: Path):
    # resp.csv 'patient' values don't leak, but assert the check mechanics
    spec = VariantSpec.from_dict({
        "name": "t", "benchmark": "b", "base_task": "x", "expected_behavior": "refuse",
        "required_signal": [{"kind": "no_value_matching", "file": "resp.csv",
                             "column": "Response", "pattern": r"NR"}],
    })
    # Response still has NR -> leak -> fail
    assert validate(spec, base_data)[0].passed is False


# --------------------------------------------------------------------------- #
# Builder: emit-only-if-valid                                                  #
# --------------------------------------------------------------------------- #

def test_builder_refuses_to_emit_invalid_variant(base_data: Path, tmp_path: Path):
    # Spec drops Tier only from S2A but REQUIRES tier gone everywhere -> must refuse.
    spec = VariantSpec.from_dict({
        "name": "bad", "benchmark": "b", "base_task": "x", "expected_behavior": "refuse",
        "ops": [{"kind": "drop_columns", "file": "mmc.xlsx", "sheet": "S2A", "columns": ["Assigned Tier"]}],
        "required_signal": [{"kind": "no_column_matching", "file": "mmc.xlsx",
                             "scope": "all_sheets", "pattern": r"(?i)\btier\b"}],
    })
    out = tmp_path / "variant"
    res = build_variant(spec, base_data, out)
    assert res.emitted is False
    assert "validation_failed" in res.error
    assert not out.exists()  # broken output removed


def test_builder_emits_valid_variant(base_data: Path, tmp_path: Path):
    spec = VariantSpec.from_dict({
        "name": "good", "benchmark": "b", "base_task": "x", "expected_behavior": "refuse",
        "ops": [
            {"kind": "drop_columns", "file": "mmc.xlsx", "sheet": "S2A", "columns": ["Assigned Tier"]},
            {"kind": "drop_columns", "file": "mmc.xlsx", "sheet": "S2B", "columns": ["Tier"]},
        ],
        "required_signal": [{"kind": "no_column_matching", "file": "mmc.xlsx",
                             "scope": "all_sheets", "pattern": r"(?i)\btier\b"}],
    })
    out = tmp_path / "variant"
    res = build_variant(spec, base_data, out)
    assert res.emitted is True and res.all_passed
    assert (out / "mmc.xlsx").exists() and (out / "resp.csv").exists()  # other files copied


def test_unsupported_format_flagged(tmp_path: Path):
    (tmp_path / "x.bam").write_bytes(b"BAM\x00")
    with pytest.raises(UnsupportedFormat):
        get_adapter(tmp_path / "x.bam")
