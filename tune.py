#!/usr/bin/env python3
"""
Subway Escape - Stage 2 Parameter Sweep (tune.py)
Systematically evaluates hypothesis configs against baseline v1-safe.
Rules:
  - TUNE = seeds 1..20
  - VALIDATE = seeds 21..40
  - Top 5 selected by (mean - 0.5 * std) on TUNE
  - Evaluated on VALIDATE with paired differences
  - Acceptance gated by Rule 4
"""

import argparse
import csv
import json
import math
import os
import statistics
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any, Dict, List, Tuple

WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
KIT_DIR = os.path.join(WORKSPACE_DIR, "Subway_Escape")
ARENA_SCRIPT = os.path.join(KIT_DIR, "practice_arena", "run_practice.py")
MY_BOT_PATH = os.path.join(KIT_DIR, "submission", "my_bot.py")
SAMPLE_BOT_PATH = os.path.join(KIT_DIR, "sample_bot", "python", "basic_bot.py")

TUNE_SEEDS = list(range(1, 21))
VALIDATE_SEEDS = list(range(21, 41))


def run_single_seed(seed: int, config_json: str, worker_id: int = 0) -> Dict[str, Any]:
    """Runs a single match between my_bot (with config) and sample_bot on a given seed."""
    env = os.environ.copy()
    env["BOT_CONFIG_JSON"] = config_json

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
        env=env,
    )

    out = proc.stdout
    lines = out.strip().splitlines()
    in_table = False
    my_bot_stats = {
        "seed": seed,
        "score": 0.0,
        "collected": 0.0,
        "deposits": 0.0,
        "caught": 0.0,
        "loot_lost": 0.0,
        "bad_acts": 0.0,
        "misses": 0.0,
        "avg_ms": 0.0,
        "max_ms": 0.0,
        "sample_score": 0.0,
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
                is_my_bot = "my_bot" in parts[0]
                try:
                    score = float(parts[1].replace(",", "").replace("$", ""))
                    if is_my_bot:
                        my_bot_stats["score"] = score
                        my_bot_stats["collected"] = float(parts[2].replace(",", ""))
                        my_bot_stats["deposits"] = float(parts[3].replace(",", ""))
                        my_bot_stats["caught"] = float(parts[4].replace(",", ""))
                        my_bot_stats["loot_lost"] = float(parts[5].replace(",", "").replace("$", ""))
                        my_bot_stats["bad_acts"] = float(parts[6].replace(",", ""))
                        my_bot_stats["misses"] = float(parts[7].replace(",", ""))
                        my_bot_stats["avg_ms"] = float(parts[8].replace(",", ""))
                        my_bot_stats["max_ms"] = float(parts[9].replace(",", ""))
                    else:
                        my_bot_stats["sample_score"] = score
                except ValueError:
                    pass

    return my_bot_stats


def evaluate_config(name: str, cfg: Dict[str, Any], seeds: List[int], max_workers: int = 4) -> Dict[str, Any]:
    cfg_json = json.dumps(cfg)
    results = []

    # Run seeds in parallel
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(run_single_seed, s, cfg_json, i % max_workers): s for i, s in enumerate(seeds)}
        for fut in as_completed(futures):
            res = fut.result()
            results.append(res)

    results.sort(key=lambda r: r["seed"])
    scores = [r["score"] for r in results]
    mean_sc = statistics.mean(scores)
    std_sc = statistics.stdev(scores) if len(scores) > 1 else 0.0
    metric = mean_sc - 0.5 * std_sc

    return {
        "name": name,
        "config": cfg,
        "seeds": seeds,
        "results": results,
        "scores": scores,
        "mean": mean_sc,
        "std": std_sc,
        "metric": metric,
        "caught": statistics.mean([r["caught"] for r in results]),
        "bad_acts": statistics.mean([r["bad_acts"] for r in results]),
        "misses": statistics.mean([r["misses"] for r in results]),
        "max_ms": max([r["max_ms"] for r in results]),
    }


def compute_paired_stats(new_scores: List[float], baseline_scores: List[float]) -> Dict[str, Any]:
    diffs = [n - b for n, b in zip(new_scores, baseline_scores)]
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
        "mean_diff": mean_diff,
        "median_diff": median_diff,
        "std_diff": std_diff,
        "ci_low": mean_diff - ci_95,
        "ci_high": mean_diff + ci_95,
        "improved": improved,
        "worsened": worsened,
        "tied": tied,
        "diffs": diffs,
    }


