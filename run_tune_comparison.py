import os
import sys
import json
from run_eval import evaluate_sweep, compute_paired_diff

PYTHON = sys.executable
TUNE_SEEDS = list(range(1, 81))

def main():
    print(f"Running paired evaluation of my_bot_v5.py vs my_bot_v4.py on TUNE (Seeds 1..{len(TUNE_SEEDS)})...")
    v4_stats, t_v4 = evaluate_sweep([PYTHON, "my_bot_v4.py"], TUNE_SEEDS, workers=12, log_dir_prefix="practice_logs/tune_v4")
    print(f"v4 evaluation completed in {t_v4:.1f}s")
    
    v5_stats, t_v5 = evaluate_sweep([PYTHON, "my_bot_v5.py"], TUNE_SEEDS, workers=12, log_dir_prefix="practice_logs/tune_v5")
    print(f"v5 evaluation completed in {t_v5:.1f}s")

    paired = compute_paired_diff(v5_stats, v4_stats, TUNE_SEEDS)
    v4_mean = sum(s.score for s in v4_stats.values()) / len(TUNE_SEEDS)
    v5_mean = sum(s.score for s in v5_stats.values()) / len(TUNE_SEEDS)

    v4_captures = sum(s.captures for s in v4_stats.values())
    v5_captures = sum(s.captures for s in v5_stats.values())

    v4_bad = sum(s.invalid_actions for s in v4_stats.values())
    v5_bad = sum(s.invalid_actions for s in v5_stats.values())

    v4_max_ms = max(s.max_response_ms for s in v4_stats.values())
    v5_max_ms = max(s.max_response_ms for s in v5_stats.values())

    print("\n" + "="*60)
    print("STAGE C & D RESULTS ON TUNE (Seeds 1..80):")
    print(f"v4-final Mean:   ${v4_mean:,.2f} | Captures: {v4_captures} | BadActs: {v4_bad} | MaxMs: {v4_max_ms:.1f}ms")
    print(f"v5 Mean:         ${v5_mean:,.2f} | Captures: {v5_captures} | BadActs: {v5_bad} | MaxMs: {v5_max_ms:.1f}ms")
    print(f"Paired Diff:     +${paired['mean_diff']:,.2f} +/- ${paired['ci_95']:,.2f} (95% CI: [{paired['ci_lower']:,.2f}, {paired['ci_upper']:,.2f}])")
    print(f"Wins / Total:    {paired['improved']} / {paired['n']} ({paired['improved']/paired['n']*100:.1f}%)")
    print("="*60)

    # Save results to json
    res = {
        "v4_mean": v4_mean,
        "v5_mean": v5_mean,
        "paired": paired,
        "v4_captures": v4_captures,
        "v5_captures": v5_captures,
        "v4_bad": v4_bad,
        "v5_bad": v5_bad,
        "v4_max_ms": v4_max_ms,
        "v5_max_ms": v5_max_ms,
    }
    with open("tune_v5_vs_v4_results.json", "w") as f:
        json.dump(res, f, indent=2)

if __name__ == "__main__":
    main()
