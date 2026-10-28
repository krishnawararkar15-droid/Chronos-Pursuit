#!/usr/bin/env python3
"""
Subway Escape - Automated Evaluation & Benchmark Harness
Evaluates our bot vs. sample_bot vs. do-nothing baseline across maps/seeds.
Computes Mean, Median, Min, Max, Captures, LootLost, BadActs, Misses, and Latency.
Supports parallel map execution for rapid high-seed sweeps.
"""

import argparse
import concurrent.futures
import json
import math
import os
import statistics
import sys
import time
from typing import Any, Dict, List, Tuple

# Ensure practice_arena is importable
ARENA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "practice_arena"))
if ARENA_DIR not in sys.path:
    sys.path.insert(0, ARENA_DIR)

from practice_arena import BotStats, PracticeArena, TOTAL_TICKS


def run_single_match(args_tuple: Tuple[int, List[List[str]], int, str]) -> Tuple[int, Dict[int, BotStats]]:
    seed, commands, ticks, log_dir = args_tuple
    arena = PracticeArena(commands, seed=seed, ticks=ticks, verbose=False, log_dir=log_dir)
    stats = arena.run()
    return seed, stats


def evaluate_bots(
    bot_configs: List[Tuple[str, List[str]]],
    runs: int = 10,
    start_seed: int = 1,
    ticks: int = TOTAL_TICKS,
    parallel: bool = True,
    workers: int = 4,
    log_dir: str = "practice_logs",
    mode: str = "solo",  # "solo" (each bot alone on each seed) or "head_to_head" (competing on same seed)
) -> Dict[str, Dict[str, Any]]:
    os.makedirs(log_dir, exist_ok=True)
    summary_results: Dict[str, Dict[str, Any]] = {}

    if mode == "solo":
        for label, cmd in bot_configs:
            print(f"\nEvaluating '{label}' solo across {runs} seeds (seeds {start_seed}..{start_seed + runs - 1})...")
            tasks = [(start_seed + i, [cmd], ticks, log_dir) for i in range(runs)]

            match_stats: List[BotStats] = []
            t_start = time.perf_counter()

            if parallel and runs > 1:
                with concurrent.futures.ThreadPoolExecutor(max_workers=min(workers, runs)) as executor:
                    for seed, st_dict in executor.map(run_single_match, tasks):
                        match_stats.append(st_dict[1])
            else:
                for task in tasks:
                    _, st_dict = run_single_match(task)
                    match_stats.append(st_dict[1])

            elapsed_eval = time.perf_counter() - t_start
            scores = [s.score for s in match_stats]
            captures = [s.captures for s in match_stats]
            loot_lost = [s.loot_lost for s in match_stats]
            bad_acts = [s.invalid_actions for s in match_stats]
            misses = [s.misses for s in match_stats]
            collections = [s.collections for s in match_stats]
            deposits = [s.deposits for s in match_stats]
            latencies = [s.total_response_ms / max(1, s.answered_ticks) for s in match_stats]
            max_latencies = [s.max_response_ms for s in match_stats]

            summary_results[label] = {
                "runs": runs,
                "elapsed_eval_s": elapsed_eval,
                "mean_score": statistics.mean(scores),
                "median_score": statistics.median(scores),
                "min_score": min(scores),
                "max_score": max(scores),
                "std_score": statistics.stdev(scores) if len(scores) > 1 else 0.0,
                "mean_collections": statistics.mean(collections),
                "mean_deposits": statistics.mean(deposits),
                "total_captures": sum(captures),
                "mean_captures": statistics.mean(captures),
                "total_loot_lost": sum(loot_lost),
                "mean_loot_lost": statistics.mean(loot_lost),
                "total_bad_acts": sum(bad_acts),
                "mean_bad_acts": statistics.mean(bad_acts),
                "total_misses": sum(misses),
                "mean_misses": statistics.mean(misses),
                "avg_ms": statistics.mean(latencies),
                "peak_ms": max(max_latencies),
            }

    else:  # head_to_head: all bots in the same match
        print(f"\nEvaluating head-to-head competition across {runs} seeds (seeds {start_seed}..{start_seed + runs - 1})...")
        commands = [cmd for _, cmd in bot_configs]
        tasks = [(start_seed + i, commands, ticks, log_dir) for i in range(runs)]

        h2h_stats: Dict[int, List[BotStats]] = {idx + 1: [] for idx in range(len(bot_configs))}
        t_start = time.perf_counter()

        if parallel and runs > 1:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(workers, runs)) as executor:
                for seed, st_dict in executor.map(run_single_match, tasks):
                    for b_id, st in st_dict.items():
                        h2h_stats[b_id].append(st)
        else:
            for task in tasks:
                _, st_dict = run_single_match(task)
                for b_id, st in st_dict.items():
                    h2h_stats[b_id].append(st)

        elapsed_eval = time.perf_counter() - t_start

        for idx, (label, _) in enumerate(bot_configs):
            match_stats = h2h_stats[idx + 1]
            scores = [s.score for s in match_stats]
            captures = [s.captures for s in match_stats]
            loot_lost = [s.loot_lost for s in match_stats]
            bad_acts = [s.invalid_actions for s in match_stats]
            misses = [s.misses for s in match_stats]
            collections = [s.collections for s in match_stats]
            deposits = [s.deposits for s in match_stats]
            latencies = [s.total_response_ms / max(1, s.answered_ticks) for s in match_stats]
            max_latencies = [s.max_response_ms for s in match_stats]

            summary_results[label] = {
                "runs": runs,
                "elapsed_eval_s": elapsed_eval,
                "mean_score": statistics.mean(scores),
                "median_score": statistics.median(scores),
                "min_score": min(scores),
                "max_score": max(scores),
                "std_score": statistics.stdev(scores) if len(scores) > 1 else 0.0,
                "mean_collections": statistics.mean(collections),
                "mean_deposits": statistics.mean(deposits),
                "total_captures": sum(captures),
                "mean_captures": statistics.mean(captures),
                "total_loot_lost": sum(loot_lost),
                "mean_loot_lost": statistics.mean(loot_lost),
                "total_bad_acts": sum(bad_acts),
                "mean_bad_acts": statistics.mean(bad_acts),
                "total_misses": sum(misses),
                "mean_misses": statistics.mean(misses),
                "avg_ms": statistics.mean(latencies),
                "peak_ms": max(max_latencies),
            }

    return summary_results


