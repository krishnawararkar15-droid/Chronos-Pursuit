#!/usr/bin/env python3
"""
Parallel Evaluation Harness for Subway Escape Bots
Supports:
  - TUNE (seeds 1-80)
  - VALIDATE (seeds 81-160)
  - FINAL (seeds 161-240)
  - Paired per-seed differences with 95% CI
  - Solo mode and Head-to-Head mode
  - Time per sweep reporting
  - Integrity metrics: Caught, LootLost, BadActs, Misses, MaxMs
"""

import argparse
import concurrent.futures
import csv
import json
import math
import os
import statistics
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
KIT_DIR = os.path.join(WORKSPACE_DIR, "Subway_Escape")
if os.path.join(KIT_DIR, "practice_arena") not in sys.path:
    sys.path.insert(0, os.path.join(KIT_DIR, "practice_arena"))

from practice_arena import PracticeArena, BotStats, TOTAL_TICKS

TUNE_SEEDS = list(range(1, 81))
VALIDATE_SEEDS = list(range(81, 161))
FINAL_SEEDS = list(range(161, 241))


def run_match_instance(args: Tuple[int, List[List[str]], int, str, str]) -> Tuple[int, Dict[int, BotStats]]:
    seed, commands, ticks, log_dir, arena_module_name = args
    if arena_module_name == "practice_arena":
        from practice_arena import PracticeArena as ArenaCls
    else:
        import importlib
        mod = importlib.import_module(arena_module_name)
        ArenaCls = getattr(mod, "PracticeArena")

    arena = ArenaCls(commands, seed=seed, ticks=ticks, verbose=False, log_dir=log_dir)
    stats = arena.run()
    return seed, stats


def evaluate_sweep(
    bot_cmd: List[str],
    seeds: List[int],
    ticks: int = TOTAL_TICKS,
    workers: int = 8,
    log_dir_prefix: str = "practice_logs/eval",
    arena_module: str = "practice_arena",
) -> Tuple[Dict[int, BotStats], float]:
    """Run bot solo across seeds in parallel."""
    tasks = [
        (seed, [bot_cmd], ticks, f"{log_dir_prefix}_{seed}", arena_module)
        for seed in seeds
    ]
    t0 = time.time()
    results: Dict[int, BotStats] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        for seed, stat_dict in executor.map(run_match_instance, tasks):
            results[seed] = stat_dict[1]
    elapsed = time.time() - t0
    return results, elapsed


