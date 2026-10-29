#!/usr/bin/env python3
"""
Test Candidate A: v4-final + exact endgame + safety fix
"""
import json
import os
import sys

from run_eval import evaluate_sweep, compute_paired_diff

PYTHON = sys.executable
V4_BOT = [PYTHON, "my_bot_v4.py"]
SEEDS = list(range(1, 11))

def test_cand_a():
    # Read my_bot_v4.py
    with open("my_bot_v4.py", "r", encoding="utf-8") as f:
        code = f.read()

    # Exact endgame: change endgame_margin to 1
    code = code.replace('"endgame_margin": 4', '"endgame_margin": 1')

    # Safety fix: hit_here_now < 0.35
    old_col = '            if here in drops_by_node and carrying < capacity:'
    new_col = '            hit_here_now = risk_model.point_hit_risk(world.nodes[here].x, world.nodes[here].y, 1)\n            if here in drops_by_node and carrying < capacity and hit_here_now < 0.35:'
    code = code.replace(old_col, new_col)

    with open("my_bot_cand_a.py", "w", encoding="utf-8") as f:
        f.write(code)

    print("Running Candidate A on Seeds 1..10...")
    v4_stats, _ = evaluate_sweep(V4_BOT, SEEDS, workers=10, log_dir_prefix="practice_logs/trace_v4")
    a_stats, _ = evaluate_sweep([PYTHON, "my_bot_cand_a.py"], SEEDS, workers=10, log_dir_prefix="practice_logs/trace_a")

    paired = compute_paired_diff(a_stats, v4_stats, SEEDS)
    v4_mean = sum(s.score for s in v4_stats.values()) / len(SEEDS)
    a_mean = sum(s.score for s in a_stats.values()) / len(SEEDS)
    print(f"v4 Mean: ${v4_mean:,.1f}")
    print(f"Candidate A Mean: ${a_mean:,.1f}")
    print(f"Paired Diff: +${paired['mean_diff']:,.1f} +/- ${paired['ci_95']:,.1f} (Wins: {paired['improved']}/{paired['n']})")

if __name__ == "__main__":
    test_cand_a()
