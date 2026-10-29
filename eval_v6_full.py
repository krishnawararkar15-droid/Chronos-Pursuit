import os
import sys
import json
from run_eval import evaluate_sweep, compute_paired_diff

PYTHON = sys.executable
TUNE_SEEDS = list(range(1, 81))
VAL_SEEDS = list(range(81, 161))

def run_suite():
    print("="*60)
    print("RUNNING FULL EVALUATION: my_bot_v6.py vs my_bot_v4.py")
    print("="*60)

    # 1. TUNE
    print("\n--- Evaluating on TUNE (Seeds 1..80) ---")
    v4_tune, _ = evaluate_sweep([PYTHON, "my_bot_v4.py"], TUNE_SEEDS, workers=12, log_dir_prefix="practice_logs/v6_tune_v4")
    v6_tune, _ = evaluate_sweep([PYTHON, "my_bot_v6.py"], TUNE_SEEDS, workers=12, log_dir_prefix="practice_logs/v6_tune_v6")
    p_tune = compute_paired_diff(v6_tune, v4_tune, TUNE_SEEDS)

    v4_tune_mean = sum(s.score for s in v4_tune.values()) / len(TUNE_SEEDS)
    v6_tune_mean = sum(s.score for s in v6_tune.values()) / len(TUNE_SEEDS)
    v4_tune_capt = sum(s.captures for s in v4_tune.values())
    v6_tune_capt = sum(s.captures for s in v6_tune.values())
    v4_tune_bad = sum(s.invalid_actions for s in v4_tune.values())
    v6_tune_bad = sum(s.invalid_actions for s in v6_tune.values())
    v4_tune_ms = max(s.max_response_ms for s in v4_tune.values())
    v6_tune_ms = max(s.max_response_ms for s in v6_tune.values())

    print(f"TUNE v4-final: Mean=${v4_tune_mean:,.2f} | Captures={v4_tune_capt} | BadActs={v4_tune_bad} | MaxMs={v4_tune_ms:.1f}ms")
    print(f"TUNE v6-final: Mean=${v6_tune_mean:,.2f} | Captures={v6_tune_capt} | BadActs={v6_tune_bad} | MaxMs={v6_tune_ms:.1f}ms")
    print(f"TUNE Paired:   +${p_tune['mean_diff']:,.2f} +/- ${p_tune['ci_95']:,.2f} (95% CI: [{p_tune['ci_lower']:,.2f}, {p_tune['ci_upper']:,.2f}])")
    print(f"TUNE Wins:     {p_tune['improved']}/{p_tune['n']} ({p_tune['improved']/p_tune['n']*100:.1f}%)")

    # 2. VALIDATE
    print("\n--- Evaluating on VALIDATE (Seeds 81..160) ---")
    v4_val, _ = evaluate_sweep([PYTHON, "my_bot_v4.py"], VAL_SEEDS, workers=12, log_dir_prefix="practice_logs/v6_val_v4")
    v6_val, _ = evaluate_sweep([PYTHON, "my_bot_v6.py"], VAL_SEEDS, workers=12, log_dir_prefix="practice_logs/v6_val_v6")
    p_val = compute_paired_diff(v6_val, v4_val, VAL_SEEDS)

    v4_val_mean = sum(s.score for s in v4_val.values()) / len(VAL_SEEDS)
    v6_val_mean = sum(s.score for s in v6_val.values()) / len(VAL_SEEDS)
    v4_val_capt = sum(s.captures for s in v4_val.values())
    v6_val_capt = sum(s.captures for s in v6_val.values())
    v4_val_bad = sum(s.invalid_actions for s in v4_val.values())
    v6_val_bad = sum(s.invalid_actions for s in v6_val.values())
    v4_val_ms = max(s.max_response_ms for s in v4_val.values())
    v6_val_ms = max(s.max_response_ms for s in v6_val.values())

    print(f"VAL v4-final:  Mean=${v4_val_mean:,.2f} | Captures={v4_val_capt} | BadActs={v4_val_bad} | MaxMs={v4_val_ms:.1f}ms")
    print(f"VAL v6-final:  Mean=${v6_val_mean:,.2f} | Captures={v6_val_capt} | BadActs={v6_val_bad} | MaxMs={v6_val_ms:.1f}ms")
    print(f"VAL Paired:    +${p_val['mean_diff']:,.2f} +/- ${p_val['ci_95']:,.2f} (95% CI: [{p_val['ci_lower']:,.2f}, {p_val['ci_upper']:,.2f}])")
    print(f"VAL Wins:      {p_val['improved']}/{p_val['n']} ({p_val['improved']/p_val['n']*100:.1f}%)")

    # Combine results
    all_res = {
        "tune": {
            "v4_mean": v4_tune_mean, "v6_mean": v6_tune_mean,
            "v4_captures": v4_tune_capt, "v6_captures": v6_tune_capt,
            "v4_bad": v4_tune_bad, "v6_bad": v6_tune_bad,
            "v4_max_ms": v4_tune_ms, "v6_max_ms": v6_tune_ms,
            "paired": p_tune
        },
        "val": {
            "v4_mean": v4_val_mean, "v6_mean": v6_val_mean,
            "v4_captures": v4_val_capt, "v6_captures": v6_val_capt,
            "v4_bad": v4_val_bad, "v6_bad": v6_val_bad,
            "v4_max_ms": v4_val_ms, "v6_max_ms": v6_val_ms,
            "paired": p_val
        }
    }
    with open("full_tune_val_results.json", "w") as f:
        json.dump(all_res, f, indent=2)

if __name__ == "__main__":
    run_suite()
