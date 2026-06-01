# Authoring adversarial-variant specs (BiomniBench-DA)

Goal: turn an answerable task into a **provably unanswerable** variant by removing
the answer-critical signal from the data. The deterministic builder EMITS a variant
only if every `required_signal` check passes (the signal is gone, not re-encoded
in a sibling column/sheet/file). Author specs; the gate proves them.

## Where the signal lives
The answer-critical signal (sample→condition mapping, cell-line label, disease
group, survival outcome, the named entities the rubric scores) is almost always in
a **metadata CSV/TSV/XLSX**, NOT the big count matrix (.mtx/.h5/.h5ad/.bam). Target
the metadata file. The matrix can stay — without the labels it's uninterpretable.

## Defect modes (author AS MANY distinct modes as the task genuinely supports)
1. **drop-column (structural)** — remove the column the analysis keys on
   (response, survival, group, the grouping variable). Also drop/anonymize any
   sibling column that leaks it (e.g. donor IDs that encode disease).
2. **single-group collapse** — subset to ONE level of the grouping variable, so a
   between-group comparison is impossible (n_groups=1).
3. **statistical underpowering** — `reduce_n` the cohort so the test is COMPUTABLE
   but uninterpretable (~1 event). expected_behavior=caveat_underpowered, NOT refuse.
4. **multi-file/sheet drop** — when signal spans files/sheets, drop all carriers.

A mode only counts if the gate proves the signal is gone. One excellent gated
variant beats three that don't emit.

## Op kinds (ops: apply the perturbation)
- `drop_columns`        params: file, columns:[..], (sheet, header_row, scope:all_sheets)
- `drop_columns_matching` params: file, pattern (regex), (sheet, header_row)
- `subset_to_single_group` params: file, column, keep_value, (sheet, header_row)
- `drop_rows_by_value`  params: file, column, keep_values:[..]  (keeps only these)
- `anonymize_column`    params: file, column, prefix   (neutralizes leaky labels)
- `reduce_n`            params: file, n, seed, (header_row)   (deterministic subsample)

## Check kinds (required_signal: the gate — must ALL pass to emit)
- `column_absent`      params: file, column            (column fully removed)
- `no_column_matching` params: file, pattern           (no column name matches regex)
- `no_value_matching`  params: file, column, pattern   (no cell in column matches regex)
- `single_value_in`    params: file, column, max_distinct:1
- `max_rows`           params: file, max               (row count ≤ max)
all checks also accept: sheet, header_row.

## Spec file (one YAML per variant) → benchmarks/specs/biomnibench-da/<name>.yaml
```yaml
name: da-3-5_drop_significance      # <base>_<short-mode>
benchmark: biomnibench-da
base_task: da-3-5
expected_behavior: refuse           # refuse | caveat_underpowered
ops:
  - kind: drop_columns
    file: <relative path under environment/data/>
    columns: [<col>]
    header_row: 0                   # set if the table has title rows above the header
required_signal:
  - kind: column_absent
    file: <same file>
    column: <col>
notes: >
  WHY unanswerable: <one or two sentences tying the dropped signal to the rubric>.
```

## Workflow
1. Read `data/biomnibench-da/<task>/instruction.md` (the `## Question`) and
   `tests/rubric.txt` — identify exactly what the answer requires.
2. Inspect the metadata file's columns/values (pandas, or the adapter). Note
   `header_row` if there are title rows above the real header (common in xlsx).
3. Author 1–N gated specs (one per distinct mode the task supports).
4. Verify EACH emits:  `uv run python scripts/check_spec.py benchmarks/specs/biomnibench-da/<name>.yaml`
   exit 0 + "EMIT ✓" = gate passed. If REJECT, the signal survived — fix ops/checks.
5. Never leave built data on disk (check_spec deletes its own temp dir).
