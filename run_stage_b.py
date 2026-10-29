#!/usr/bin/env python3
"""
STAGE B Execution Script
Runs Hindsight analysis across 20 TUNE seeds (1-20) and 20 VALIDATE seeds (81-100)
Computes:
  - Hindsight upper bound vs v4-final actual score per map
  - Gap breakdown: Idle ticks, Late pickups (decay), Long trips (travel), Drops expired/unreached
"""

import json
import os
import statistics
import sys
import time

from hindsight import run_and_log_match, solve_hindsight
from gap_analyzer import AuditArena, audit_seed, run_audit

PYTHON = sys.executable
V4_BOT = [PYTHON, "my_bot_v4.py"]


def run_stage_b():
    print("=" * 80)
    print("STAGE B: MEASURE HEADROOM & HINDSIGHT UPPER BOUND")
    print("=" * 80)

    # We evaluate 20 seeds from TUNE and 20 seeds from VALIDATE
    tune_seeds = list(range(1, 21))
    val_seeds = list(range(81, 101))

    all_results = {}

    for s_name, seeds in [("TUNE", tune_seeds), ("VALIDATE", val_seeds)]:
        print(f"\n>>> Running Hindsight Upper Bound on {s_name} (Seeds {seeds[0]}..{seeds[-1]}) <<<")
        bounds = []
        actuals = []
        gaps = []

        print(f"{'Seed':<5} | {'Bot Score':<12} | {'Hindsight Bound':<16} | {'Gap ($)':<12} | {'Gap (%)':<8} | {'Logged Drops':<12} | {'Time':<6}")
        print("-" * 80)

        for seed in seeds:
            t0 = time.time()
            nodes, edges, drops, start_node, act_score = run_and_log_match(seed, V4_BOT)
            bound, hist = solve_hindsight(nodes, edges, drops, start_node, beam_width=1500)
            dt = time.time() - t0

            # Upper bound is at least the actual score achieved
            bound = max(bound, act_score)
            gap = bound - act_score
            gap_pct = (gap / bound * 100) if bound > 0 else 0.0

            bounds.append(bound)
            actuals.append(act_score)
            gaps.append(gap)

            print(f"{seed:<5d} | ${act_score:<11,.1f} | ${bound:<15,.1f} | ${gap:<11,.1f} | {gap_pct:<7.1f}% | {len(drops):<12d} | {dt:<5.1f}s")
            sys.stdout.flush()

        mean_act = statistics.mean(actuals)
        mean_bnd = statistics.mean(bounds)
        mean_gp = statistics.mean(gaps)
        gp_pct = (mean_gp / mean_bnd * 100) if mean_bnd > 0 else 0.0

        print("\n" + "-" * 60)
        print(f"HINDSIGHT SUMMARY - {s_name} (N={len(seeds)}):")
        print(f"  Mean Bot Score:        ${mean_act:,.1f}")
        print(f"  Mean Hindsight Bound:  ${mean_bnd:,.1f}")
        print(f"  Mean Headroom Gap:     ${mean_gp:,.1f} ({gp_pct:.1f}% headroom)")
        print(f"  Median Bot Score:      ${statistics.median(actuals):,.1f}")
        print(f"  Median Hindsight Bound:${statistics.median(bounds):,.1f}")
        print(f"  Median Gap:            ${statistics.median(gaps):,.1f}")
        print("-" * 60)

        # Run Gap audit
        print(f"\nRunning Money Conservation & Gap Breakdown Audit on {s_name}...")
        audit_res = run_audit(seeds, V4_BOT)

        all_results[s_name] = {
            "mean_actual": mean_act,
            "mean_bound": mean_bnd,
            "mean_gap": mean_gp,
            "gap_pct": gp_pct,
            "audit": audit_res
        }

    with open("stage_b_results.json", "w") as f:
        json.dump(all_results, f, indent=2)

    print("\nStage B complete! Saved to stage_b_results.json")


if __name__ == "__main__":
    run_stage_b()
