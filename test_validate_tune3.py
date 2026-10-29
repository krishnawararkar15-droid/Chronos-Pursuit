import os
import sys
import json
from run_eval import evaluate_sweep, compute_paired_diff

PYTHON = sys.executable
VAL_SEEDS = list(range(81, 161))

def main():
    print("Testing Tune 3 on VALIDATE (Seeds 81..160)...")
    # Baseline v4
    os.environ.pop("BOT_CONFIG_JSON", None)
    v4_stats, t_v4 = evaluate_sweep([PYTHON, "my_bot_v4.py"], VAL_SEEDS, workers=12, log_dir_prefix="practice_logs/val_v4")
    v4_mean = sum(s.score for s in v4_stats.values()) / len(VAL_SEEDS)
    print(f"v4 baseline mean on VALIDATE: ${v4_mean:,.2f}")

    cfg_tune3 = {"bank_threshold_min": 220.0, "bank_threshold_max": 450.0, "dynamic_bank_coef": 3.5}
    os.environ["BOT_CONFIG_JSON"] = json.dumps(cfg_tune3)
    t3_stats, t_t3 = evaluate_sweep([PYTHON, "my_bot_v4.py"], VAL_SEEDS, workers=12, log_dir_prefix="practice_logs/val_tune3")
    t3_mean = sum(s.score for s in t3_stats.values()) / len(VAL_SEEDS)

    v4_captures = sum(s.captures for s in v4_stats.values())
    t3_captures = sum(s.captures for s in t3_stats.values())

    v4_bad = sum(s.invalid_actions for s in v4_stats.values())
    t3_bad = sum(s.invalid_actions for s in t3_stats.values())

    paired = compute_paired_diff(t3_stats, v4_stats, VAL_SEEDS)

    print("\n" + "="*60)
    print("TUNE 3 RESULTS ON VALIDATE (Seeds 81..160):")
    print(f"v4-final Mean:   ${v4_mean:,.2f} | Captures: {v4_captures} | BadActs: {v4_bad}")
    print(f"Tune 3 Mean:     ${t3_mean:,.2f} | Captures: {t3_captures} | BadActs: {t3_bad}")
    print(f"Paired Diff:     +${paired['mean_diff']:,.2f} +/- ${paired['ci_95']:,.2f} [{paired['ci_lower']:,.2f}, {paired['ci_upper']:,.2f}]")
    print(f"Wins / Total:    {paired['improved']} / {paired['n']} ({paired['improved']/paired['n']*100:.1f}%)")
    print("="*60)

    # Save to json
    res = {
        "v4_mean": v4_mean,
        "t3_mean": t3_mean,
        "v4_captures": v4_captures,
        "t3_captures": t3_captures,
        "paired": paired
    }
    with open("validate_tune3_results.json", "w") as f:
        json.dump(res, f, indent=2)

if __name__ == "__main__":
    main()