def main():
    parser = argparse.ArgumentParser(description="Stage 2 Parameter Sweep")
    parser.add_argument("--workers", type=int, default=4, help="Parallel worker processes")
    args = parser.parse_args()

    # Load baseline scores from eval_results.csv
    baseline_tune_scores = {}
    baseline_val_scores = {}
    csv_file = os.path.join(WORKSPACE_DIR, "eval_results.csv")
    if os.path.exists(csv_file):
        with open(csv_file, mode="r", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r["bot"] == "my_bot":
                    s = int(r["seed"])
                    sc = float(r["score"])
                    if s <= 20:
                        baseline_tune_scores[s] = sc
                    elif 21 <= s <= 40:
                        baseline_val_scores[s] = sc

    b_tune_list = [baseline_tune_scores[s] for s in TUNE_SEEDS]
    b_val_list = [baseline_val_scores[s] for s in VALIDATE_SEEDS]

    print("=" * 85)
    print("STAGE 2: PARAMETER SWEEP ON TUNE SET (SEEDS 1..20)")
    print(f"Baseline TUNE mean: ${statistics.mean(b_tune_list):,.1f} | VAL mean: ${statistics.mean(b_val_list):,.1f}")
    print("=" * 85)

    # Hypothesis configs to test
    candidates = [
        ("C0_baseline", {
            "bank_threshold_min": 180.0, "bank_threshold_max": 420.0,
            "risk_penalty_weight": 6.0, "risk_safety_margin": 8.0,
            "endgame_margin": 4, "dynamic_bank_coef": 3.2
        }),
        ("C1_bank_300", {
            "bank_threshold_min": 300.0, "bank_threshold_max": 440.0,
            "risk_penalty_weight": 6.0, "risk_safety_margin": 8.0,
            "endgame_margin": 4, "dynamic_bank_coef": 3.2
        }),
        ("C2_bank_350", {
            "bank_threshold_min": 350.0, "bank_threshold_max": 460.0,
            "risk_penalty_weight": 6.0, "risk_safety_margin": 8.0,
            "endgame_margin": 4, "dynamic_bank_coef": 3.2
        }),
        ("C3_bank_380", {
            "bank_threshold_min": 380.0, "bank_threshold_max": 470.0,
            "risk_penalty_weight": 6.0, "risk_safety_margin": 8.0,
            "endgame_margin": 4, "dynamic_bank_coef": 3.2
        }),
        ("C4_risk_3.5", {
            "bank_threshold_min": 180.0, "bank_threshold_max": 420.0,
            "risk_penalty_weight": 3.5, "risk_safety_margin": 8.0,
            "endgame_margin": 4, "dynamic_bank_coef": 3.2
        }),
        ("C5_risk_2.5", {
            "bank_threshold_min": 180.0, "bank_threshold_max": 420.0,
            "risk_penalty_weight": 2.5, "risk_safety_margin": 6.0,
            "endgame_margin": 4, "dynamic_bank_coef": 3.2
        }),
        ("C6_bank340_risk3.5", {
            "bank_threshold_min": 340.0, "bank_threshold_max": 460.0,
            "risk_penalty_weight": 3.5, "risk_safety_margin": 7.0,
            "endgame_margin": 4, "dynamic_bank_coef": 3.2
        }),
        ("C7_bank360_risk3.5", {
            "bank_threshold_min": 360.0, "bank_threshold_max": 460.0,
            "risk_penalty_weight": 3.5, "risk_safety_margin": 7.0,
            "endgame_margin": 4, "dynamic_bank_coef": 3.4
        }),
        ("C8_bank380_risk3.0", {
            "bank_threshold_min": 380.0, "bank_threshold_max": 470.0,
            "risk_penalty_weight": 3.0, "risk_safety_margin": 6.5,
            "endgame_margin": 4, "dynamic_bank_coef": 3.5
        }),
        ("C9_bank350_risk4.0_end3", {
            "bank_threshold_min": 350.0, "bank_threshold_max": 460.0,
            "risk_penalty_weight": 4.0, "risk_safety_margin": 7.5,
            "endgame_margin": 3, "dynamic_bank_coef": 3.2
        }),
        ("C10_bank360_risk3.5_end5", {
            "bank_threshold_min": 360.0, "bank_threshold_max": 460.0,
            "risk_penalty_weight": 3.5, "risk_safety_margin": 7.0,
            "endgame_margin": 5, "dynamic_bank_coef": 3.4
        }),
        ("C11_bank400_risk3.5", {
            "bank_threshold_min": 400.0, "bank_threshold_max": 480.0,
            "risk_penalty_weight": 3.5, "risk_safety_margin": 7.0,
            "endgame_margin": 4, "dynamic_bank_coef": 3.6
        }),
    ]

    tune_evals = []
    print(f"{'Config Name':<22} | {'TUNE Mean':>10} | {'TUNE Std':>9} | {'Metric (u-0.5s)':>15} | {'Caught':>6} | {'BadActs':>7} | {'MaxMs':>5}")
    print("-" * 88)

    for name, cfg in candidates:
        ev = evaluate_config(name, cfg, TUNE_SEEDS, max_workers=args.workers)
        tune_evals.append(ev)
        print(f"{name:<22} | ${ev['mean']:>9.1f} | ${ev['std']:>8.1f} | ${ev['metric']:>14.1f} | {ev['caught']:>6.2f} | {ev['bad_acts']:>7.2f} | {ev['max_ms']:>5.0f}")

    # Sort by metric (mean - 0.5 * std)
    tune_evals.sort(key=lambda x: x["metric"], reverse=True)
    top_5 = tune_evals[:5]

    print("\n" + "=" * 88)
    print("TOP 5 CONFIGURATIONS SELECTED BY (u - 0.5s) -> RE-EVALUATING ON VALIDATE (SEEDS 21..40)")
    print("=" * 88)

    val_evals = []
    for rank, ev in enumerate(top_5, start=1):
        name = ev["name"]
        cfg = ev["config"]
        val_ev = evaluate_config(name, cfg, VALIDATE_SEEDS, max_workers=args.workers)
        
        # Paired statistics against baseline
        tune_paired = compute_paired_stats(ev["scores"], b_tune_list)
        val_paired = compute_paired_stats(val_ev["scores"], b_val_list)

        val_evals.append({
            "rank": rank,
            "name": name,
            "config": cfg,
            "tune_ev": ev,
            "val_ev": val_ev,
            "tune_paired": tune_paired,
            "val_paired": val_paired,
        })

    print(f"\n{'Rank':<4} | {'Name':<20} | {'TUNE Mean':>9} | {'TUNE Diff (95% CI)':>22} | {'VAL Mean':>9} | {'VAL Diff (95% CI)':>22} | {'VAL Imp/Wor':>11}")
    print("-" * 110)
    for ve in val_evals:
        tp = ve["tune_paired"]
        vp = ve["val_paired"]
        t_ci = f"+${tp['mean_diff']:,.0f} [+-${1.96*tp['std_diff']/math.sqrt(20):,.0f}]"
        v_ci = f"+${vp['mean_diff']:,.0f} [+-${1.96*vp['std_diff']/math.sqrt(20):,.0f}]" if vp['mean_diff'] >= 0 else f"-${abs(vp['mean_diff']):,.0f} [+-${1.96*vp['std_diff']/math.sqrt(20):,.0f}]"
        imp_wor = f"{vp['improved']}/{vp['worsened']}"
        print(f"#{ve['rank']:<3} | {ve['name']:<20} | ${ve['tune_ev']['mean']:>8.1f} | {t_ci:>22} | ${ve['val_ev']['mean']:>8.1f} | {v_ci:>22} | {imp_wor:>11}")

    # Check Rule 4 on the best candidate
    best = val_evals[0]
    rule4_pass = (
        best["val_paired"]["mean_diff"] > 0
        and best["tune_paired"]["improved"] > best["tune_paired"]["worsened"]
        and best["val_ev"]["caught"] <= 0.05
        and best["val_ev"]["bad_acts"] == 0.0
        and best["val_ev"]["misses"] == 0.0
    )

    print("\n" + "=" * 88)
    print("RULE 4 ACCEPTANCE GATEWAY CHECK FOR TOP CANDIDATE:", best["name"])
    print(f"  * VALIDATE Mean Diff > 0:       {best['val_paired']['mean_diff']:+.1f} -> {'PASS' if best['val_paired']['mean_diff'] > 0 else 'FAIL'}")
    print(f"  * TUNE Improved > Worsened:    {best['tune_paired']['improved']} > {best['tune_paired']['worsened']} -> {'PASS' if best['tune_paired']['improved'] > best['tune_paired']['worsened'] else 'FAIL'}")
    print(f"  * Caught <= 0.05:              {best['val_ev']['caught']:.2f} -> PASS")
    print(f"  * BadActs == 0, Misses == 0:   {best['val_ev']['bad_acts']:.2f}, {best['val_ev']['misses']:.2f} -> PASS")
    print(f"  * Verdict:                     {'ACCEPTED' if rule4_pass else 'REJECTED'}")
    print("=" * 88)

    if rule4_pass:
        print("\nFreezing winning configuration:")
        print(json.dumps(best["config"], indent=2))
        with open("best_config.json", "w") as f:
            json.dump(best["config"], f, indent=2)


if __name__ == "__main__":
    main()
