#!/usr/bin/env python3
"""
Evaluation script for Subway Escape bot comparison.
Runs our bot vs sample_bot across map seeds.
Saves CSV with per-seed metrics:
  seed,set,bot,score,collected,deposits,caught,loot_lost,bad_acts,misses,max_ms,disqualified
Splits seeds into:
  - tuning set: seeds 1..20
  - held-out set: seeds 21..40
Prints statistics (mean, median, min, max, std) for both sets.
"""

import argparse
import csv
import math
import os
import statistics
import subprocess
import sys
from collections import defaultdict

# Root directories
WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
KIT_DIR = os.path.join(WORKSPACE_DIR, "Subway_Escape")
ARENA_SCRIPT = os.path.join(KIT_DIR, "practice_arena", "run_practice.py")
MY_BOT_PATH = os.path.join(KIT_DIR, "submission", "my_bot.py")
SAMPLE_BOT_PATH = os.path.join(KIT_DIR, "sample_bot", "python", "basic_bot.py")


def run_match_pair(seed, ticks=300):
    """
    Run our bot vs sample_bot on a specific seed using run_practice.py.
    Returns dict mapping bot name to metrics dict.
    """
    python_bin = sys.executable
    cmd = [
        python_bin,
        ARENA_SCRIPT,
        "--bot", f'"{python_bin}" "{MY_BOT_PATH}"',
        "--bot", f'"{python_bin}" "{SAMPLE_BOT_PATH}"',
        "--runs", "1",
        "--seed", str(seed),
        "--ticks", str(ticks),
    ]

    # Run the arena match
    proc = subprocess.run(
        cmd,
        cwd=KIT_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    out = proc.stdout
    # Parse table lines from output
    results = {}
    lines = out.strip().splitlines()
    in_table = False
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
                bot_id_label = parts[0]
                bot_label = "my_bot" if "my_bot" in bot_id_label else "sample_bot"
                score_str = parts[1].replace(",", "").replace("$", "")
                try:
                    score = float(score_str)
                    collected = float(parts[2].replace(",", ""))
                    deposits = float(parts[3].replace(",", ""))
                    caught = float(parts[4].replace(",", ""))
                    loot_lost = float(parts[5].replace(",", "").replace("$", ""))
                    bad_acts = float(parts[6].replace(",", ""))
                    misses = float(parts[7].replace(",", ""))
                    avg_ms = float(parts[8].replace(",", ""))
                    max_ms = float(parts[9].replace(",", ""))
                    results[bot_label] = {
                        "score": score,
                        "collected": collected,
                        "deposits": deposits,
                        "caught": caught,
                        "loot_lost": loot_lost,
                        "bad_acts": bad_acts,
                        "misses": misses,
                        "avg_ms": avg_ms,
                        "max_ms": max_ms,
                        "disqualified": 1 if "DISQUALIFIED" in line_str else 0,
                    }
                except ValueError:
                    pass

    return results


def calculate_stats(scores):
    if not scores:
        return {"mean": 0.0, "median": 0.0, "min": 0.0, "max": 0.0, "std": 0.0}
    mean = statistics.mean(scores)
    median = statistics.median(scores)
    min_v = min(scores)
    max_v = max(scores)
    std = statistics.stdev(scores) if len(scores) > 1 else 0.0
    return {"mean": mean, "median": median, "min": min_v, "max": max_v, "std": std}


def main():
    parser = argparse.ArgumentParser(description="Evaluate our bot vs sample_bot across map seeds")
    parser.add_argument("--start-seed", type=int, default=1, help="First seed (default 1)")
    parser.add_argument("--end-seed", type=int, default=40, help="Last seed (default 40)")
    parser.add_argument("--csv", type=str, default="eval_results.csv", help="Output CSV path")
    parser.add_argument("--ticks", type=int, default=300, help="Match ticks (default 300)")
    args = parser.parse_args()

    csv_path = os.path.abspath(args.csv)
    print(f"=== Starting Evaluation Sweep: Seeds {args.start_seed} to {args.end_seed} ===")
    print(f"  Tuning Set:   seeds 1..20")
    print(f"  Held-Out Set: seeds 21..40")
    print(f"  CSV Output:   {csv_path}\n")

    fieldnames = [
        "seed", "set", "bot", "score", "collected", "deposits",
        "caught", "loot_lost", "bad_acts", "misses", "max_ms", "disqualified"
    ]

    all_rows = []
    # Dicts for grouping scores: data[set_name][bot_name] = [scores...]
    grouped_scores = {
        "tuning": defaultdict(list),
        "held_out": defaultdict(list),
        "all": defaultdict(list),
    }
    grouped_metrics = {
        "tuning": defaultdict(lambda: defaultdict(list)),
        "held_out": defaultdict(lambda: defaultdict(list)),
        "all": defaultdict(lambda: defaultdict(list)),
    }

    for seed in range(args.start_seed, args.end_seed + 1):
        set_name = "tuning" if 1 <= seed <= 20 else ("held_out" if 21 <= seed <= 40 else "extra")
        print(f"Running Match seed={seed:02d} [{set_name.upper()}] ... ", end="", flush=True)

        res = run_match_pair(seed, ticks=args.ticks)
        if not res:
            print("FAILED (no output)")
            continue

        my_res = res.get("my_bot", {})
        sample_res = res.get("sample_bot", {})
        print(f"my_bot=${my_res.get('score', 0):,.0f} | sample_bot=${sample_res.get('score', 0):,.0f}")

        for bot_name in ["my_bot", "sample_bot"]:
            b_data = res.get(bot_name)
            if not b_data:
                continue
            row = {
                "seed": seed,
                "set": set_name,
                "bot": bot_name,
                "score": b_data["score"],
                "collected": b_data["collected"],
                "deposits": b_data["deposits"],
                "caught": b_data["caught"],
                "loot_lost": b_data["loot_lost"],
                "bad_acts": b_data["bad_acts"],
                "misses": b_data["misses"],
                "max_ms": b_data["max_ms"],
                "disqualified": b_data["disqualified"],
            }
            all_rows.append(row)

            # Store for stats
            grouped_scores[set_name][bot_name].append(b_data["score"])
            grouped_scores["all"][bot_name].append(b_data["score"])
            for k in ["collected", "deposits", "caught", "loot_lost", "bad_acts", "misses", "max_ms"]:
                grouped_metrics[set_name][bot_name][k].append(b_data[k])
                grouped_metrics["all"][bot_name][k].append(b_data[k])

    # Write CSV
    with open(csv_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"\n[OK] CSV written successfully to: {csv_path}\n")

    # Print summary tables
    def print_section(section_name, s_key):
        print("=" * 90)
        print(f"  {section_name.upper()} SUMMARY TABLE")
        print("=" * 90)
        header = f"{'Bot':<12} | {'Mean $':>9} | {'Median $':>9} | {'Min $':>9} | {'Max $':>9} | {'StdDev':>8} | {'Caught':>6} | {'BadActs':>7} | {'Win Rate':>8}"
        print(header)
        print("-" * len(header))

        my_scores = grouped_scores[s_key].get("my_bot", [])
        sample_scores = grouped_scores[s_key].get("sample_bot", [])
        n_matches = len(my_scores)

        wins = sum(1 for m, s in zip(my_scores, sample_scores) if m > s)
        win_rate_my = (wins / n_matches * 100.0) if n_matches else 0.0
        win_rate_sample = (100.0 - win_rate_my) if n_matches else 0.0

        for b_name in ["my_bot", "sample_bot"]:
            sc = grouped_scores[s_key].get(b_name, [])
            st = calculate_stats(sc)
            c = statistics.mean(grouped_metrics[s_key][b_name]["caught"]) if sc else 0.0
            ba = statistics.mean(grouped_metrics[s_key][b_name]["bad_acts"]) if sc else 0.0
            wr = win_rate_my if b_name == "my_bot" else win_rate_sample
            print(f"{b_name:<12} | {st['mean']:>9.1f} | {st['median']:>9.1f} | {st['min']:>9.1f} | {st['max']:>9.1f} | {st['std']:>8.1f} | {c:>6.2f} | {ba:>7.2f} | {wr:>7.1f}%")
        print("=" * 90 + "\n")

    print_section("Tuning Set (Seeds 1-20)", "tuning")
    print_section("Held-Out Set (Seeds 21-40)", "held_out")
    print_section("All Seeds Combined (Seeds 1-40)", "all")


if __name__ == "__main__":
    main()
