import os
import sys
import json
import time

PYTHON = sys.executable
TUNE_SEEDS = list(range(241, 301))      # 60 seeds
VAL_SEEDS = list(range(301, 361))       # 60 seeds

from run_eval import evaluate_sweep, compute_paired_diff

def run_stage3():
    t_start = time.perf_counter()
    print("="*60)
    print(f"STAGE 3: 6 Variation Tests on TUNE (Clock: {time.strftime('%H:%M:%S')})")
    print("="*60)

    # 1. Baseline on TUNE
    os.environ.pop("BOT_CONFIG_JSON", None)
    base_stats, t_base = evaluate_sweep([PYTHON, "my_bot.py"], TUNE_SEEDS, workers=14, log_dir_prefix="practice_logs/s3_base")
    base_mean = sum(s.score for s in base_stats.values()) / len(TUNE_SEEDS)
    print(f"v5-final Baseline on TUNE: ${base_mean:,.2f} in {t_base:.1f}s")

    variants = [
        ("Var 1: bank_threshold_min -40 (180.0)", {"bank_threshold_min": 180.0}),
        ("Var 2: bank_threshold_min +40 (260.0)", {"bank_threshold_min": 260.0}),
        ("Var 3: risk_safety_margin -1 (7.0)", {"risk_safety_margin": 7.0}),
        ("Var 4: risk_safety_margin +1 (9.0)", {"risk_safety_margin": 9.0}),
        ("Var 5: chain_max_depth 4 (4)", {"chain_max_depth": 4}),
        ("Var 6a: endgame_margin 3 (3)", {"endgame_margin": 3}),
        ("Var 6b: endgame_margin 5 (5)", {"endgame_margin": 5}),
    ]

    variant_results = []
    for name, cfg in variants:
        t0 = time.perf_counter()
        os.environ["BOT_CONFIG_JSON"] = json.dumps(cfg)
        cand_stats, t_c = evaluate_sweep([PYTHON, "my_bot.py"], TUNE_SEEDS, workers=14, log_dir_prefix=f"practice_logs/s3_var_{len(variant_results)}")
        cand_mean = sum(s.score for s in cand_stats.values()) / len(TUNE_SEEDS)
        p = compute_paired_diff(cand_stats, base_stats, TUNE_SEEDS)
        max_ms = max(s.max_response_ms for s in cand_stats.values())
        captures = sum(s.captures for s in cand_stats.values())
        print(f"{name:38s} | Mean=${cand_mean:9,.2f} | Diff={p['mean_diff']:+7.2f} +/- {p['ci_95']:6.2f} | Wins={p['improved']:2d}/60 | Capt={captures} | MaxMs={max_ms:.1f}ms")
        variant_results.append({
            "name": name,
            "cfg": cfg,
            "mean": cand_mean,
            "diff": p['mean_diff'],
            "ci": p['ci_95'],
            "wins": p['improved'],
            "captures": captures,
            "max_ms": max_ms
        })

    # Pick top 2 variants by positive diff
    positive_vars = [v for v in variant_results if v["diff"] > 0]
    positive_vars.sort(key=lambda x: x["diff"], reverse=True)

    print("\n--- Summary of Positive Variants ---")
    for v in positive_vars:
        print(f"  {v['name']}: Diff=+${v['diff']:.2f}")

    if not positive_vars:
        print("No variant beat v5-final on TUNE. Keeping v5-final config.")
        return False, None

    # Take best 2 variants, combine them
    best2 = positive_vars[:2]
    combined_cfg = {}
    for b in best2:
        combined_cfg.update(b["cfg"])
    print(f"\nCombining top variants: {combined_cfg}")

    # Check on VALIDATE (Seeds 301..360)
    print("\nEvaluating combined config on VALIDATE (301..360)...")
    os.environ.pop("BOT_CONFIG_JSON", None)
    base_val, _ = evaluate_sweep([PYTHON, "my_bot.py"], VAL_SEEDS, workers=14, log_dir_prefix="practice_logs/s3_val_base")
    base_val_mean = sum(s.score for s in base_val.values()) / len(VAL_SEEDS)

    os.environ["BOT_CONFIG_JSON"] = json.dumps(combined_cfg)
    comb_val, _ = evaluate_sweep([PYTHON, "my_bot.py"], VAL_SEEDS, workers=14, log_dir_prefix="practice_logs/s3_val_comb")
    comb_val_mean = sum(s.score for s in comb_val.values()) / len(VAL_SEEDS)
    p_val = compute_paired_diff(comb_val, base_val, VAL_SEEDS)

    print(f"Base VAL Mean:     ${base_val_mean:,.2f}")
    print(f"Combined VAL Mean: ${comb_val_mean:,.2f}")
    print(f"Paired Diff VAL:   +${p_val['mean_diff']:,.2f} +/- ${p_val['ci_95']:,.2f} (Wins: {p_val['improved']}/{p_val['n']})")

    accept = (p_val['mean_diff'] > 0)
    print(f"\nSTAGE 3 DECISION: {'ACCEPT' if accept else 'REVERT'} (Total elapsed: {time.perf_counter()-t_start:.1f}s)")
    if accept:
        with open("stage3_accepted_cfg.json", "w") as f:
            json.dump(combined_cfg, f, indent=2)
    return accept, combined_cfg

if __name__ == "__main__":
    run_stage3()
