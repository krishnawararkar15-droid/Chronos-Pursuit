#!/usr/bin/env python3
"""
Test tuning of bank thresholds and chaining parameters on Seeds 1..20.
"""
import copy
import json
import os
import sys

from run_eval import evaluate_sweep, compute_paired_diff

PYTHON = sys.executable
V4_BOT = [PYTHON, "my_bot_v4.py"]
SEEDS = list(range(1, 21))

def test_banking_params():
    print(f"Evaluating v4-final baseline on Seeds 1..{len(SEEDS)}...")
    v4_stats, _ = evaluate_sweep(V4_BOT, SEEDS, workers=10, log_dir_prefix="practice_logs/tune_v4")
    v4_mean = sum(s.score for s in v4_stats.values()) / len(SEEDS)
    print(f"v4-final baseline mean: ${v4_mean:,.1f}")

    candidates = [
        {"bank_threshold_min": 250.0, "bank_threshold_max": 480.0, "dynamic_bank_coef": 4.0},
        {"bank_threshold_min": 300.0, "bank_threshold_max": 500.0, "dynamic_bank_coef": 5.0},
        {"bank_threshold_min": 350.0, "bank_threshold_max": 500.0, "dynamic_bank_coef": 6.0},
        {"chain_capacity_cutoff": 500.0, "chain_max_depth": 4},
        {"bank_threshold_min": 250.0, "bank_threshold_max": 480.0, "chain_capacity_cutoff": 500.0},
    ]

    for i, cfg in enumerate(candidates, 1):
        print(f"\n--- Testing Candidate {i}: {cfg} ---")
        os.environ["BOT_CONFIG_JSON"] = json.dumps(cfg)
        c_stats, _ = evaluate_sweep(V4_BOT, SEEDS, workers=10, log_dir_prefix=f"practice_logs/tune_c{i}")
        c_mean = sum(s.score for s in c_stats.values()) / len(SEEDS)
        paired = compute_paired_diff(c_stats, v4_stats, SEEDS)
        print(f"Candidate {i}: Mean=${c_mean:,.1f} | Paired Diff: +${paired['mean_diff']:,.1f} +/- ${paired['ci_95']:,.1f} (Wins: {paired['improved']}/{paired['n']})")

if __name__ == "__main__":
    test_banking_params()
