import os
import sys
import json
from run_eval import evaluate_sweep, compute_paired_diff

PYTHON = sys.executable
TUNE_SEEDS = list(range(1, 81))
VAL_SEEDS = list(range(81, 161))

def run_stress():
    print("="*60)
    print("STAGE F: EVALUATION ON STRESS VARIANTS (1.5x and 2.0x)")
    print("="*60)

    # 1. Stress 1.5 on TUNE
    print("\n--- Stress 1.5 on TUNE (Seeds 1..80) ---")
    s15_tune, t_s15_tune = evaluate_sweep(
        [PYTHON, "my_bot_v6.py"], TUNE_SEEDS, workers=12,
        log_dir_prefix="practice_logs/v6_s15_tune", arena_module="arena_stress_1_5"
    )
    s15_tune_mean = sum(s.score for s in s15_tune.values()) / len(TUNE_SEEDS)
    s15_tune_capt = sum(s.captures for s in s15_tune.values())
    s15_tune_bad = sum(s.invalid_actions for s in s15_tune.values())
    s15_tune_ms = max(s.max_response_ms for s in s15_tune.values())
    print(f"Stress 1.5 TUNE: Mean=${s15_tune_mean:,.2f} | Captures={s15_tune_capt} | BadActs={s15_tune_bad} | MaxMs={s15_tune_ms:.1f}ms")

    # 2. Stress 1.5 on VALIDATE
    print("\n--- Stress 1.5 on VALIDATE (Seeds 81..160) ---")
    s15_val, t_s15_val = evaluate_sweep(
        [PYTHON, "my_bot_v6.py"], VAL_SEEDS, workers=12,
        log_dir_prefix="practice_logs/v6_s15_val", arena_module="arena_stress_1_5"
    )
    s15_val_mean = sum(s.score for s in s15_val.values()) / len(VAL_SEEDS)
    s15_val_capt = sum(s.captures for s in s15_val.values())
    s15_val_bad = sum(s.invalid_actions for s in s15_val.values())
    s15_val_ms = max(s.max_response_ms for s in s15_val.values())
    print(f"Stress 1.5 VALIDATE: Mean=${s15_val_mean:,.2f} | Captures={s15_val_capt} | BadActs={s15_val_bad} | MaxMs={s15_val_ms:.1f}ms")

    # 3. Stress 2.0 on TUNE
    print("\n--- Stress 2.0 on TUNE (Seeds 1..80) ---")
    s20_tune, t_s20_tune = evaluate_sweep(
        [PYTHON, "my_bot_v6.py"], TUNE_SEEDS, workers=12,
        log_dir_prefix="practice_logs/v6_s20_tune", arena_module="arena_stress_2_0"
    )
    s20_tune_mean = sum(s.score for s in s20_tune.values()) / len(TUNE_SEEDS)
    s20_tune_capt = sum(s.captures for s in s20_tune.values())
    s20_tune_bad = sum(s.invalid_actions for s in s20_tune.values())
    s20_tune_ms = max(s.max_response_ms for s in s20_tune.values())
    print(f"Stress 2.0 TUNE: Mean=${s20_tune_mean:,.2f} | Captures={s20_tune_capt} | BadActs={s20_tune_bad} | MaxMs={s20_tune_ms:.1f}ms")

    # 4. Stress 2.0 on VALIDATE
    print("\n--- Stress 2.0 on VALIDATE (Seeds 81..160) ---")
    s20_val, t_s20_val = evaluate_sweep(
        [PYTHON, "my_bot_v6.py"], VAL_SEEDS, workers=12,
        log_dir_prefix="practice_logs/v6_s20_val", arena_module="arena_stress_2_0"
    )
    s20_val_mean = sum(s.score for s in s20_val.values()) / len(VAL_SEEDS)
    s20_val_capt = sum(s.captures for s in s20_val.values())
    s20_val_bad = sum(s.invalid_actions for s in s20_val.values())
    s20_val_ms = max(s.max_response_ms for s in s20_val.values())
    print(f"Stress 2.0 VALIDATE: Mean=${s20_val_mean:,.2f} | Captures={s20_val_capt} | BadActs={s20_val_bad} | MaxMs={s20_val_ms:.1f}ms")

    stress_res = {
        "s15_tune": {"mean": s15_tune_mean, "captures": s15_tune_capt, "bad_acts": s15_tune_bad, "max_ms": s15_tune_ms},
        "s15_val": {"mean": s15_val_mean, "captures": s15_val_capt, "bad_acts": s15_val_bad, "max_ms": s15_val_ms},
        "s20_tune": {"mean": s20_tune_mean, "captures": s20_tune_capt, "bad_acts": s20_tune_bad, "max_ms": s20_tune_ms},
        "s20_val": {"mean": s20_val_mean, "captures": s20_val_capt, "bad_acts": s20_val_bad, "max_ms": s20_val_ms},
    }
    with open("stage_f_stress_results.json", "w") as f:
        json.dump(stress_res, f, indent=2)

if __name__ == "__main__":
    run_stress()
