# BixBench-Verified-50 — results

Canonical grade artifacts for the 3-agent capability+consistency run (2026-06-05).
Full write-up: [`docs/research/2026-06-05-bixbench-verified-50-results.md`](../../docs/research/2026-06-05-bixbench-verified-50-results.md).

## Full-50 (verifier-fixed, MiniMax-M3 judge, k=3)

| Agent | open | MCQ | consistency |
|---|---|---|---|
| cc (Opus 4.7) | **0.847** | 0.927 | 0.979 |
| agy (Gemini 3.1 Pro) | 0.827 | 0.907 | **0.986** |
| codex (gpt-5.5) | 0.796 | 0.927 | 0.972 |

Hard-35 only: cc 0.828 > agy 0.790 > codex 0.735. (Easy-15 subset inverted this: codex 0.933 > agy 0.911 > cc 0.889.)

## Files

```
full50_summary.json     per-agent full-50 means + all-agents-fail list
hard35_summary.json     per-agent hard-35 means + all-agents-fail list
grades/
  subset15_<agent>.json   15 easy tasks, comma-fixed grader   (open_acc/mcq_acc/open_agree per task)
  full35_<agent>.json     35 hard tasks, verifier-fixed grader
```

Agents: `claude-code` = cc, `codex`, `antigravity-cli` = agy.

Regenerate the summaries from the per-task grades:

```bash
python scripts/bixbench/merge_grades.py \
  --agent cc    results/bixbench/grades/subset15_claude-code.json results/bixbench/grades/full35_claude-code.json \
  --agent codex results/bixbench/grades/subset15_codex.json       results/bixbench/grades/full35_codex.json \
  --agent agy   results/bixbench/grades/subset15_antigravity-cli.json results/bixbench/grades/full35_antigravity-cli.json \
  --out results/bixbench/full50_summary.json
```
