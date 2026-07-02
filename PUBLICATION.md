# Publication Readiness

Status: public repo (released 2026-07-02). Code, variant specs, and derived results; source datasets cited by accession, not redistributed.

## What I Did

- Framed the trust question for biology agents: capability is not enough; calibration, refusal, trajectory consistency, and benchmark validity matter.
- Designed and interpreted BiomniBench-DA experiments and adversarial variants.
- Audited and corrected claims when later judging showed that the initial zero-refusal framing was too strong.
- Own the public summary and final interpretation.

## Coding-Agent Help

- Coding agents helped implement scripts, runners, graders, extractors, variant specs, and repeated local audits.
- Coding agents drafted intermediate plans and summaries.
- Agent outputs are treated as implementation assistance or drafts until checked against run artifacts and benchmark constraints.

## Excluded From Publication

These should stay out of the public repo unless deliberately released:

- `.env` and any provider/auth tokens.
- Raw benchmark data under `data/`.
- Full run directories under `runs/` unless a specific result bundle is scrubbed and intentional.
- Local browser/debug artifacts.

## Current Gates

- Keep `results/biomnibench/refusal/refusal_classifications.json` only as the early per-response refusal screen unless individual labels are re-adjudicated again.
- Keep `results/biomnibench/failure_analysis.xlsx` only as a derived working analysis artifact; do not treat manual failure-mode labels as a benchmark ground truth without review.
- Keep the corrected `RESULTS.md` banner and machine-readable summary framing: rare refusals, not zero refusals.
- Source-task redistribution: **RESOLVED (2026-07-02).** BiomniBench-DA (phylobio) benchmark artifacts are **CC-BY-4.0**; derived variant specs are shared under CC-BY-4.0 with attribution (see README "Attribution & Third-Party Licenses" + `benchmarks/SOURCES.md`). Underlying biomedical datasets are **not** redistributed — cited by accession only, retaining their original source terms.

## Verification

- 2026-07-02: `uv run pytest -q tests/test_providers.py` -> 8 passed.
- 2026-07-02: `jq empty results/biomnibench/summary.json` -> passed.
- 2026-07-02: `git diff --check` -> passed.
- 2026-07-02: inspected `results/biomnibench/refusal/refusal_classifications.json`; it contains 14 early labels: 7 `FABRICATION` and 7 `PARTIAL_ACKNOWLEDGMENT`, with no `APPROPRIATE_REFUSAL`. Public claim remains based on `refusal_consolidated.json`, not this early screen alone.
- 2026-07-02: inspected `results/biomnibench/failure_analysis.xlsx`; sheets are `Failure Analysis`, `Per-Rep Detail`, `Rubric Defects (confirmed)`, `All Scores (150)`, and `Summary`. Sensitive-string scan did not find local user paths or credentials; matches were benchmark/container paths such as `/app/...` and `/environment/data/...`.
- 2026-07-02: removed a private raw-run host/path reference from `results/biomnibench/README.md`; raw traces are now described as excluded unless a scrubbed bundle is intentionally released.

## Website Link

Public note draft:

https://manu-tej.github.io/research/biomnibench/
