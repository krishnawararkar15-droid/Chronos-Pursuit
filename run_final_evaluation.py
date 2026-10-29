import os
import sys
import json
import numpy as np
from run_eval import evaluate_sweep, compute_paired_diff

PYTHON = sys.executable
FINAL_SEEDS = list(range(161, 241))

SAMPLE_BOT = [PYTHON, os.path.join("Subway_Escape", "bots", "sample_bot.py")]
V4_BOT = [PYTHON, "my_bot_v4.py"]
VNEW_BOT = [PYTHON, "my_bot_v6.py"]

def run_final():
    print("="*70)
    print("FINAL EVALUATION ON UNSEEN TEST SET: SEEDS 161-240 (N=80)")
    print("="*70)

    # Ensure clean environment
    os.environ.pop("BOT_CONFIG_JSON", None)

    # 1. Run v-new (my_bot_v6.py)
    print("\n[1/3] Running v-new (my_bot_v6.py) on FINAL seeds 161..240...")
    vnew_stats, t_vnew = evaluate_sweep(VNEW_BOT, FINAL_SEEDS, workers=12, log_dir_prefix="practice_logs/final_vnew")
    print(f"v-new completed in {t_vnew:.1f}s")

    # 2. Run v4-final (my_bot_v4.py)
    print("\n[2/3] Running v4-final (my_bot_v4.py) on FINAL seeds 161..240...")
    v4_stats, t_v4 = evaluate_sweep(V4_BOT, FINAL_SEEDS, workers=12, log_dir_prefix="practice_logs/final_v4")
    print(f"v4-final completed in {t_v4:.1f}s")

    # 3. Run sample_bot
    print("\n[3/3] Running sample_bot on FINAL seeds 161..240...")
    sample_stats, t_sample = evaluate_sweep(SAMPLE_BOT, FINAL_SEEDS, workers=12, log_dir_prefix="practice_logs/final_sample")
    print(f"sample_bot completed in {t_sample:.1f}s")

    # Helper stats
    def calc_stats(stats_dict):
        scores = [stats_dict[s].score for s in FINAL_SEEDS]
        captures = sum(stats_dict[s].captures for s in FINAL_SEEDS)
        bad_acts = sum(stats_dict[s].invalid_actions for s in FINAL_SEEDS)
        max_ms = max(stats_dict[s].max_response_ms for s in FINAL_SEEDS)
        return {
            "mean": float(np.mean(scores)),
            "median": float(np.median(scores)),
            "std": float(np.std(scores, ddof=1)),
            "captures": captures,
            "bad_acts": bad_acts,
            "max_ms": max_ms
        }

    s_vnew = calc_stats(vnew_stats)
    s_v4 = calc_stats(v4_stats)
    s_sample = calc_stats(sample_stats)

    # Paired diffs
    p_vnew_vs_v4 = compute_paired_diff(vnew_stats, v4_stats, FINAL_SEEDS)
    p_vnew_vs_sample = compute_paired_diff(vnew_stats, sample_stats, FINAL_SEEDS)
    p_v4_vs_sample = compute_paired_diff(v4_stats, sample_stats, FINAL_SEEDS)

    print("\n" + "="*70)
    print("FINAL SUMMARY RESULTS (SEEDS 161-240):")
    print("="*70)
    print(f"v-new:      Mean=${s_vnew['mean']:,.2f} | Med=${s_vnew['median']:,.2f} | Capt={s_vnew['captures']} | BadActs={s_vnew['bad_acts']} | MaxMs={s_vnew['max_ms']:.1f}ms")
    print(f"v4-final:   Mean=${s_v4['mean']:,.2f} | Med=${s_v4['median']:,.2f} | Capt={s_v4['captures']} | BadActs={s_v4['bad_acts']} | MaxMs={s_v4['max_ms']:.1f}ms")
    print(f"sample_bot: Mean=${s_sample['mean']:,.2f} | Med=${s_sample['median']:,.2f} | Capt={s_sample['captures']} | BadActs={s_sample['bad_acts']} | MaxMs={s_sample['max_ms']:.1f}ms")
    print("-"*70)
    print(f"Paired Diff (v-new vs v4-final):")
    print(f"  +${p_vnew_vs_v4['mean_diff']:,.2f} +/- ${p_vnew_vs_v4['ci_95']:,.2f} (95% CI: [{p_vnew_vs_v4['ci_lower']:,.2f}, {p_vnew_vs_v4['ci_upper']:,.2f}])")
    print(f"  Wins: {p_vnew_vs_v4['improved']}/{p_vnew_vs_v4['n']} ({p_vnew_vs_v4['improved']/p_vnew_vs_v4['n']*100:.1f}%)")
    print("-"*70)
    print(f"Paired Diff (v-new vs sample_bot):")
    print(f"  +${p_vnew_vs_sample['mean_diff']:,.2f} +/- ${p_vnew_vs_sample['ci_95']:,.2f} (95% CI: [{p_vnew_vs_sample['ci_lower']:,.2f}, {p_vnew_vs_sample['ci_upper']:,.2f}])")
    print(f"  Wins: {p_vnew_vs_sample['improved']}/{p_vnew_vs_sample['n']} ({p_vnew_vs_sample['improved']/p_vnew_vs_sample['n']*100:.1f}%)")
    print("="*70)

    # Full data dump
    final_output = {
        "vnew": s_vnew,
        "v4": s_v4,
        "sample": s_sample,
        "paired_vnew_vs_v4": p_vnew_vs_v4,
        "paired_vnew_vs_sample": p_vnew_vs_sample,
        "paired_v4_vs_sample": p_v4_vs_sample,
        "scores": {
            s: {
                "vnew": vnew_stats[s].score,
                "v4": v4_stats[s].score,
                "sample": sample_stats[s].score
            }
            for s in FINAL_SEEDS
        }
    }
    with open("final_evaluation_results.json", "w") as f:
        json.dump(final_output, f, indent=2)

if __name__ == "__main__":
    run_final()
