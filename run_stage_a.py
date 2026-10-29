#!/usr/bin/env python3
"""
STAGE A Execution Script
(1) Evaluate v4-final, v1-safe, sample_bot on TUNE (1-80) and VALIDATE (81-160)
(2) Self-play: v4-final vs v1-safe on the same map (competing for drops)
(3) Stress variants: stress_1_5 and stress_2_0 on TUNE and VALIDATE for all three bots
"""

import json
import os
import sys
import time

from run_eval import (
    TUNE_SEEDS, VALIDATE_SEEDS,
    evaluate_sweep, evaluate_h2h_sweep,
    summarize_stats, compute_paired_diff,
    format_summary_table, format_paired_table
)

PYTHON = sys.executable
V4_BOT = [PYTHON, "my_bot_v4.py"]
V1_BOT = [PYTHON, "my_bot_v1.py"]
SAMPLE_BOT = [PYTHON, "Subway_Escape/sample_bot/python/basic_bot.py"]
WORKERS = 12

def save_incremental(data):
    with open("stage_a_results.json", "w") as f:
        json.dump(data, f, default=lambda o: str(o), indent=2)


def run_stage_a():
    print("=" * 80)
    print("STAGE A: BENCHMARK EXECUTION (TUNE=1..80, VALIDATE=81..160)")
    print("=" * 80)

    results_data = {}

    # 1. Solo evaluations on standard arena
    for s_name, seeds in [("TUNE", TUNE_SEEDS), ("VALIDATE", VALIDATE_SEEDS)]:
        print(f"\n>>> Part (1): Standard Solo Evaluations on {s_name} (N={len(seeds)}) <<<")
        v4_stats, t_v4 = evaluate_sweep(V4_BOT, seeds, workers=WORKERS, log_dir_prefix=f"practice_logs/a_v4_{s_name.lower()}")
        v1_stats, t_v1 = evaluate_sweep(V1_BOT, seeds, workers=WORKERS, log_dir_prefix=f"practice_logs/a_v1_{s_name.lower()}")
        sm_stats, t_sm = evaluate_sweep(SAMPLE_BOT, seeds, workers=WORKERS, log_dir_prefix=f"practice_logs/a_sm_{s_name.lower()}")

        s_v4 = summarize_stats(v4_stats)
        s_v1 = summarize_stats(v1_stats)
        s_sm = summarize_stats(sm_stats)

        print(format_summary_table(f"v4-final on {s_name}", s_v4, t_v4))
        print(format_summary_table(f"v1-safe on {s_name}", s_v1, t_v1))
        print(format_summary_table(f"sample_bot on {s_name}", s_sm, t_sm))

        p_v4_v1 = compute_paired_diff(v4_stats, v1_stats, seeds)
        p_v4_sm = compute_paired_diff(v4_stats, sm_stats, seeds)
        print("\n" + format_paired_table(f"v4-final vs v1-safe on {s_name}", p_v4_v1))
        print(format_paired_table(f"v4-final vs sample_bot on {s_name}", p_v4_sm))

        results_data[f"solo_{s_name}"] = {
            "v4": s_v4, "v1": s_v1, "sample": s_sm,
            "paired_v4_v1": p_v4_v1, "paired_v4_sm": p_v4_sm
        }
        save_incremental(results_data)
        sys.stdout.flush()

    # 2. Self-play (v4-final vs v1-safe competing on same map)
    for s_name, seeds in [("TUNE", TUNE_SEEDS), ("VALIDATE", VALIDATE_SEEDS)]:
        print(f"\n>>> Part (2): Self-Play (v4-final vs v1-safe competing) on {s_name} <<<")
        h2h_stats, t_h2h = evaluate_h2h_sweep(V4_BOT, V1_BOT, seeds, workers=WORKERS, log_dir_prefix=f"practice_logs/a_h2h_{s_name.lower()}")
        v4_h2h = {s: p[0] for s, p in h2h_stats.items()}
        v1_h2h = {s: p[1] for s, p in h2h_stats.items()}
        s_v4_h2h = summarize_stats(v4_h2h)
        s_v1_h2h = summarize_stats(v1_h2h)
        p_h2h = compute_paired_diff(v4_h2h, v1_h2h, seeds)

        print(format_summary_table(f"v4-final in Self-Play on {s_name}", s_v4_h2h, t_h2h))
        print(format_summary_table(f"v1-safe in Self-Play on {s_name}", s_v1_h2h, t_h2h))
        print(format_paired_table(f"Self-Play (v4-final vs v1-safe) on {s_name}", p_h2h))

        results_data[f"self_play_{s_name}"] = {
            "v4": s_v4_h2h, "v1": s_v1_h2h, "paired": p_h2h
        }
        save_incremental(results_data)
        sys.stdout.flush()

    # 3. Stress variants
    for var_name, mod_name in [("Stress x1.5", "arena_stress_1_5"), ("Stress x2.0", "arena_stress_2_0")]:
        for s_name, seeds in [("TUNE", TUNE_SEEDS), ("VALIDATE", VALIDATE_SEEDS)]:
            print(f"\n>>> Part (3): {var_name} on {s_name} <<<")
            v4_st, t_v4 = evaluate_sweep(V4_BOT, seeds, workers=WORKERS, log_dir_prefix=f"practice_logs/a_st_{mod_name}_{s_name.lower()}", arena_module=mod_name)
            v1_st, t_v1 = evaluate_sweep(V1_BOT, seeds, workers=WORKERS, log_dir_prefix=f"practice_logs/a_st_v1_{mod_name}_{s_name.lower()}", arena_module=mod_name)
            sm_st, t_sm = evaluate_sweep(SAMPLE_BOT, seeds, workers=WORKERS, log_dir_prefix=f"practice_logs/a_st_sm_{mod_name}_{s_name.lower()}", arena_module=mod_name)

            s_v4 = summarize_stats(v4_st)
            s_v1 = summarize_stats(v1_st)
            s_sm = summarize_stats(sm_st)

            print(format_summary_table(f"v4-final on {var_name} {s_name}", s_v4, t_v4))
            print(format_summary_table(f"v1-safe on {var_name} {s_name}", s_v1, t_v1))
            print(format_summary_table(f"sample_bot on {var_name} {s_name}", s_sm, t_sm))

            p_v4_v1 = compute_paired_diff(v4_st, v1_st, seeds)
            print(format_paired_table(f"v4-final vs v1-safe ({var_name} {s_name})", p_v4_v1))

            results_data[f"{mod_name}_{s_name}"] = {
                "v4": s_v4, "v1": s_v1, "sample": s_sm, "paired_v4_v1": p_v4_v1
            }
            save_incremental(results_data)
            sys.stdout.flush()

    with open("stage_a_results.json", "w") as f:
        # Custom serializer for non-serializable elements if any
        json.dump(results_data, f, default=lambda o: str(o), indent=2)

    print("\nStage A Complete! Results saved to stage_a_results.json")


if __name__ == "__main__":
    run_stage_a()
