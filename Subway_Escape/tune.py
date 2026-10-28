#!/usr/bin/env python3
"""
Parameter Tuning and Optimization Harness for Phase 8:
Conducts randomized parameter search across candidate CONFIG spaces.
Evaluates candidates using the official PracticeArena over train seeds and tests on held-out seeds.
Ranks candidates via robust fitness: mean - 0.5 * std (maximizing score while minimizing variance).
Freezes the winning config into submission/my_bot.py and my_bot.py.
"""

import concurrent.futures
import json
import math
import os
import random
import re
import statistics
import sys
import time
from typing import Any, Dict, List, Tuple

ARENA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "practice_arena"))
if ARENA_DIR not in sys.path:
    sys.path.insert(0, ARENA_DIR)

from practice_arena import PracticeArena, TOTAL_TICKS


def run_candidate_match(args: Tuple[int, str, Dict[str, Any], int]) -> Tuple[int, float, int, float]:
    seed, bot_path, config_overrides, ticks = args
    # Use environment variable to pass config overrides to the bot process
    env = os.environ.copy()
    env["SUBWAY_CONFIG_OVERRIDE"] = json.dumps(config_overrides)

    # Launch arena with the bot command
    arena = PracticeArena([[sys.executable, bot_path]], seed=seed, ticks=ticks, verbose=False, log_dir="practice_logs")
    # Set env on process
    for cmd in arena.commands.values():
        pass
    stats = arena.run()
    bot_stat = stats[1]
    return seed, bot_stat.score, bot_stat.captures, bot_stat.loot_lost


def evaluate_config(
    bot_path: str,
    config: Dict[str, Any],
    seeds: List[int],
    workers: int = 4,
) -> Dict[str, float]:
    tasks = [(s, bot_path, config, TOTAL_TICKS) for s in seeds]
    scores = []
    captures = []
    loot_lost = []

    # Run in parallel
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(workers, len(seeds))) as executor:
        for seed, score, cap, lost in executor.map(run_candidate_match, tasks):
            scores.append(score)
            captures.append(cap)
            loot_lost.append(lost)

    mean_s = statistics.mean(scores)
    std_s = statistics.stdev(scores) if len(scores) > 1 else 0.0
    fitness = mean_s - 0.5 * std_s

    return {
        "mean_score": mean_s,
        "median_score": statistics.median(scores),
        "std_score": std_s,
        "fitness": fitness,
        "mean_captures": statistics.mean(captures),
        "mean_loot_lost": statistics.mean(loot_lost),
    }


def generate_candidate_configs(num_candidates: int = 6) -> List[Dict[str, Any]]:
    rng = random.Random(2026)
    candidates = []

    # Baseline configuration as Candidate 0
    candidates.append({
        "bank_threshold_min": 180.0,
        "bank_threshold_max": 420.0,
        "risk_lookahead_H": 15,
        "risk_safety_margin": 8.0,
        "risk_penalty_weight": 6.0,
        "switch_gain": 0.15,
        "endgame_margin": 4,
        "safehouse_congestion_pen": 2.0,
    })

    # Sample randomized variations
    for _ in range(num_candidates - 1):
        cand = {
            "bank_threshold_min": round(rng.uniform(160.0, 210.0), 1),
            "bank_threshold_max": round(rng.uniform(390.0, 460.0), 1),
            "risk_lookahead_H": rng.choice([12, 14, 15, 16]),
            "risk_safety_margin": round(rng.uniform(7.0, 10.0), 1),
            "risk_penalty_weight": round(rng.uniform(5.0, 7.5), 1),
            "switch_gain": round(rng.uniform(0.12, 0.20), 2),
            "endgame_margin": rng.choice([3, 4, 5]),
            "safehouse_congestion_pen": round(rng.uniform(1.5, 2.5), 1),
        }
        candidates.append(cand)

    return candidates


