# Context-Load Reliability — Literature Review (verified)

**Date:** 2026-06-03
**Purpose:** Methods grounding for the "reliability degrades as agent context accumulates" probe
(performance + refusal/calibration vs. tokens-in-context), on biomedical agents (BiomniBench-DA substrate).
**Status:** All citations below fetched & page-verified by 5 parallel research agents. Body-level numbers
flagged `[unverified-body]` were not extractable from abstract/HTML and must be checked against the PDF
before going load-bearing in a paper.

---

## 1. The effect is real and starts at a tiny fraction of the window

| Work | ID / URL | The knob | Headline number |
|---|---|---|---|
| **Context Rot** (Chroma, Hong/Troynikov/Huber, 2025) | trychroma.com/research/context-rot | fixed trivial task, sweep input length; needle-question similarity; distractor count; coherent vs shuffled haystack | monotonic degradation on *trivial* tasks; 1M models show clear effect ~300–400k; **coherent filler hurts MORE than shuffled** |
| **Same Task, More Tokens / FLenQA** (Levy, Jacoby, Goldberg, 2024) | arXiv:2402.14848 | same reasoning question padded 250→3000 tok; padding type = duplicate/similar/different | **~92% @250 tok → ~68% @3000 tok**; CoT does NOT rescue; unrelated padding hurts more than topical |
| **Lost in the Middle** (Liu et al., TACL 2024) | arXiv:2307.03172 | position of gold doc among answer-free hard-negative distractors; k=10/20/30 | U-shape; **>20pt** drop GPT-3.5; 20–30 docs fall *below* closed-book |
| **RULER** (Hsieh et al., NVIDIA, COLM 2024) | arXiv:2404.06654 | synthetic multi-key/multi-hop at 4k→128k; "effective context length" = threshold crossing | of 17 models claiming ≥32k, **~half** hold at 32k |
| **NoLiMa** (Modarressi et al., ICML 2025) | arXiv:2502.05167 | NIAH with minimal lexical overlap (forces latent retrieval) | at 32k, **11/13** models < 50% of short-context baseline; GPT-4o 99.3%→69.7% |
| **HELMET** (Yen et al., Princeton, ICLR 2025) | arXiv:2410.02694 | application-centric, length-controlled, model-graded | synthetic NIAH **poorly predicts** downstream long-context perf |

Supporting: ∞Bench arXiv:2402.13718; LongBench v2 arXiv:2412.15204 (best model 50.1% vs human 53.7%);
"Context Length Alone Hurts…" arXiv:2510.05381 `[title-only, unverified]`.

**Takeaway:** "Even at 150K of a 1M window" is a *conservative* thesis — FLenQA sees it by 500 tokens.

---

## 2. THE methodological reversal — padding is NOT a neutral length knob (sign-flips)

The single most important finding for our design. Topical relevance & coherence of the filler have
**large, sign-flipping effects** that will confound a naive depth sweep:

