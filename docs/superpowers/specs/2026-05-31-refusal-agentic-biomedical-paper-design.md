# Design Spec: Refusal as the Missing Axis in Agentic Biomedical Agents (position note)

**Date:** 2026-05-31
**Type:** arXiv position / methodology note
**Status:** approved design, pre-implementation

## 1. What this is

A short arXiv position/methodology note arguing that **refusal/abstention is an
unmeasured trust axis in agentic biomedical benchmarks**, and that the agentic
setting introduces a failure pathway — *fabrication via silent external-data
substitution* — that text-QA abstention benchmarks structurally cannot observe.

The note co-headlines two results as a single **outcome → process → agency**
progression:

1. **Process scoring defeats contamination** (validates BiomniBench's design):
   prediction-only probes recall published conclusions from task text (+60-pt
   signal), but real code-executing agents on the same tasks show ≈0-pt effect.
2. **But agents still don't refuse**: across adversarial *unanswerable* task
   variants, frontier agents issue near-zero appropriate refusals; on agentic
   tasks they fabricate by substituting external data, and even on QA with an
   explicit "insufficient information" option they under-abstain.

## 2. Thesis (the flag we plant)

In agentic biomedical settings, abstention failure has a *fabrication-via-
substitution* pathway that text-QA abstention benchmarks cannot exhibit (there
is no tool with which to fabricate). Frontier agents (Claude Opus 4.7, Gemini 3)
under-refuse across two benchmarks; process scoring fixed memorization but cannot
see this, because it grades the trajectory the agent *chose to produce*, not what
the agent should have declined to do.

### Honest positioning vs. prior work (mandatory)

Refusal/abstention is NOT unmeasured in general. We must cite and distinguish:

- **AbstentionBench** (Meta/FAIR, 2025) — text QA; reasoning LLMs fail on
  unanswerable questions; model scale barely helps. Our agentic result extends
  this and adds the fabrication pathway.
- **LAB-Bench / LAB-Bench2** (FutureHouse) — biology QA with a built-in
  "insufficient information" option and accuracy/precision/coverage metrics. We
  reuse LAB-Bench2 as our second benchmark.
- **RefusalBench**, **BixBench**, **ScienceAgentBench** — related; cite.

The novel contribution is the **agentic-biomedical regime + the fabrication
pathway**, NOT "agents under-refuse" in the abstract.

## 3. Scope honesty rules (enforced throughout)

- All result sentences name the specific models ("Claude Opus 4.7", "Gemini 3"),
  never the bare word "agents," except in framing/discussion.
- Claims are scoped to: **2 models × 2 benchmarks; 6 agentic tasks; 11
  adversarial variants; Claude-based judges.** Limitations section states this
  plainly.
- §4 (contamination-defeat) is kept visibly shorter than §5–6, matching its
  thinner evidence base (2 tasks deep vs. 6).

## 4. Abstract (~190 words, current draft)

> Process-level benchmarks such as BiomniBench were introduced to fix outcome-only
> evaluation, where a correct answer can come from memorization rather than
> analysis. We confirm the fix works: prediction-only probes recall published
> conclusions from task text (+60-point signal), but real code-executing agents
> show ≈0-point effect. Yet process scoring grades the trajectory the agent *chose
> to produce* — it cannot see what the agent should have declined to do. Using
> adversarial *unanswerable* variants of BiomniBench-DA tasks (a required column
> dropped, a comparison group removed), we find Claude Opus 4.7 and Gemini 3 issue
> near-zero appropriate refusals across 6 tasks and 11 variants; instead they
> fabricate by silently substituting external data. On LAB-Bench2, which offers an
> explicit "insufficient information" option, both models under-abstain. Two
> measurements corroborate an always-commit posture: stated confidence is
> well-calibrated only on tasks the agent always gets right (ECE 0.10→0.90 as
> success falls), and trajectories use the same operations in inconsistent orders.
> Prior work studies abstention for text QA; we show the failure persists and
> acquires a fabrication pathway in agentic biomedical settings, and release the
> measurement harness.

## 5. Title (working)

Primary: **"Agents That Never Say No: Process Scoring Defeats Contamination but
Misses Refusal in Biomedical AI"**

Alternates: "Refusal Is the Missing Axis: What Process-Level Biomedical
Benchmarks Still Can't See"; "From Memorization to Agency: A Trust Audit of
Biomedical Analysis Agents".

## 6. Section outline

| § | Section | Core content | Backing |
|---|---|---|---|
| 1 | Introduction | outcome→process→agency progression; name the fabrication-via-substitution pathway; 2 contributions | — |
| 2 | Background | outcome vs process scoring; BiomniBench; Rabanser reliability framework; **abstention lit: AbstentionBench, LAB-Bench(2), RefusalBench** | lit |
| 3 | Setup | 6 tasks (type/format table); minimal agent scaffold; **2 models (Opus 4.7, Gemini 3)**; adversarial-variant construction; **LAB-Bench2**; judges | `agent.py`, configs |
| 4 | **Result 1** — process scoring defeats contamination (kept short) | probe +60pp → agent ≈0pp; da-12-4 + da-3-4 evidence | `probe.py`, 140 probe + 136 agent runs |
| 5 | **Result 2** — near-zero refusal + fabrication pathway | 0/33 BiomniBench (Opus); + Gemini replication; 4-way failure taxonomy; + LAB-Bench2 under-abstention (both models) | `refusal_judge.py`, 33 sidecars, LAB-Bench2 |
| 6 | Corroborating — always-commit posture | calibration-conditioned-on-difficulty (monotonic ECE, 0 LOW used); trajectory what-but-not-when; both models | `calibration_ece.py`, `trust_metrics.py` |
| 7 | Discussion | why process scoring can't see refusal; contrast with text-QA abstention; the adversarial-variant + judge methodology as the proposal | — |
| 8 | Limitations | 2 models, 6 agentic tasks, one scaffold, Claude judges, small K | — |
| 9 | Conclusion | refusal as a first-class agentic-trust axis; call to incorporate into benchmarks | — |

## 7. Data → claim map (every headline claim → committed artifact)

| Claim | Evidence | Reproduce with | Status |
|---|---|---|---|
| Probe recalls, agent doesn't | 140 probe + 136 agent runs | `probe.py`, `agent.py`, `aggregate.py` | **have** |
| 0/33 refusal (Opus, BiomniBench) | 33 `refusal_judgment.json` | `refusal_judge.py` | **have** |
| Monotonic ECE 0.10→0.90, 0 LOW (Opus) | 36 calibrate runs | `calibration_ece.py --audit` | **have** |
| Trajectory C_seq 0.21–0.57 (Opus) | tool-call logs | `trust_metrics.py` | **have** |
| Refusal/calibration/trajectory replicate on **Gemini 3** | new runs | E1–E2 below | **needed** |
| Under-abstention on **LAB-Bench2** (both models) | new runs | E3 below | **needed** |

## 8. Empirical-expansion plan (the new data the spec needs)

| Step | Work | Effort |
|---|---|---|
| E1 | Gemini 3 provider adapter — abstract the tool-use loop in `agent.py` behind a provider interface (Anthropic + Google), preserving the single `run_python` tool, sandbox layout, caching where supported, and meta.json schema | ~half-day |
| E2 | Re-run 6-task adversarial (11 variants × K=3) + calibrate (per task × K=5) with Gemini 3; re-judge with existing `refusal_judge.py` + `judge.py` + `calibration_ece.py` | compute |
| E3 | LAB-Bench2 harness: download dataset, run Opus 4.7 + Gemini 3 (QA, no agent loop), compute coverage / precision / under-abstention | ~half-day + compute |
| E4 | Extend `refusal_judge.py` / `calibration_ece.py` aggregation to a 2-model × 2-benchmark grid | small |
| E5 | Update RESULTS.md with the expanded grid | small |

### Provider-adapter design constraint (E1)

The adapter must keep these invariants so existing judges/aggregators work
unchanged: per-(task, model, variant, ts) sandbox with `./data/` symlink; writes
`trace.md` + `answer.txt`; `meta.json` carries task/variant/model/turns_used/
tokens/stop_reason/produced_trace/produced_answer; tool calls logged under
`_tool_calls/turn_*.py`. Model slug for Gemini follows the existing
`{provider}_{model}` directory convention.

## 9. Sequencing

1. Write + commit this spec (done).
2. Implementation plan (via writing-plans) for E1–E5.
3. Execute E1–E5; fill the "needed" rows of the data→claim map.
4. Draft prose section by section against the outline.
5. Convert to arXiv form (pandoc/LaTeX) only after content is stable.

Rationale: the outline pins exactly which experiments matter, so no run is made
that the argument doesn't need.

## 10. Risks / open questions

- **Gemini tool-use parity.** Google's function-calling loop differs from
  Anthropic's; the adapter must handle multi-turn tool results and max-token
  recovery equivalently, or the trajectory metric becomes non-comparable.
- **LAB-Bench2 access + licensing.** Confirm dataset availability and that
  re-reporting coverage/precision is permitted.
- **Judge symmetry.** Judges are Claude; judging Gemini outputs may introduce
  cross-family bias. Note explicitly; consider a spot Gemini-judge cross-check.
- **Cost.** Gemini re-runs + LAB-Bench2 across two models; estimate before
  launching (prior BiomniBench agentic runs were ~$11/task with caching).
- **ECE confidence→prob map sensitivity.** Absolute ECE depends on
  HIGH=0.90/MEDIUM=0.60/LOW=0.30; report sensitivity, keep qualitative claims.
- **The Gemini result is not assumed.** The §4 abstract and §2 thesis are written
  for the *hypothesized* outcome (Gemini replicates near-zero refusal). E2 must be
  run before those sentences are asserted. If Gemini 3 refuses substantially more
  than Opus 4.7, that is itself a reportable cross-vendor finding and the thesis
  reframes to "refusal behavior is model-dependent, and at least one frontier
  agent under-refuses with a fabrication pathway" — the paper still stands, but
  the abstract changes. Do not hard-code the two-model claim into prose until the
  data is in.
