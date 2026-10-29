import os
import sys
import json
from run_eval import evaluate_sweep, compute_paired_diff

PYTHON = sys.executable
TUNE_SEEDS = list(range(1, 81))

def main():
    print("Testing clean tuning directly on my_bot_v4.py on Seeds 1..80...")
    # Baseline
    os.environ.pop("BOT_CONFIG_JSON", None)
    v4_stats, t_v4 = evaluate_sweep([PYTHON, "my_bot_v4.py"], TUNE_SEEDS, workers=12, log_dir_prefix="practice_logs/clean_v4")
    v4_mean = sum(s.score for s in v4_stats.values()) / len(TUNE_SEEDS)
    print(f"v4 baseline mean: ${v4_mean:,.2f}")

    configs = [
        # Tuning 1: Candidate 5 parameters
        (
            "Tune 1: Candidate 5 (bank_min=250, bank_max=480, cutoff=500)",
            {"bank_threshold_min": 250.0, "bank_threshold_max": 480.0, "chain_capacity_cutoff": 500.0}
        ),
        # Tuning 2: Higher chain depth 4
        (
            "Tune 2: Chaining depth 4 (chain_max_depth=4, chain_capacity_cutoff=500)",
            {"chain_max_depth": 4, "chain_capacity_cutoff": 500.0}
        ),
        # Tuning 3: Fine-tuned banking min 220, max 450
        (
            "Tune 3: bank_min=220, bank_max=450, dynamic_bank_coef=3.5",
            {"bank_threshold_min": 220.0, "bank_threshold_max": 450.0, "dynamic_bank_coef": 3.5}
        ),
        # Tuning 4: Endgame margin 3 vs 4
        (
            "Tune 4: endgame_margin=3",
            {"endgame_margin": 3}
        ),
    ]

    for name, cfg in configs:
        print(f"\n--- {name} ---")
        os.environ["BOT_CONFIG_JSON"] = json.dumps(cfg)
        stats, t_el = evaluate_sweep([PYTHON, "my_bot_v4.py"], TUNE_SEEDS, workers=12, log_dir_prefix="practice_logs/clean_tune")
        mean_score = sum(s.score for s in stats.values()) / len(TUNE_SEEDS)
        captures = sum(s.captures for s in stats.values())
        bad_acts = sum(s.invalid_actions for s in stats.values())
        max_ms = max(s.max_response_ms for s in stats.values())
        paired = compute_paired_diff(stats, v4_stats, TUNE_SEEDS)
        
        print(f"Mean Score:   ${mean_score:,.2f} (Time: {t_el:.1f}s)")
        print(f"Captures:     {captures} | BadActs: {bad_acts} | MaxMs: {max_ms:.1f}ms")
        print(f"Paired Diff:  +${paired['mean_diff']:,.2f} +/- ${paired['ci_95']:,.2f} [{paired['ci_lower']:,.2f}, {paired['ci_upper']:,.2f}]")
        print(f"Wins / Total: {paired['improved']} / {paired['n']} ({paired['improved']/paired['n']*100:.1f}%)")

if __name__ == "__main__":
    main()