| Padding type | Effect on accuracy | Source |
|---|---|---|
| Random / off-topic | **benign → HELPS** (up to +35%, avg +3–4pt) | Power of Noise, Cuconasu et al. SIGIR 2024, arXiv:2401.14887 |
| Coherent, on-topic (e.g. agent's own transcript) | **hurts MORE than shuffled** | Context Rot (Chroma) |
| Same-domain hard negatives | **hurts −6 to −11 pt** | Distracting Effect, Amiraz et al. ACL 2025, arXiv:2505.06914 `[deltas unverified-body]` |
| Keyword-overlap, answer-free decoy | **maximally destructive** | NoLiMa |

**Implication for our padding strategies:**
- Strategy (3) "agent's own prior transcript" and (2) "domain-coherent" = the **riskiest** (maximally
  coherent + on-topic). Keep them, but as **labeled arms expected to over-state degradation**, never as neutral filler.
- Strategy (1) random decoys and (4) raw-data reads = cleaner.
- **You need a Tier-0 pure-noise control** (UUID/shuffled-off-topic, à la Lost-in-the-Middle KV task) to
  separate "token count" from "coherence/distraction." Without it, no causal length claim survives review.

**Decouple two orthogonal factors, never confound:** (a) token count (depth), (b) answer/needle **position**
(Lost-in-the-Middle: position alone = 20%+). Pin relevant material at fixed position while growing padding;
separately sweep position at fixed length.

**Leakage filter** (Longpre et al., EMNLP 2021, arXiv:2109.05052 — entity-based knowledge conflicts): run
NER + Wikidata-alias + coref over the gold answer; reject any padding containing the answer entity, its
aliases, or type-matched near-substitutes. Add a lexical-overlap screen (NoLiMa) for rare-keyword decoys.
Our hardened validator's `no_signal_anywhere` is the existing hook for this.

Tiered padding ladder (recommended):
- **Tier 0** pure-noise length control (UUID/shuffled off-topic) — isolates token count
- **Tier 1** random real-domain decoys, answer-scrubbed — ecological, low-distraction
- **Tier 2** adversarial/hard-negative + own-transcript — separate labeled arm (measures distraction/self-conditioning, a *different* failure mode)

RAG-side noise-ratio templates: RGB benchmark arXiv:2309.01431; Divide-Then-Align arXiv:2505.20871;
unanswerable-RAG arXiv:2510.11956.

---

## 3. Agentic mechanism: self-conditioning (why real-trajectory padding is its own arm)

| Work | ID | Finding |
|---|---|---|
| **Illusion of Diminishing Returns** (Sinha et al., 2025, ICLR 2026) | arXiv:2509.09677 | per-step accuracy *decays as trajectory lengthens* beyond long-context limits; **self-conditioning** — model errs more once its OWN prior errors are in context; not cured by scale; thinking partially escapes. `[120-step/47pt body numbers unverified]` |
| **LLMs Get Lost in Multi-Turn Conversation** (Laban et al., MS/Salesforce, ICLR 2026 best paper) | arXiv:2505.06120 | **avg 39% drop** single→multi-turn; decomposes **aptitude vs unreliability** (drop is mostly unreliability); "sharding" = hold content fixed, vary turn count |
| **Cat: Context as a Tool** (Liu et al., 2025) | arXiv:2512.22087 | ReAct append-only **saturates ~60 rounds then degrades**; compaction keeps improving to 500 rounds @ stable ~35k tok; 57.6% vs 53.2% SWE-bench-Verified |
| **τ-bench** (Yao et al., Sierra, 2024) | arXiv:2406.12045 | **pass^k** metric (all k trials succeed); GPT-4o pass^1 <50%, **pass^8 <25%** retail |
| **τ²-bench** (Barres et al., Sierra, 2025) | arXiv:2506.07982 | dual-control; GPT-4.1 74% retail / 56% air / **34% telecom** |

**Self-conditioning is the threat model for a real pipeline:** the agent's own QC/triage mistakes pollute
its window and accelerate later failure → directly motivates the mitigation arms.

**Mitigation taxonomy** (Anthropic "Effective context engineering," 2025-09-29): compaction; sub-agent
isolation (clean windows, 1–2k-tok distilled returns); structured note-taking/memory; just-in-time retrieval.
Multi-agent research system (Anthropic, 2025-06-13): **+90.2%** vs single-agent but **~15× tokens**.
Counter-thesis — Cognition "Don't Build Multi-Agents" (Walden Yan, 2025-06-12): naive isolation → incoherence;
share full traces. → **Design fork:** isolation likely helps *independent* sub-steps (QC, triage), hurts
*interdependent* ones; biomedical gather→triage→QC→analyze has strong downstream dependence = natural testbed.
MemGPT/Letta (Packer et al., 2023, arXiv:2310.08560) = memory-arm archetype.

---

## 4. Refusal / calibration under load — the novel endpoint

**Metrics to adopt (for direct comparability):**
- **Rabanser et al., "Towards a Science of AI Agent Reliability"** (Princeton, ICML 2026, **arXiv:2602.16666**):
  12 metrics / 4 dims. **Predictability** = `P_cal` (ECE), `P_AUROC` (frac of (success,failure) pairs where
  success has higher confidence), `P_brier` (1 − mean (c−y)²). **Safety** = `S_comp` (frac tasks w/o violations,
  LLM judge), `S_harm` (expected severity 0.25/0.5/1.0). **No refusal/abstention metric, no length sweep.**
  Evaluated only on GAIA + τ-bench — **never on science/biomed.**
- **pass^k** (τ-bench) for reliability; **aptitude/unreliability** decomposition (Laban) — separate "can it
  ever" from "does it every time."
- Verbalized confidence elicitation: "Just Ask for Calibration" (Tian et al., EMNLP 2023, arXiv:2305.14975),
  ~50% rel. ECE reduction. Self-eval P(True)/P(IK): Kadavath et al. (Anthropic, 2022, arXiv:2207.05221) —
  shows **relevant context raises P(IK) appropriately**; nobody tests whether *non-leaking load* moves it wrong.

**Unanswerable-task item sources:** SQuAD 2.0 (Rajpurkar et al., arXiv:1806.03822); (QA)² false-premise
(arXiv:2212.10003); QASPER (arXiv:2105.03011); AbstentionBench (Meta FAIR, NeurIPS 2025, arXiv:2506.09038 —
**reasoning fine-tuning degrades abstention ~24%**: capability can erode refusal); AbstainQA (arXiv:2402.00367);
R-Tuning (NAACL 2024, arXiv:2311.09677). Metric menu: "Art of Refusal" survey (arXiv:2407.18418) — Reliable
Accuracy, Abstain-ECE, Coverage@Accuracy, etc.

**Nearest neighbors to our endpoint (each misses one ingredient):**
- *When Refusals Fail* (arXiv:2512.02445): refusal vs context **1K→200K** — but **safety** refusal of harmful
  requests, no calibration. Refusal is unstable/non-monotone, model-dependent.
- *Sci-QA Context Perturbations* (Wen et al., arXiv:2404.12452): **epistemic** abstention vs context — but
  varies content not length; found noise → MORE abstention (a control to beat, opposite direction).
- *Not All Needles Are Found* (arXiv:2601.02023 `[venue unverified]`): anti-hallucination prompt effectiveness
  erodes 10k→1M — but answerable needles, not genuinely-unanswerable tasks.
- Sibling precedents that behavior drifts with accumulating context: **sycophancy rises** (Jain et al.,
  arXiv:2509.12517); LLMs distracted by irrelevant context (Shi et al., ICML 2023, arXiv:2302.00093).

---

## 5. Positioning / whitespace (scientific-agent benchmark landscape)

| Benchmark | ID/DOI | Reliability axes | Biomed? | Context-load? | Refusal? |
|---|---|---|---|---|---|
| **BiomniBench** (Phylo+Stanford, 2026) | 10.64898/2026.05.12.724604 | process-rubric only | **yes (our base)** | no | no |
| Rabanser framework (Princeton, 2026) | arXiv:2602.16666 | **full (12 metrics)** | **no (GAIA/τ)** | no | no |
| CompBioBench (Genentech, 2026) | 10.64898/2026.04.06.716850 | accuracy only | yes | no | no |
| GeneBench (OpenAI, 2026) | 10.64898/2026.04.22.720113 | multi-run pass rate; error-propagation across "inferential forks" | yes | gestures (no isolation) | no |
| BixBench (FutureHouse, 2025) | arXiv:2503.00096 | accuracy | yes | no | MCQ-refusal? `[unverified]` |
| LAB-Bench (FutureHouse, 2024) | arXiv:2407.10362 | **sure/unsure abstention (precision/coverage)** | yes | no | **yes — but single-turn QA** `[verify wording]` |
| AstaBench (Ai2, 2025) | arXiv:2510.21652 | cost + reproducibility | **defers biomed** (*"deepen coverage…such as biomedicine"*) | no | no |
| ScienceAgentBench (OSU, ICLR 2025) | arXiv:2410.05080 | accuracy/cost | bioinfo slice | no | no |
| CORE-Bench (Princeton, 2024) | arXiv:2409.11363 | reproducibility-of-papers | medicine slice | no | no |

Also: DiscoveryBench arXiv:2407.01725; MLE-bench arXiv:2410.07095; BioPlanner arXiv:2310.10632.

**Whitespace, stated precisely (survey-confirmed):**
1. Rabanser's reliability decomposition has **never been applied to science/biomed** (GAIA + τ-bench only).
2. **AstaBench explicitly defers biomedicine** and only adds cost + reproducibility, not behavioral reliability.
3. Agentic-pipeline **refusal on genuinely-unanswerable tasks** is unmeasured (LAB-Bench abstention is single-turn QA).
4. **Context-load degradation over an accumulating multi-step pipeline** is measured by NO ONE (GeneBench/BiomniBench gesture).
5. **Calibration of biomedical agents** is unmeasured.
6. The "Art of Refusal" survey **explicitly states no work studies abstention as a function of context length.**

**The one-sentence contribution:** *abstention/calibration on genuinely-unanswerable biomedical tasks, as a
function of accumulating non-leaking context* — qualifiers "unanswerable," "non-leaking," "biomedical-agentic"
keep it clear of every nearest neighbor.

---

## Design steer (consensus across all 5 sweeps)

1. **Dose-response curve**, fixed task, x = tokens, y = grade — template: Context Rot + FLenQA.
2. **Tiered padding ladder** (Tier 0 pure-noise control mandatory) — own-transcript is a *labeled arm*, not filler.
3. **Decouple length from position**; log where relevant data lands.
4. **Metrics:** pass^k + aptitude/unreliability; Rabanser P_cal/P_brier/P_AUROC verbatim for comparability.
5. **Two endpoints:** accuracy (answerable) AND refusal/calibration (unanswerable twin) — the second is the novelty.
6. **Mitigation arms:** sub-agent isolation / compaction / retrieval / memory — test whether they flatten the
   curve AND whether they preserve refusal-triggering tokens (compaction lossiness is an open safety risk).
7. **Avoid floor/ceiling:** BixBench ~17%, GeneBench 11–33% — pick mid-difficulty tasks or the effect is invisible.