def evaluate_h2h_sweep(
    bot1_cmd: List[str],
    bot2_cmd: List[str],
    seeds: List[int],
    ticks: int = TOTAL_TICKS,
    workers: int = 8,
    log_dir_prefix: str = "practice_logs/h2h",
    arena_module: str = "practice_arena",
) -> Tuple[Dict[int, Tuple[BotStats, BotStats]], float]:
    """Run two bots head-to-head competing on the same map across seeds in parallel."""
    tasks = [
        (seed, [bot1_cmd, bot2_cmd], ticks, f"{log_dir_prefix}_{seed}", arena_module)
        for seed in seeds
    ]
    t0 = time.time()
    results: Dict[int, Tuple[BotStats, BotStats]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        for seed, stat_dict in executor.map(run_match_instance, tasks):
            results[seed] = (stat_dict[1], stat_dict[2])
    elapsed = time.time() - t0
    return results, elapsed


def summarize_stats(stats_dict: Dict[int, BotStats]) -> Dict[str, Any]:
    scores = [s.score for s in stats_dict.values()]
    collections = [s.collections for s in stats_dict.values()]
    deposits = [s.deposits for s in stats_dict.values()]
    caught = [s.captures for s in stats_dict.values()]
    loot_lost = [s.loot_lost for s in stats_dict.values()]
    bad_acts = [s.invalid_actions for s in stats_dict.values()]
    misses = [s.misses for s in stats_dict.values()]
    max_ms = [s.max_response_ms for s in stats_dict.values()]
    avg_ms = [s.total_response_ms / max(1, s.answered_ticks) for s in stats_dict.values()]
    n = len(scores)

    return {
        "n": n,
        "mean_score": statistics.mean(scores),
        "median_score": statistics.median(scores),
        "std_score": statistics.stdev(scores) if n > 1 else 0.0,
        "min_score": min(scores),
        "max_score": max(scores),
        "mean_collections": statistics.mean(collections),
        "mean_deposits": statistics.mean(deposits),
        "mean_caught": statistics.mean(caught),
        "total_caught": sum(caught),
        "mean_loot_lost": statistics.mean(loot_lost),
        "total_bad_acts": sum(bad_acts),
        "total_misses": sum(misses),
        "avg_ms": statistics.mean(avg_ms),
        "peak_max_ms": max(max_ms) if max_ms else 0.0,
    }


def compute_paired_diff(
    new_stats: Dict[int, BotStats],
    baseline_stats: Dict[int, BotStats],
    seeds: List[int],
) -> Dict[str, Any]:
    diffs = [new_stats[s].score - baseline_stats[s].score for s in seeds]
    n = len(diffs)
    mean_diff = statistics.mean(diffs)
    median_diff = statistics.median(diffs)
    std_diff = statistics.stdev(diffs) if n > 1 else 0.0
    se = std_diff / math.sqrt(n) if n > 1 else 0.0
    ci_95 = 1.96 * se
    improved = sum(1 for d in diffs if d > 0)
    worsened = sum(1 for d in diffs if d < 0)
    tied = sum(1 for d in diffs if d == 0)

    return {
        "n": n,
        "mean_diff": mean_diff,
        "median_diff": median_diff,
        "std_diff": std_diff,
        "ci_95": ci_95,
        "ci_lower": mean_diff - ci_95,
        "ci_upper": mean_diff + ci_95,
        "improved": improved,
        "worsened": worsened,
        "tied": tied,
        "diffs": diffs,
    }


def format_summary_table(label: str, s: Dict[str, Any], elapsed: Optional[float] = None) -> str:
    t_str = f" in {elapsed:.1f}s" if elapsed is not None else ""
    lines = [
        f"--- {label}{t_str} (N={s['n']}) ---",
        f"Score: Mean=${s['mean_score']:,.1f} | Median=${s['median_score']:,.1f} | Min=${s['min_score']:,.1f} | Max=${s['max_score']:,.1f} | Std=${s['std_score']:,.1f}",
        f"Ops:   Collections={s['mean_collections']:.1f} | Deposits={s['mean_deposits']:.1f}",
        f"Safe:  Caught={s['mean_caught']:.2f} (Tot={s['total_caught']}) | LootLost=${s['mean_loot_lost']:,.1f} | BadActs={s['total_bad_acts']} | Misses={s['total_misses']}",
        f"Time:  AvgMs={s['avg_ms']:.1f}ms | PeakMaxMs={s['peak_max_ms']:.0f}ms",
    ]
    return "\n".join(lines)


def format_paired_table(label: str, p: Dict[str, Any]) -> str:
    sign = "+" if p["mean_diff"] >= 0 else ""
    return (
        f"Paired Diff ({label}): {sign}${p['mean_diff']:,.1f} ± ${p['ci_95']:,.1f} "
        f"[95% CI: ${p['ci_lower']:,.1f} to ${p['ci_upper']:,.1f}] | "
        f"Median: {sign}${p['median_diff']:,.1f} | "
        f"Win/Loss/Tie: {p['improved']}/{p['worsened']}/{p['tied']} "
        f"({p['improved']/p['n']*100:.1f}% wins)"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate bots on TUNE/VALIDATE/FINAL")
    parser.add_argument("--bot", default="my_bot_v4.py", help="Path to bot script")
    parser.add_argument("--baseline", default="my_bot_v1.py", help="Path to baseline bot for paired diff")
    parser.add_argument("--set", choices=["tune", "validate", "both", "final"], default="tune")
    parser.add_argument("--workers", type=int, default=8, help="Number of parallel workers")
    parser.add_argument("--mode", choices=["solo", "h2h"], default="solo")
    parser.add_argument("--opponent", default="Subway_Escape/sample_bot/python/basic_bot.py")
    args = parser.parse_args()

    python_exe = sys.executable
    bot_cmd = [python_exe, args.bot]

    if args.set == "tune":
        seeds = TUNE_SEEDS
    elif args.set == "validate":
        seeds = VALIDATE_SEEDS
    elif args.set == "final":
        seeds = FINAL_SEEDS
    else:
        seeds = TUNE_SEEDS + VALIDATE_SEEDS

    print(f"Running evaluation on {len(seeds)} seeds ({args.set.upper()}) with {args.workers} workers...")
    stats, elapsed = evaluate_sweep(bot_cmd, seeds, workers=args.workers)
    summ = summarize_stats(stats)
    print(format_summary_table(f"{args.bot} on {args.set.upper()}", summ, elapsed))
