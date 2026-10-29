#!/usr/bin/env python3
import json
import os
import sys

from run_eval import (
    TUNE_SEEDS, VALIDATE_SEEDS,
    evaluate_sweep, summarize_stats, compute_paired_diff,
    format_summary_table, format_paired_table
)

PYTHON = sys.executable
V4_BOT = [PYTHON, "my_bot_v4.py"]
V1_BOT = [PYTHON, "my_bot_v1.py"]
SAMPLE_BOT = [PYTHON, "Subway_Escape/sample_bot/python/basic_bot.py"]
WORKERS = 12

with open("stage_a_results.json") as f:
    results_data = json.load(f)

for s_name, seeds in [("TUNE", TUNE_SEEDS), ("VALIDATE", VALIDATE_SEEDS)]:
    k = f"arena_stress_2_0_{s_name}"
    if k in results_data:
        print(f"[SKIP] {k} already done.")
        continue
    print(f"\n>>> Running Stress x2.0 on {s_name} (N={len(seeds)}) <<<")
    v4_st, t_v4 = evaluate_sweep(V4_BOT, seeds, workers=WORKERS, log_dir_prefix=f"practice_logs/a_st_arena_stress_2_0_{s_name.lower()}", arena_module="arena_stress_2_0")
    v1_st, t_v1 = evaluate_sweep(V1_BOT, seeds, workers=WORKERS, log_dir_prefix=f"practice_logs/a_st_v1_arena_stress_2_0_{s_name.lower()}", arena_module="arena_stress_2_0")
    sm_st, t_sm = evaluate_sweep(SAMPLE_BOT, seeds, workers=WORKERS, log_dir_prefix=f"practice_logs/a_st_sm_arena_stress_2_0_{s_name.lower()}", arena_module="arena_stress_2_0")

    s_v4 = summarize_stats(v4_st)
    s_v1 = summarize_stats(v1_st)
    s_sm = summarize_stats(sm_st)

    print(format_summary_table(f"v4-final on Stress x2.0 {s_name}", s_v4, t_v4))
    print(format_summary_table(f"v1-safe on Stress x2.0 {s_name}", s_v1, t_v1))
    print(format_summary_table(f"sample_bot on Stress x2.0 {s_name}", s_sm, t_sm))

    p_v4_v1 = compute_paired_diff(v4_st, v1_st, seeds)
    print(format_paired_table(f"v4-final vs v1-safe (Stress x2.0 {s_name})", p_v4_v1))

    results_data[k] = {
        "v4": s_v4, "v1": s_v1, "sample": s_sm, "paired_v4_v1": p_v4_v1
    }
    with open("stage_a_results.json", "w") as f:
        json.dump(results_data, f, default=lambda o: str(o), indent=2)

print("\nStage A finished!")