def update_bot_config(file_path: str, best_config: Dict[str, Any]) -> None:
    """Updates the CONFIG dictionary in the bot file."""
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Format new config dictionary string
    new_cfg_lines = ["CONFIG: Dict[str, Any] = {"]
    new_cfg_lines.append('    "total_ticks": 300,')
    new_cfg_lines.append('    "tick_budget_s": 0.35,')
    new_cfg_lines.append('    "debug_log_ticks": 5,')
    new_cfg_lines.append('    "debug_log_path": "debug.log",')
    new_cfg_lines.append('    "log_timing": False,')
    new_cfg_lines.append(f'    "risk_lookahead_H": {best_config["risk_lookahead_H"]},')
    new_cfg_lines.append(f'    "risk_safety_margin": {best_config["risk_safety_margin"]},')
    new_cfg_lines.append(f'    "risk_penalty_weight": {best_config["risk_penalty_weight"]},')
    new_cfg_lines.append('    "avg_income_per_tick": 70.0,')
    new_cfg_lines.append(f'    "bank_threshold_min": {best_config["bank_threshold_min"]},')
    new_cfg_lines.append(f'    "bank_threshold_max": {best_config["bank_threshold_max"]},')
    new_cfg_lines.append('    "opportunistic_bank_dist": 1,')
    new_cfg_lines.append('    "min_opportunistic_loot": 50.0,')
    new_cfg_lines.append(f'    "switch_gain": {best_config["switch_gain"]},')
    new_cfg_lines.append(f'    "endgame_margin": {best_config["endgame_margin"]},')
    new_cfg_lines.append(f'    "safehouse_congestion_pen": {best_config["safehouse_congestion_pen"]},')
    new_cfg_lines.append("}")
    new_cfg_str = "\n".join(new_cfg_lines)

    # Regex replace CONFIG dict
    pattern = r"CONFIG:\s*Dict\[str,\s*Any\]\s*=\s*\{.*?\}"
    updated_content = re.sub(pattern, new_cfg_str, content, flags=re.DOTALL)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(updated_content)


def main():
    bot_path = "submission/my_bot.py"
    train_seeds = list(range(1, 11))      # Seeds 1..10
    val_seeds = list(range(11, 21))       # Held-out Seeds 11..20

    print("=====================================================================")
    print("PHASE 8: HYPERPARAMETER TUNING & ROBUSTNESS SWEEP")
    print(f"Train Seeds: {train_seeds}")
    print(f"Validation (Held-Out) Seeds: {val_seeds}")
    print("=====================================================================")

    candidates = generate_candidate_configs(num_candidates=5)

    best_fitness = -1e9
    best_candidate = None
    best_val_stats = None

    for idx, cand in enumerate(candidates):
        print(f"\n--- Testing Candidate {idx+1}/{len(candidates)} on Training Seeds ---")
        print(f"Config: {json.dumps(cand, indent=2)}")

        # Temporary write config to bot
        update_bot_config(bot_path, cand)

        train_res = evaluate_config(bot_path, cand, train_seeds, workers=4)
        print(f"Train Result: Mean=${train_res['mean_score']:,.0f} | Std=${train_res['std_score']:,.0f} | Fitness={train_res['fitness']:,.0f} | Captures={train_res['mean_captures']:.2f}")

        # Evaluate on validation held-out seeds
        val_res = evaluate_config(bot_path, cand, val_seeds, workers=4)
        print(f"Validation Result: Mean=${val_res['mean_score']:,.0f} | Std=${val_res['std_score']:,.0f} | Fitness={val_res['fitness']:,.0f} | Captures={val_res['mean_captures']:.2f}")

        if val_res["fitness"] > best_fitness:
            best_fitness = val_res["fitness"]
            best_candidate = cand
            best_val_stats = val_res
            print(">>> NEW BEST CANDIDATE FOUND! <<<")

    print("\n=====================================================================")
    print("TUNING COMPLETE — BEST ROBUST CONFIGURATION")
    print("=====================================================================")
    print(f"Best Config:\n{json.dumps(best_candidate, indent=2)}")
    print(f"Held-out Validation Score: ${best_val_stats['mean_score']:,.0f} (Fitness: {best_val_stats['fitness']:,.0f})")

    # Freeze best candidate into bot files
    update_bot_config("submission/my_bot.py", best_candidate)
    update_bot_config("../my_bot.py", best_candidate)
    print("Successfully froze best configuration into submission/my_bot.py and my_bot.py.")


if __name__ == "__main__":
    main()
