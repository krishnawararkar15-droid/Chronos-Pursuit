import os
import sys
import json
import numpy as np

PYTHON = sys.executable
FINAL_SEEDS = list(range(361, 421))      # 60 seeds

from run_eval import evaluate_sweep, evaluate_h2h_sweep, compute_paired_diff

def run_stage4():
    print("="*60)
    print("STAGE 4: FINAL EVALUATION ON SEEDS 361-420 (N=60)")
    print("="*60)

    # 1. Solo evaluation of v5-final on FINAL seeds 361-420
    print("\n1. Running v5-final on FINAL seeds 361..420 (solo mode)...")
    os.environ.pop("BOT_CONFIG_JSON", None)
    v5_stats, t_v5 = evaluate_sweep([PYTHON, "my_bot.py"], FINAL_SEEDS, workers=14, log_dir_prefix="practice_logs/s4_final_solo")

    scores = [v5_stats[s].score for s in FINAL_SEEDS]
    mean_score = float(np.mean(scores))
    median_score = float(np.median(scores))
    std_score = float(np.std(scores, ddof=1))
    ci_95 = 1.96 * std_score / np.sqrt(len(scores))
    captures = sum(v5_stats[s].captures for s in FINAL_SEEDS)
    bad_acts = sum(v5_stats[s].invalid_actions for s in FINAL_SEEDS)
    misses = sum(v5_stats[s].misses for s in FINAL_SEEDS)
    max_ms = max(v5_stats[s].max_response_ms for s in FINAL_SEEDS)

    print("\n--- FINAL SOLO EVALUATION (SEEDS 361-420) ---")
    print(f"Mean Score:   ${mean_score:,.2f} +/- ${ci_95:,.2f} (95% CI: [{mean_score-ci_95:,.2f}, {mean_score+ci_95:,.2f}])")
    print(f"Median Score: ${median_score:,.2f}")
    print(f"Captures:     {captures} ({captures/len(FINAL_SEEDS):.2f}/match)")
    print(f"BadActs:      {bad_acts}")
    print(f"Misses:       {misses}")
    print(f"MaxMs:        {max_ms:.1f}ms")

    # 2. Head-to-Head evaluation on the same map (Seeds 361-420)
    print("\n2. Running Head-to-Head on FINAL seeds 361..420 (same map)...")
    h2h_results, t_h2h = evaluate_h2h_sweep(
        [PYTHON, "my_bot.py"],
        [PYTHON, "my_bot.py"],
        FINAL_SEEDS,
        workers=14,
        log_dir_prefix="practice_logs/s4_final_h2h"
    )
    b1_scores = [h2h_results[s][0].score for s in FINAL_SEEDS]
    b2_scores = [h2h_results[s][1].score for s in FINAL_SEEDS]
    print(f"H2H Completed in {t_h2h:.1f}s.")
    print(f"Bot 1 Mean: ${np.mean(b1_scores):,.2f} | Bot 2 Mean: ${np.mean(b2_scores):,.2f}")

    results = {
        "mean_score": mean_score,
        "median_score": median_score,
        "ci_95": ci_95,
        "captures": captures,
        "bad_acts": bad_acts,
        "misses": misses,
        "max_ms": max_ms
    }
    with open("stage4_final_results.json", "w") as f:
        json.dump(results, f, indent=2)

if __name__ == "__main__":
    run_stage4()
