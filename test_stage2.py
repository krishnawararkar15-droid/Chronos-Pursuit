import os
import sys
import json
import time

PYTHON = sys.executable
TUNE_SEEDS = list(range(241, 301))      # 60 seeds
VAL_SEEDS = list(range(301, 361))       # 60 seeds

from run_eval import evaluate_sweep, compute_paired_diff

def test_idle_positioning():
    t_start = time.perf_counter()
    print("="*60)
    print(f"STAGE 2: Evaluating Idle Positioning (Clock: {time.strftime('%H:%M:%S')})")
    print("="*60)

    # 1. Baseline on TUNE
    print("1. Running v5-final baseline on TUNE (241..300)...")
    os.environ["BOT_CONFIG_JSON"] = json.dumps({"enable_idle_positioning": False})
    base_tune, t_b_tune = evaluate_sweep([PYTHON, "my_bot.py"], TUNE_SEEDS, workers=14, log_dir_prefix="practice_logs/s2_base_tune")
    base_tune_mean = sum(s.score for s in base_tune.values()) / len(TUNE_SEEDS)
    print(f"Base TUNE Mean: ${base_tune_mean:,.2f} in {t_b_tune:.1f}s")

    # 2. Candidate on TUNE
    print("2. Running Candidate (enable_idle_positioning=True) on TUNE (241..300)...")
    os.environ["BOT_CONFIG_JSON"] = json.dumps({"enable_idle_positioning": True})
    cand_tune, t_c_tune = evaluate_sweep([PYTHON, "my_bot_s2.py"], TUNE_SEEDS, workers=14, log_dir_prefix="practice_logs/s2_cand_tune")
    cand_tune_mean = sum(s.score for s in cand_tune.values()) / len(TUNE_SEEDS)
    p_tune = compute_paired_diff(cand_tune, base_tune, TUNE_SEEDS)
    print(f"Cand TUNE Mean: ${cand_tune_mean:,.2f} in {t_c_tune:.1f}s")
    print(f"Paired Diff TUNE: +${p_tune['mean_diff']:,.2f} +/- ${p_tune['ci_95']:,.2f} (Wins: {p_tune['improved']}/{p_tune['n']})")

    # If TUNE is not positive, don't waste time on VALIDATE
    if p_tune['mean_diff'] <= 0:
        print("TUNE diff not positive -> REVERT STAGE 2 immediately.")
        return False, p_tune, None

    # 3. Baseline and Candidate on VALIDATE
    print("\n3. Running on VALIDATE (301..360)...")
    os.environ["BOT_CONFIG_JSON"] = json.dumps({"enable_idle_positioning": False})
    base_val, _ = evaluate_sweep([PYTHON, "my_bot.py"], VAL_SEEDS, workers=14, log_dir_prefix="practice_logs/s2_base_val")
    os.environ["BOT_CONFIG_JSON"] = json.dumps({"enable_idle_positioning": True})
    cand_val, _ = evaluate_sweep([PYTHON, "my_bot_s2.py"], VAL_SEEDS, workers=14, log_dir_prefix="practice_logs/s2_cand_val")
    
    p_val = compute_paired_diff(cand_val, base_val, VAL_SEEDS)
    cand_val_mean = sum(s.score for s in cand_val.values()) / len(VAL_SEEDS)
    base_val_mean = sum(s.score for s in base_val.values()) / len(VAL_SEEDS)
    print(f"Base VAL Mean: ${base_val_mean:,.2f} | Cand VAL Mean: ${cand_val_mean:,.2f}")
    print(f"Paired Diff VAL: +${p_val['mean_diff']:,.2f} +/- ${p_val['ci_95']:,.2f} (Wins: {p_val['improved']}/{p_val['n']})")

    accept = (p_tune['mean_diff'] > 0 and p_val['mean_diff'] > 0)
    print(f"\nSTAGE 2 DECISION: {'ACCEPT' if accept else 'REVERT'} (Elapsed: {time.perf_counter()-t_start:.1f}s)")
    return accept, p_tune, p_val

if __name__ == "__main__":
    test_idle_positioning()
