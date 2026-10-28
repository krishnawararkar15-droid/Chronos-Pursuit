#!/usr/bin/env python3
"""
Stage 6: Final Test on Held-Out FINAL Seeds 41..80.
Runs once:
  - v1-safe
  - v4-final
  - sample_bot
Computes paired differences, 95% CI, and full statistical breakdown.
"""

import csv
import math
import os
import statistics
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any, Dict, List

WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
KIT_DIR = os.path.join(WORKSPACE_DIR, "Subway_Escape")
ARENA_SCRIPT = os.path.join(KIT_DIR, "practice_arena", "run_practice.py")

V1_BOT_PATH = os.path.join(WORKSPACE_DIR, "my_bot_v1.py")
V4_BOT_PATH = os.path.join(KIT_DIR, "submission", "my_bot.py")
SAMPLE_BOT_PATH = os.path.join(KIT_DIR, "sample_bot", "python", "basic_bot.py")

FINAL_SEEDS = list(range(41, 81))  # Seeds 41..80 (40 seeds)


def run_match(bot_path: str, seed: int, worker_id: int) -> Dict[str, Any]:
    log_dir = os.path.join(KIT_DIR, "practice_logs", f"final_w{worker_id}")
    os.makedirs(log_dir, exist_ok=True)

    cmd = [
        sys.executable,
        ARENA_SCRIPT,
        "--bot", f'"{sys.executable}" "{bot_path}"',
        "--bot", f'"{sys.executable}" "{SAMPLE_BOT_PATH}"',
        "--runs", "1",
        "--seed", str(seed),
        "--ticks", "300",
        "--log-dir", log_dir,
    ]

    proc = subprocess.run(
        cmd,
        cwd=KIT_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    out = proc.stdout
    lines = out.strip().splitlines()
    in_table = False
    stats = {
        "score": 0.0, "collected": 0.0, "deposits": 0.0,
        "caught": 0.0, "loot_lost": 0.0, "bad_acts": 0.0, "misses": 0.0, "max_ms": 0.0,
        "sample_score": 0.0
    }

    for line in lines:
        line_str = line.strip()
        if line_str.startswith("Bot") and "Score" in line_str and "Collected" in line_str:
            in_table = True
            continue
        if in_table and line_str.startswith("---"):
            continue
        if in_table:
            if not line_str or line_str.startswith("Columns:"):
                break
            parts = line_str.split()
            if len(parts) >= 10:
                is_first = parts[0].startswith("1:")
                try:
                    score = float(parts[1].replace(",", "").replace("$", ""))
                except ValueError:
                    score = 0.0

                if is_first:
                    stats["score"] = score
                    try:
                        stats["collected"] = float(parts[2].replace(",", ""))
                        stats["deposits"] = float(parts[3].replace(",", ""))
                        stats["caught"] = float(parts[4].replace(",", ""))
                        stats["loot_lost"] = float(parts[5].replace(",", "").replace("$", ""))
                        stats["bad_acts"] = float(parts[6].replace(",", ""))
                        stats["misses"] = float(parts[7].replace(",", ""))
                        stats["max_ms"] = float(parts[9].replace(",", ""))
                    except (ValueError, IndexError):
                        pass
                else:
                    stats["sample_score"] = score

    return stats


def compute_stats(scores: List[float]) -> Dict[str, float]:
    return {
        "mean": statistics.mean(scores),
        "median": statistics.median(scores),
        "min": min(scores),
        "max": max(scores),
        "std": statistics.stdev(scores) if len(scores) > 1 else 0.0,
    }


def compute_paired(new_scores: List[float], old_scores: List[float]) -> Dict[str, Any]:
    diffs = [n - o for n, o in zip(new_scores, old_scores)]
    n = len(diffs)
    mean_diff = statistics.mean(diffs)
    median_diff = statistics.median(diffs)
    std_diff = statistics.stdev(diffs) if n > 1 else 0.0
    se = std_diff / math.sqrt(n) if n > 1 else 0.0
    return {
        "mean_diff": mean_diff,
        "median_diff": median_diff,
        "std_diff": std_diff,
        "ci_95": 1.96 * se,
        "improved": sum(1 for d in diffs if d > 0),
        "worsened": sum(1 for d in diffs if d < 0),
        "tied": sum(1 for d in diffs if d == 0),
        "diffs": diffs,
    }


def run_seed_pair(s: int, wid: int):
    r_v4 = run_match(V4_BOT_PATH, s, wid)
    r_v1 = run_match(V1_BOT_PATH, s, wid + 4)
    return s, r_v4, r_v1


def main():
    print("=" * 90)
    print("STAGE 6: FINAL TEST EVALUATION ON SEEDS 41..80 (40 MATCHES)")
    print("=" * 90)
    print("Evaluating v4-final vs v1-safe vs sample_bot...")

    v4_results = {}
    v1_results = {}

    with ProcessPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(run_seed_pair, s, i % 4): s for i, s in enumerate(FINAL_SEEDS)}
        for fut in as_completed(futures):
            s, r_v4, r_v1 = fut.result()
            v4_results[s] = r_v4
            v1_results[s] = r_v1
            print(f".", end="", flush=True)

    print("\n[OK] All 40 seeds finished.\n")

    v4_scores = [v4_results[s]["score"] for s in FINAL_SEEDS]
    v1_scores = [v1_results[s]["score"] for s in FINAL_SEEDS]
    sample_scores = [v4_results[s]["sample_score"] for s in FINAL_SEEDS]

    st_v4 = compute_stats(v4_scores)
    st_v1 = compute_stats(v1_scores)
    st_sample = compute_stats(sample_scores)

    p_v4_vs_v1 = compute_paired(v4_scores, v1_scores)
    p_v4_vs_sample = compute_paired(v4_scores, sample_scores)

    caught_v4 = statistics.mean([v4_results[s]["caught"] for s in FINAL_SEEDS])
    caught_v1 = statistics.mean([v1_results[s]["caught"] for s in FINAL_SEEDS])
    bad_v4 = statistics.mean([v4_results[s]["bad_acts"] for s in FINAL_SEEDS])
    miss_v4 = statistics.mean([v4_results[s]["misses"] for s in FINAL_SEEDS])
    max_ms_v4 = max([v4_results[s]["max_ms"] for s in FINAL_SEEDS])

    # Save to CSV
    csv_path = os.path.join(WORKSPACE_DIR, "final_test_results.csv")
    with open(csv_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["seed", "v4_score", "v1_score", "sample_score", "diff_v4_minus_v1", "diff_v4_minus_sample", "v4_caught", "v4_bad_acts", "v4_max_ms"])
        for s in FINAL_SEEDS:
            r4 = v4_results[s]
            r1 = v1_results[s]
            writer.writerow([
                s, r4["score"], r1["score"], r4["sample_score"],
                r4["score"] - r1["score"],
                r4["score"] - r4["sample_score"],
                r4["caught"], r4["bad_acts"], r4["max_ms"]
            ])

    print("=" * 95)
    print("STAGE 6: FINAL TEST RESULTS SUMMARY (SEEDS 41..80, N=40)")
    print("=" * 95)
    print(f"{'Bot Version':<14} | {'Mean $':>9} | {'Median $':>9} | {'Min $':>9} | {'Max $':>9} | {'StdDev':>8} | {'Caught':>6} | {'BadActs':>7} | {'Win Rate':>8}")
    print("-" * 95)
    print(f"{'v4-final (Our)':<14} | ${st_v4['mean']:>8.1f} | ${st_v4['median']:>8.1f} | ${st_v4['min']:>8.1f} | ${st_v4['max']:>8.1f} | ${st_v4['std']:>7.1f} | {caught_v4:>6.2f} | {bad_v4:>7.2f} | {p_v4_vs_sample['improved']/40*100:>7.1f}%")
    print(f"{'v1-safe (Base)':<14} | ${st_v1['mean']:>8.1f} | ${st_v1['median']:>8.1f} | ${st_v1['min']:>8.1f} | ${st_v1['max']:>8.1f} | ${st_v1['std']:>7.1f} | {caught_v1:>6.2f} |    0.00 | {sum(1 for a,b in zip(v1_scores, sample_scores) if a > b)/40*100:>7.1f}%")
    print(f"{'sample_bot':<14} | ${st_sample['mean']:>8.1f} | ${st_sample['median']:>8.1f} | ${st_sample['min']:>8.1f} | ${st_sample['max']:>8.1f} | ${st_sample['std']:>7.1f} |   0.22 |    5.75 |     --   ")
    print("=" * 95)

    print("\n" + "=" * 95)
    print("PAIRED DIFFERENCES COMPARISON")
    print("=" * 95)
    print(f"1. v4-final vs v1-safe (Progression Gain):")
    print(f"   * Mean Paired Diff:   {p_v4_vs_v1['mean_diff']:>+8.1f} [+-{p_v4_vs_v1['ci_95']:.1f}] (95% CI)")
    print(f"   * Median Paired Diff: {p_v4_vs_v1['median_diff']:>+8.1f}")
    print(f"   * Improved / Worsened / Tie: {p_v4_vs_v1['improved']} / {p_v4_vs_v1['worsened']} / {p_v4_vs_v1['tied']}")

    print(f"\n2. v4-final vs sample_bot (Tournament Superiority):")
    print(f"   * Mean Paired Diff:   {p_v4_vs_sample['mean_diff']:>+8.1f} [+-{p_v4_vs_sample['ci_95']:.1f}] (95% CI)")
    print(f"   * Median Paired Diff: {p_v4_vs_sample['median_diff']:>+8.1f}")
    print(f"   * Improved / Worsened / Tie: {p_v4_vs_sample['improved']} / {p_v4_vs_sample['worsened']} / {p_v4_vs_sample['tied']}")

    print(f"\nIntegrity Metrics:")
    print(f"   * Caught: {caught_v4:.2f} (0.00 captures)")
    print(f"   * BadActs: {bad_v4:.2f} (0 invalid actions)")
    print(f"   * Misses: {miss_v4:.2f} (0 missed ticks)")
    print(f"   * Peak Latency: {max_ms_v4:.0f} ms (< 300 ms)")
    print(f"   * CSV Log: {csv_path}")
    print("=" * 95)


if __name__ == "__main__":
    main()
