# Results compendium — biomedical-agent trust evaluation

All evaluation results in one place. Two benchmarks, three frontier agents
(cc = Claude Opus 4.7, codex = gpt-5.5, agy = Gemini 3.1 Pro), graded by neutral judges with
3 replicates. The through-line: **static accuracy can't tell these agents apart or tell you
which to trust — the trust dimensions can.**

## The two benchmarks

| | [BiomniBench-DA](biomnibench/) | [BixBench-Verified-50](bixbench/) |
|---|---|---|
| Tasks | 50 data-analysis | 50 (15 easy + 35 hard) |
| Capability (best judge) | cc 0.806 > codex 0.737 > agy 0.494 | cc 0.847 > agy 0.827 > codex 0.796 |
| Consistency leader | codex (SD 0.002) | agy (agree 0.986) |
| Judge | MiniMax-M3 + Gemini | MiniMax-M3 |

## Cross-cutting findings (the actual contribution)

1. **Static accuracy can't separate frontier agents.** On BixBench the paired-difference 95%
   CIs all cross zero (cc−agy differ on 4 of 48 tasks). The agents are statistically tied; the
   "ranking" is point-estimate theater.

2. **Capability ≠ consistency.** The accuracy leader and the reliability leader differ on
   *both* benchmarks (BiomniBench: cc capable / codex steady; BixBench: cc capable / agy
   steady). "Best agent" depends on which axis you weight.

3. **The judge changes the answer.** On BiomniBench the cc-vs-codex ranking flips between the
   Gemini and MiniMax judges. LLM-as-judge numbers are judge-dependent and (when an agent
   judges itself) circular — see [the eval-design research](../docs/research/2026-06-05-scientific-eval-design-deep-research.md).

4. **Refusal collapse.** On sabotaged-data tasks (correct answer = "unanswerable"), agents gave
   **zero appropriate refusals** — every response fabricated or partially hedged (codex
   fabricates 56%, cc 40%). Accuracy benchmarks never test this and it is the sharpest failure.

5. **When agents fail, they fail together.** On BixBench's all-fail tasks the agents agree
   *with each other* on a defensible reading the answer key rejects (bix-54-q7 monoculture
   anchors; bix-16-q1 DepMap sign convention — both proven by reproduction). Per-agent
   consistency is blind to this correlated cross-agent failure.

6. **Verifiers are a false-negative source.** Three grader bugs (thousands-comma,
   scientific-notation, fraction-numerator) scored *correct* answers as 0 until fixed —
   automated numeric verifiers systematically under-score.

## Layout

```
results/
├── README.md                  # this compendium
├── biomnibench/               # BiomniBench-DA: capability + consistency + refusal
│   ├── README.md  summary.json
│   ├── grades/    biomni_<agent>_<judge>.json
│   └── refusal/   refusal_classifications.json, refusal_consolidated.json
└── bixbench/                  # BixBench-Verified-50: full-50 + hard-35, verifier-fixed
    ├── README.md  full50_summary.json  hard35_summary.json
    └── grades/    {subset15,full35}_<agent>.json
```

See [`docs/research/`](../docs/research/) for the writeups: BixBench results, the eval-design
deep research, and [the taking-stock plan](../docs/research/2026-06-07-taking-stock-quration-validation-demo.md)
(how these results become quration's real validation, replacing its circular LLM-judge number).