def print_comparison_table(results: Dict[str, Dict[str, Any]]) -> None:
    headers = [
        "Bot Name",
        "Mean $",
        "Median $",
        "Min $",
        "Max $",
        "StdDev",
        "Captures",
        "LootLost",
        "BadActs",
        "Misses",
        "AvgMs",
        "MaxMs",
    ]

    rows = []
    for name, r in results.items():
        rows.append([
            name,
            f"{r['mean_score']:,.0f}",
            f"{r['median_score']:,.0f}",
            f"{r['min_score']:,.0f}",
            f"{r['max_score']:,.0f}",
            f"{r['std_score']:,.0f}",
            f"{r['mean_captures']:.2f}",
            f"${r['mean_loot_lost']:,.0f}",
            f"{r['mean_bad_acts']:.2f}",
            f"{r['mean_misses']:.2f}",
            f"{r['avg_ms']:.1f}",
            f"{r['peak_ms']:.0f}",
        ])

    col_widths = [max(len(headers[i]), max(len(row[i]) for row in rows)) for i in range(len(headers))]

    print("\n" + "=" * (sum(col_widths) + 3 * len(headers)))
    print("SUBWAY ESCAPE — COMPREHENSIVE BENCHMARK TABLE")
    print("=" * (sum(col_widths) + 3 * len(headers)))

    hdr_str = " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    sep_str = "-+-".join("-" * col_widths[i] for i in range(len(headers)))
    print(hdr_str)
    print(sep_str)

    for row in rows:
        row_str = " | ".join(row[i].ljust(col_widths[i]) for i in range(len(headers)))
        print(row_str)

    print("=" * (sum(col_widths) + 3 * len(headers)) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Subway Escape Benchmark Harness")
    parser.add_argument("--runs", type=int, default=10, help="Number of map seeds to evaluate (default: 10)")
    parser.add_argument("--seed", type=int, default=1, help="Starting map seed (default: 1)")
    parser.add_argument("--mode", choices=["solo", "head_to_head", "both"], default="solo", help="Match evaluation mode")
    parser.add_argument("--workers", type=int, default=4, help="Parallel worker threads (default: 4)")
    args = parser.parse_args()

    python_exe = sys.executable

    # Define bots
    bot_configs = [
        ("Antigravity Bot", [python_exe, "submission/my_bot.py"]),
        ("Sample Bot", [python_exe, "sample_bot/python/basic_bot.py"]),
        ("Do-Nothing Bot", [python_exe, "templates/python/my_bot.py"]),
    ]

    modes = ["solo", "head_to_head"] if args.mode == "both" else [args.mode]

    for m in modes:
        print(f"\n>>> Running Evaluation Mode: {m.upper()} ({args.runs} seeds, start seed {args.seed}) <<<")
        results = evaluate_bots(
            bot_configs=bot_configs,
            runs=args.runs,
            start_seed=args.seed,
            parallel=True,
            workers=args.workers,
            mode=m,
        )
        print_comparison_table(results)


if __name__ == "__main__":
    main()
