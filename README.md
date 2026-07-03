# Trustworthy Biology Agents

Benchmarking notes and harnesses for evaluating scientific AI agents on biological data-analysis tasks.

The motivating question is not only whether an agent can reach the right answer, but whether it behaves like a trustworthy analyst when the task is ambiguous, under-specified, or impossible with the provided data.

## What I built

- Framed a trust evaluation for biology agents around computation, calibration, refusal, trajectory consistency, and benchmark validity.
- Built and interpreted BiomniBench-DA adversarial variants and result summaries.
- Corrected over-strong public claims when later judging showed that the initial zero-refusal framing was too strong.

## Where coding agents helped

- Implemented and iterated on runners, graders, extractors, variant specs, utilities, and documentation drafts.
- Helped with local audit passes for private paths, result framing, and publication caveats.
- Produced drafts and implementation help only; public claims are tied to run artifacts, source files, and reviewed summaries.

## Current Focus

This repository started as a BiomniBench-DA investigation:

- Can paper-recall contamination explain high benchmark scores?
- Do code-executing agents actually compute from the data?
- Do agents know when to caveat or refuse when required data is missing?
- Are the benchmark variants themselves valid unanswerable cases?

The working summary is in [`RESULTS.md`](RESULTS.md).

## Headline Findings

- **Process helps against contamination.** Prediction-only probes can expose paper-identifying cues, but real code-executing agents are much less driven by that signal.
- **Calibration fails when it matters.** Confidence is most useful on hard or variable tasks, but that is exactly where overconfidence becomes most visible.
- **Trajectory consistency is a separate trust axis.** Agents often choose the same broad operations across reruns while applying them in different orders.
- **Refusal is rare and judge-sensitive.** A first-pass "zero refusals" result was too strong; stronger re-judging found some real refusals, while the dominant failure remained partial acknowledgment followed by an answer.
- **Variant validity needs a gate.** Biomedical datasets often contain redundant signal in sibling columns, sheets, files, or metadata. An unanswerable variant should not be emitted unless checks prove the answer-critical signal is gone.

## Repository Map

- `RESULTS.md` — current research compendium and evolving writeup.
- `bench/` — reusable runner pieces for assembling, running, and grading benchmark tasks.
- `benchmarks/variant_pipeline/` — spec-driven adversarial variant construction and validation.
- `benchmarks/specs/` — variant specs for BiomniBench-DA tasks.
- `benchmarks/coverage_matrix.md` — task-format coverage and redundancy hazard survey.
- `benchmarks/SOURCES.md` — source-paper provenance for BiomniBench-DA task groups.
- `docs/research/` — design notes, literature reviews, and follow-on benchmark results.
- `scripts/` — experiment, grading, extraction, and audit utilities.

## Reproducibility Notes

The repo intentionally excludes local data, runs, and secrets:

- `.env`, `data/`, and `runs/` are gitignored.
- Public BiomniBench-DA data should be fetched separately from its source distribution.
- Agent and judge API keys should stay in local environment files only.

Most scripts are designed to run through `uv` once dependencies and data are present. Exact commands vary by experiment and are documented in `RESULTS.md` and `bench/README.md`.

## Verification

- 2026-07-02: `uv run pytest -q tests/test_providers.py` -> 8 passed.
- 2026-07-02: `jq empty results/biomnibench/summary.json results/biomnibench/refusal/refusal_classifications.json results/biomnibench/refusal/refusal_consolidated.json` -> passed.
- 2026-07-02: `git diff --check` -> passed.

## Limitations

- This is a working research repository, not a paper claim.
- Raw benchmark inputs and full run directories are excluded unless a scrubbed result bundle is deliberately released.
- Refusal labels and failure-mode labels are judge-sensitive derived evidence, not standalone benchmark ground truth.

## Status

This is a working research repository. The public-facing note is being distilled at:

https://manu-tej.github.io/research/biomnibench/

## License

MIT. See [`LICENSE`](LICENSE).

## Attribution & Third-Party Licenses

This project evaluates and builds adversarial variants on top of **BiomniBench-DA**
(Phylo — [`phylobio/BiomniBench-DA`](https://huggingface.co/datasets/phylobio/BiomniBench-DA)),
whose benchmark artifacts (instructions, rubrics, reference traces, judge prompts) are
released under **CC-BY-4.0**. The variant specs in `benchmarks/specs/` are derivative
works of those tasks and are shared under the same **CC-BY-4.0** terms, with attribution
to the source benchmark and to the underlying publications listed in
[`benchmarks/SOURCES.md`](benchmarks/SOURCES.md).

The underlying biomedical datasets (GEO, TCGA, CPTAC, cBioPortal, etc.) are **not
redistributed here** — only citations and accessions are included. They retain their
original public-release terms and must be fetched from their source distributions.

Original code in this repository is MIT-licensed.
