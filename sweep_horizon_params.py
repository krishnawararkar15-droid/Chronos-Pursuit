#!/usr/bin/env python3
"""
Parameter sweep for Horizon Planner (Stage C):
Tests H = 25, 40, 60 and B = 20, 30, 40 on Seeds 1..10.
"""
import copy
import json
import os
import sys

from run_eval import evaluate_sweep, compute_paired_diff

PYTHON = sys.executable
V4_BOT = [PYTHON, "my_bot_v4.py"]
SEEDS = list(range(1, 11))

def run_param_sweep():
    print(f"Running parameter sweep on Seeds 1..{len(SEEDS)}...")
    v4_stats, t_v4 = evaluate_sweep(V4_BOT, SEEDS, workers=10, log_dir_prefix="practice_logs/sweep_v4")
    v4_mean = sum(s.score for s in v4_stats.values()) / len(SEEDS)
    print(f"v4-final baseline mean: ${v4_mean:,.1f}")

    configs = [
        {"horizon_ticks": 25, "horizon_beam_width": 20},
        {"horizon_ticks": 40, "horizon_beam_width": 30},
        {"horizon_ticks": 60, "horizon_beam_width": 40},
    ]

    for cfg in configs:
        h = cfg["horizon_ticks"]
        b = cfg["horizon_beam_width"]
        print(f"\n--- Testing H={h}, B={b} ---")
        os.environ["BOT_CONFIG_JSON"] = json.dumps(cfg)
        cand_cmd = [PYTHON, "my_bot_v5_candidate.py"]
        cand_stats, t_cand = evaluate_sweep(cand_cmd, SEEDS, workers=10, log_dir_prefix=f"practice_logs/sweep_h{h}_b{b}")
        cand_mean = sum(s.score for s in cand_stats.values()) / len(SEEDS)
        paired = compute_paired_diff(cand_stats, v4_stats, SEEDS)
        print(f"H={h}, B={b}: Mean=${cand_mean:,.1f} | Paired Diff vs v4: +${paired['mean_diff']:,.1f} +/- ${paired['ci_95']:,.1f} (Wins: {paired['improved']}/{paired['n']})")

if __name__ == "__main__":
    run_param_sweep()
