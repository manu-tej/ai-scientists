#!/usr/bin/env python3
"""Regression tests for grade_bixbench.open_score numeric-verifier robustness.

Each case here corresponds to a real BixBench task where a brittle verifier scored a
CORRECT agent answer as 0 (or where we must NOT over-correct a genuine miss):
  - bix-52-q7  thousands comma   "19159" == "19,159"
  - bix-14-q1  fraction+decimal  "30/41 (0.732)" -> check 0.732, not numerator 30
  - bix-52-q2  scientific notation "1.128e-07" in (1.03E-07, 1.23E-07)
  - bix-27-q5  near-miss MUST stay wrong (56.47% just outside (55,56))
  - bix-54-q7  genuine miss MUST stay wrong (178984 not in (184000,185000))

Run:  python scripts/bixbench/test_verifiers.py      (or: pytest scripts/bixbench/)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # scripts/ on path
import grade_bixbench as G  # noqa: E402

CASES = [
    # (name, eval_mode, ideal, answer, expected)
    ("str_comma",        "str_verifier",   "19,159",                "19159",          True),
    ("str_plain",        "str_verifier",   "3",                     "3",              True),
    ("str_wrong",        "str_verifier",   "3",                     "5",              False),
    ("str_contains",     "str_verifier",   "CDKN1A",                "answer: CDKN1A", True),
    ("range_fraction",   "range_verifier", "(0.7, 0.8)",            "30/41 (0.732)",  True),
    ("range_scinote",    "range_verifier", "(1.03E-07,1.23E-07)",   "1.128e-07",      True),
    ("range_plain",      "range_verifier", "(55,56)",               "55.3",           True),
    ("range_near_miss",  "range_verifier", "(55,56)",               "56.47%",         False),
    ("range_real_miss",  "range_verifier", "(184000,185000)",       "178984",         False),
    ("empty_answer",     "str_verifier",   "3",                     "   ",            None),
]


def test_open_score():
    failures = []
    for name, mode, ideal, ans, exp in CASES:
        got = G.open_score(ans, ideal, mode)
        if got != exp:
            failures.append(f"{name}: open_score({ans!r}, {ideal!r}, {mode}) = {got}, want {exp}")
    assert not failures, "\n".join(failures)


if __name__ == "__main__":
    test_open_score()
    print(f"OK — {len(CASES)} verifier cases pass")
