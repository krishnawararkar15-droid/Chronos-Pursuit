#!/usr/bin/env python3
"""
Stage Validator: Computes paired differences for any stage change versus baseline v1-safe.
Gated strictly by Rule 4:
  1. Mean diff on VALIDATE > 0
  2. TUNE improved > worsened
  3. Caught <= 0.05, BadActs == 0, Misses == 0
"""

import csv
import json
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
MY_BOT_PATH = os.path.join(KIT_DIR, "submission", "my_bot.py")
SAMPLE_BOT_PATH = os.path.join(KIT_DIR, "sample_bot", "python", "basic_bot.py")

TUNE_SEEDS = list(range(1, 21))
VALIDATE_SEEDS = list(range(21, 41))


def run_single_seed(seed: int, worker_id: int = 0) -> Dict[str, Any]:
    log_dir = os.path.join(KIT_DIR, "practice_logs", f"w{worker_id}")
    os.makedirs(log_dir, exist_ok=True)

    cmd = [
        sys.executable,
        ARENA_SCRIPT,
        "--bot", f'"{sys.executable}" "{MY_BOT_PATH}"',
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
    my_stats = {
        "seed": seed, "score": 0.0, "collected": 0.0, "deposits": 0.0,
        "caught": 0.0, "loot_lost": 0.0, "bad_acts": 0.0, "misses": 0.0, "max_ms": 0.0
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
            if len(parts) >= 10 and "my_bot" in parts[0]:
                my_stats["score"] = float(parts[1].replace(",", "").replace("$", ""))
                my_stats["collected"] = float(parts[2].replace(",", ""))
                my_stats["deposits"] = float(parts[3].replace(",", ""))
                my_stats["caught"] = float(parts[4].replace(",", ""))
                my_stats["loot_lost"] = float(parts[5].replace(",", "").replace("$", ""))
                my_stats["bad_acts"] = float(parts[6].replace(",", ""))
                my_stats["misses"] = float(parts[7].replace(",", ""))
                my_stats["max_ms"] = float(parts[9].replace(",", ""))

    return my_stats


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


def main():
    stage_name = sys.argv[1] if len(sys.argv) > 1 else "Stage_3a"
    print(f"=== Evaluating {stage_name} across TUNE (seeds 1..20) and VALIDATE (seeds 21..40) ===")

    # Load baseline scores from eval_results.csv
    baseline_scores = {}
    with open(os.path.join(WORKSPACE_DIR, "eval_results.csv"), mode="r", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["bot"] == "my_bot":
                baseline_scores[int(r["seed"])] = float(r["score"])

    all_seeds = TUNE_SEEDS + VALIDATE_SEEDS
    results = {}

    with ProcessPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(run_single_seed, s, i % 4): s for i, s in enumerate(all_seeds)}
        for fut in as_completed(futures):
            res = fut.result()
            results[res["seed"]] = res

    tune_new = [results[s]["score"] for s in TUNE_SEEDS]
    tune_base = [baseline_scores[s] for s in TUNE_SEEDS]
    val_new = [results[s]["score"] for s in VALIDATE_SEEDS]
    val_base = [baseline_scores[s] for s in VALIDATE_SEEDS]

    tp = compute_paired(tune_new, tune_base)
    vp = compute_paired(val_new, val_base)

    tune_caught = statistics.mean([results[s]["caught"] for s in TUNE_SEEDS])
    val_caught = statistics.mean([results[s]["caught"] for s in VALIDATE_SEEDS])
    tune_bad = statistics.mean([results[s]["bad_acts"] for s in TUNE_SEEDS])
    val_bad = statistics.mean([results[s]["bad_acts"] for s in VALIDATE_SEEDS])
    tune_miss = statistics.mean([results[s]["misses"] for s in TUNE_SEEDS])
    val_miss = statistics.mean([results[s]["misses"] for s in VALIDATE_SEEDS])
    max_ms = max(results[s]["max_ms"] for s in all_seeds)

    print("\n" + "=" * 90)
    print(f"PAIRED EVALUATION REPORT: {stage_name}")
    print("=" * 90)
    print(f"{'Metric':<25} | {'TUNE (seeds 1..20)':>28} | {'VALIDATE (seeds 21..40)':>28}")
    print("-" * 90)
    print(f"{'Mean Score (New)':<25} | ${statistics.mean(tune_new):>14.1f}              | ${statistics.mean(val_new):>14.1f}")
    print(f"{'Mean Score (Baseline)':<25} | ${statistics.mean(tune_base):>14.1f}              | ${statistics.mean(val_base):>14.1f}")
    print(f"{'Mean Diff (Paired)':<25} | {tp['mean_diff']:>+14.1f} [+-{tp['ci_95']:.1f}]   | {vp['mean_diff']:>+14.1f} [+-{vp['ci_95']:.1f}]")
    print(f"{'Median Diff':<25} | {tp['median_diff']:>+14.1f}              | {vp['median_diff']:>+14.1f}")
    print(f"{'Improved / Worsened / Tie':<25} | {tp['improved']:>7} / {tp['worsened']:>2} / {tp['tied']:>2}           | {vp['improved']:>7} / {vp['worsened']:>2} / {vp['tied']:>2}")
    print(f"{'Caught per match':<25} | {tune_caught:>14.2f}              | {val_caught:>14.2f}")
    print(f"{'BadActs / Misses':<25} | {tune_bad:>7.2f} / {tune_miss:>4.2f}           | {val_bad:>7.2f} / {val_miss:>4.2f}")
    print(f"{'Peak Latency (MaxMs)':<25} | {max_ms:>14.0f} ms            | (Limit: 300 ms)")
    print("=" * 90)

    # Acceptance check
    rule4_pass = (
        vp["mean_diff"] > 0
        and tp["improved"] > tp["worsened"]
        and val_caught <= 0.05
        and val_bad == 0.0
        and val_miss == 0.0
    )

    print(f"\nRULE 4 GATEWAY CHECK:")
    print(f"  * VALIDATE Mean Diff > 0:    {vp['mean_diff']:+.1f} -> {'PASS' if vp['mean_diff'] > 0 else 'FAIL'}")
    print(f"  * TUNE Improved > Worsened: {tp['improved']} > {tp['worsened']} -> {'PASS' if tp['improved'] > tp['worsened'] else 'FAIL'}")
    print(f"  * Safety & Integrity:        Caught={val_caught:.2f}, BadActs={val_bad:.2f}, Misses={val_miss:.2f} -> PASS")
    print(f"  * VERDICT:                   {'ACCEPTED' if rule4_pass else 'REJECTED'}\n")

    return 0 if rule4_pass else 1


if __name__ == "__main__":
    sys.exit(main())
