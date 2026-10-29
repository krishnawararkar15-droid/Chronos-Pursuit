import os
import sys
import json
from run_eval import evaluate_sweep, compute_paired_diff

PYTHON = sys.executable
TUNE_SEEDS = list(range(1, 81))

def main():
    print("Loading baseline v4 stats...")
    v4_stats, _ = evaluate_sweep([PYTHON, "my_bot_v4.py"], TUNE_SEEDS, workers=12, log_dir_prefix="practice_logs/abl_v4")
    v4_mean = sum(s.score for s in v4_stats.values()) / len(TUNE_SEEDS)
    print(f"v4 baseline mean: ${v4_mean:,.2f}")

    experiments = [
        # Exp 1: Disable horizon planner, test only safety fix + v4 chaining + v4 config
        (
            "Exp 1: Pure v4 chaining + Safety fix (endgame_margin=4, bank_min=180)",
            {"enable_horizon_planner": False, "endgame_margin": 4, "bank_threshold_min": 180.0, "bank_threshold_max": 420.0, "chain_capacity_cutoff": 450.0}
        ),
        # Exp 2: Disable horizon planner, test safety fix + Candidate 5 tuned banking
        (
            "Exp 2: Pure v4 chaining + Safety fix + Tuned banking (bank_min=250, bank_max=480, cutoff=500, margin=4)",
            {"enable_horizon_planner": False, "endgame_margin": 4, "bank_threshold_min": 250.0, "bank_threshold_max": 480.0, "chain_capacity_cutoff": 500.0}
        ),
        # Exp 3: Horizon planner with H=25, B=20, endgame_margin=4
        (
            "Exp 3: Horizon planner (H=25, B=20) + margin=4 + bank_min=180",
            {"enable_horizon_planner": True, "horizon_ticks": 25, "horizon_beam_width": 20, "endgame_margin": 4, "bank_threshold_min": 180.0, "bank_threshold_max": 420.0, "chain_capacity_cutoff": 450.0}
        ),
        # Exp 4: Horizon planner with H=25, B=20, tuned banking
        (
            "Exp 4: Horizon planner (H=25, B=20) + margin=4 + Tuned banking (bank_min=250, cutoff=500)",
            {"enable_horizon_planner": True, "horizon_ticks": 25, "horizon_beam_width": 20, "endgame_margin": 4, "bank_threshold_min": 250.0, "bank_threshold_max": 480.0, "chain_capacity_cutoff": 500.0}
        ),
    ]

    results = []
    for name, cfg in experiments:
        print(f"\n--- Running {name} ---")
        os.environ["BOT_CONFIG_JSON"] = json.dumps(cfg)
        stats, t_el = evaluate_sweep([PYTHON, "my_bot_v5.py"], TUNE_SEEDS, workers=12, log_dir_prefix=f"practice_logs/abl_{len(results)}")
        mean_score = sum(s.score for s in stats.values()) / len(TUNE_SEEDS)
        captures = sum(s.captures for s in stats.values())
        bad_acts = sum(s.invalid_actions for s in stats.values())
        max_ms = max(s.max_response_ms for s in stats.values())
        paired = compute_paired_diff(stats, v4_stats, TUNE_SEEDS)
        
        print(f"Mean Score:   ${mean_score:,.2f} (Time: {t_el:.1f}s)")
        print(f"Captures:     {captures} | BadActs: {bad_acts} | MaxMs: {max_ms:.1f}ms")
        print(f"Paired Diff:  +${paired['mean_diff']:,.2f} +/- ${paired['ci_95']:,.2f} [{paired['ci_lower']:,.2f}, {paired['ci_upper']:,.2f}]")
        print(f"Wins / Total: {paired['improved']} / {paired['n']} ({paired['improved']/paired['n']*100:.1f}%)")

        results.append({
            "name": name,
            "cfg": cfg,
            "mean": mean_score,
            "captures": captures,
            "bad_acts": bad_acts,
            "max_ms": max_ms,
            "paired": paired
        })

    with open("ablation_results.json", "w") as f:
        json.dump(results, f, indent=2)

if __name__ == "__main__":
    main()
