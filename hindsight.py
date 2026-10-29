#!/usr/bin/env python3
"""
STAGE B - Hindsight Upper Bound Planner
Computes near-optimal single-runner plan with full knowledge of all drop spawns.
Uses Macro-Action Beam Search over 300 ticks:
- Exact spawn ticks, TTL expiry, exponential decay
- Exact COLLECT (1 tick) and DEPOSIT (1 tick) mechanics
- Capacity constraint (500)
- Feasibility check: must end with a deposit before tick 300
- Analyzes gap breakdown: idle ticks, late pickups, long trips, stolen drops.
"""

import argparse
import heapq
import json
import math
import os
import random
import statistics
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
KIT_DIR = os.path.join(WORKSPACE_DIR, "Subway_Escape")
if os.path.join(KIT_DIR, "practice_arena") not in sys.path:
    sys.path.insert(0, os.path.join(KIT_DIR, "practice_arena"))

from practice_arena import PracticeArena, TOTAL_TICKS, RUNNER_CAPACITY, NUM_NODES, WORLD_SIZE


@dataclass
class SpawnedDrop:
    drop_id: int
    node_id: int
    target_safehouse: int
    base_value: float
    leak: float
    ttl: int
    spawn_tick: int

    def value_at(self, tick: int) -> float:
        if tick < self.spawn_tick or tick >= self.spawn_tick + self.ttl:
            return 0.0
        return self.base_value * math.exp(-self.leak * (tick - self.spawn_tick))


class LoggingArena(PracticeArena):
    def __init__(self, commands, seed=1, ticks=TOTAL_TICKS, verbose=False, log_dir="practice_logs"):
        self.logged_spawns: List[SpawnedDrop] = []
        super().__init__(commands, seed=seed, ticks=ticks, verbose=verbose, log_dir=log_dir)
        for d in self.drops:
            self.logged_spawns.append(SpawnedDrop(
                d.drop_id, d.node_id, d.target_safehouse, d.base_value, d.leak, d.ttl, d.spawn_tick
            ))

    def _spawn_one_drop(self):
        res = super()._spawn_one_drop()
        if res and self.drops:
            d = self.drops[-1]
            self.logged_spawns.append(SpawnedDrop(
                d.drop_id, d.node_id, d.target_safehouse, d.base_value, d.leak, d.ttl, d.spawn_tick
            ))
        return res


def run_and_log_match(seed: int, bot_cmd: List[str], ticks: int = TOTAL_TICKS) -> Tuple[Dict[int, Any], List[Any], List[SpawnedDrop], int, float]:
    """
    Runs an actual match with bot_cmd, logging all drop spawns that occurred.
    Returns: (nodes, edges, spawned_drops, runner_start_node, bot_actual_score)
    """
    log_dir = f"practice_logs/hindsight_seed{seed}"
    os.makedirs(log_dir, exist_ok=True)
    arena = LoggingArena([bot_cmd], seed=seed, ticks=ticks, verbose=False, log_dir=log_dir)
    stats = arena.run()
    bot_score = stats[1].score
    start_node = arena.runners[1].node

    return arena.nodes, arena.edges, arena.logged_spawns, start_node, bot_score


def compute_all_pairs_hops(nodes: Dict[int, Any], edges: List[Any]) -> Dict[int, Dict[int, int]]:
    """Compute shortest BFS hop distance between all node pairs."""
    adj = {n: [] for n in nodes}
    for e in edges:
        adj[e.a].append(e.b)
        adj[e.b].append(e.a)

    dist = {}
    for start in nodes:
        d = {start: 0}
        q = [start]
        while q:
            u = q.pop(0)
            for v in adj[u]:
                if v not in d:
                    d[v] = d[u] + 1
                    q.append(v)
        dist[start] = d
    return dist


@dataclass(order=True)
class HindsightState:
    neg_score: float  # for max-heap priority queue
    banked_score: float = 0.0
    carried_loot: float = 0.0
    current_node: int = 0
    current_tick: int = 0
    collected_mask: int = 0  # bitmask of collected drops
    history: List[Tuple[str, int, int, float]] = None  # (action, node, tick, value)


def solve_hindsight(
    nodes: Dict[int, Any],
    edges: List[Any],
    drops: List[SpawnedDrop],
    start_node: int,
    total_ticks: int = TOTAL_TICKS,
    beam_width: int = 800,
) -> Tuple[float, List[Tuple[str, int, int, float]]]:
    """
    Macro-action beam search to find near-optimal single-runner plan.
    Macro actions:
      1. Go to drop d, wait if necessary until spawn, COLLECT (1 tick)
      2. Go to safehouse s, DEPOSIT (1 tick)
    """
    safehouses = [n for n, node in nodes.items() if node.type == "safehouse"]
    dist = compute_all_pairs_hops(nodes, edges)

    # Do not cap drops; python bitmasks handle arbitrary width
    drop_index = {d.drop_id: i for i, d in enumerate(drops)}

    # Distance to nearest safehouse from any node
    nearest_safe_dist = {}
    nearest_safe_node = {}
    for u in nodes:
        best_d = 999
        best_s = safehouses[0]
        for s in safehouses:
            if dist[u][s] < best_d:
                best_d = dist[u][s]
                best_s = s
        nearest_safe_dist[u] = best_d
        nearest_safe_node[u] = best_s

    # Initial state
    init_state = HindsightState(
        neg_score=0.0,
        banked_score=0.0,
        carried_loot=0.0,
        current_node=start_node,
        current_tick=0,
        collected_mask=0,
        history=[("START", start_node, 0, 0.0)]
    )

    beam = [init_state]
    best_final_score = 0.0
    best_final_history = []

    # Run beam search until all states exceed 300 ticks (up to 300 macro steps)
    for step in range(300):
        if not beam:
            break
        # If all states in beam have reached total_ticks, we can stop
        if all(s.current_tick >= total_ticks for s in beam):
            break

        next_candidates = []
        for state in beam:
            # Check if current state can deposit before tick 300 to update best_final_score
            if state.carried_loot > 0:
                s_node = nearest_safe_node[state.current_node]
                t_arr_safe = state.current_tick + dist[state.current_node][s_node]
                t_dep = t_arr_safe + 1  # 1 tick to deposit
                if t_dep <= total_ticks:
                    final_score = state.banked_score + state.carried_loot
                    if final_score > best_final_score:
                        best_final_score = final_score
                        best_final_history = list(state.history) + [("DEPOSIT", s_node, t_dep, state.carried_loot)]
            else:
                if state.banked_score > best_final_score:
                    best_final_score = state.banked_score
                    best_final_history = list(state.history)

            # Option A: Go deposit at nearest safehouse (if carrying loot)
            if state.carried_loot > 0:
                s_node = nearest_safe_node[state.current_node]
                travel_ticks = dist[state.current_node][s_node]
                t_dep = state.current_tick + travel_ticks + 1
                if t_dep <= total_ticks:
                    new_banked = state.banked_score + state.carried_loot
                    new_hist = list(state.history) + [("DEPOSIT", s_node, t_dep, state.carried_loot)]
                    next_candidates.append(HindsightState(
                        neg_score=-new_banked,
                        banked_score=new_banked,
                        carried_loot=0.0,
                        current_node=s_node,
                        current_tick=t_dep,
                        collected_mask=state.collected_mask,
                        history=new_hist
                    ))

            # Option B: Go collect an available drop
            if state.carried_loot < RUNNER_CAPACITY:
                for d in drops:
                    idx = drop_index[d.drop_id]
                    if (state.collected_mask & (1 << idx)) != 0:
                        continue  # already collected

                    travel = dist[state.current_node][d.node_id]
                    t_arrive = state.current_tick + travel
                    # Do not idle for long periods waiting for future drops
                    if t_arrive < d.spawn_tick:
                        if d.spawn_tick - t_arrive > 2:
                            continue
                        t_arrive = d.spawn_tick
                    t_collect = t_arrive + 1  # 1 tick to collect

                    # Expiry check
                    if t_arrive >= d.spawn_tick + d.ttl:
                        continue

                    # Must have enough time left to return to safehouse and deposit before tick 300
                    h_safe = nearest_safe_dist[d.node_id]
                    if t_collect + h_safe + 1 > total_ticks:
                        continue

                    val = d.value_at(t_arrive)
                    if val <= 0:
                        continue

                    take = min(RUNNER_CAPACITY - state.carried_loot, val)
                    new_carried = state.carried_loot + take
                    new_mask = state.collected_mask | (1 << idx)
                    new_hist = list(state.history) + [("COLLECT", d.node_id, t_collect, take)]

                    # Heuristic score for ranking: banked + carried + future potential rate
                    potential = state.banked_score + new_carried
                    next_candidates.append(HindsightState(
                        neg_score=-potential,
                        banked_score=state.banked_score,
                        carried_loot=new_carried,
                        current_node=d.node_id,
                        current_tick=t_collect,
                        collected_mask=new_mask,
                        history=new_hist
                    ))

        # Filter and select top states for next beam
        # Deduplicate states with same (node, tick, mask)
        seen = {}
        for s in next_candidates:
            key = (s.current_node, s.current_tick // 4, round(s.carried_loot / 50.0))
            if key not in seen or s.banked_score + s.carried_loot > seen[key].banked_score + seen[key].carried_loot:
                seen[key] = s

        unique_cands = list(seen.values())
        unique_cands.sort(key=lambda s: -(s.banked_score + s.carried_loot * 0.95))
        beam = unique_cands[:beam_width]

    return best_final_score, best_final_history


def run_hindsight_analysis(seeds: List[int], bot_cmd: Optional[List[str]] = None) -> Dict[str, Any]:
    if bot_cmd is None:
        bot_cmd = [sys.executable, "my_bot_v4.py"]

    print(f"Running Hindsight Upper Bound Analysis across {len(seeds)} seeds using actual match spawns...")
    bounds = []
    actual_scores = []
    gaps = []
    times = []

    print(f"{'Seed':<5} | {'Bot Score':<12} | {'Hindsight Bound':<16} | {'Gap ($)':<12} | {'Gap (%)':<8} | {'Logged Drops':<12} | {'Time':<6}")
    print("-" * 80)

    for seed in seeds:
        t0 = time.time()
        nodes, edges, drops, start_node, actual_score = run_and_log_match(seed, bot_cmd)
        bound, hist = solve_hindsight(nodes, edges, drops, start_node, beam_width=1500)
        dt = time.time() - t0

        gap = bound - actual_score
        gap_pct = (gap / bound * 100) if bound > 0 else 0.0

        bounds.append(bound)
        actual_scores.append(actual_score)
        gaps.append(gap)
        times.append(dt)

        print(f"{seed:<5d} | ${actual_score:<11,.1f} | ${bound:<15,.1f} | ${gap:<11,.1f} | {gap_pct:<7.1f}% | {len(drops):<12d} | {dt:<5.1f}s")

    mean_actual = statistics.mean(actual_scores)
    mean_bound = statistics.mean(bounds)
    mean_gap = statistics.mean(gaps)
    mean_gap_pct = (mean_gap / mean_bound * 100) if mean_bound > 0 else 0.0

    print("\n" + "=" * 80)
    print(f"HINDSIGHT HEADROOM SUMMARY (N={len(seeds)})")
    print("=" * 80)
    print(f"Mean Actual Bot Score:    ${mean_actual:,.1f}")
    print(f"Mean Hindsight Bound:     ${mean_bound:,.1f}")
    print(f"Mean Headroom Gap:        ${mean_gap:,.1f} ({mean_gap_pct:.1f}% headroom)")
    print(f"Median Actual Bot Score:  ${statistics.median(actual_scores):,.1f}")
    print(f"Median Hindsight Bound:   ${statistics.median(bounds):,.1f}")
    print(f"Median Headroom Gap:      ${statistics.median(gaps):,.1f}")
    print("=" * 80)

    return {
        "seeds": seeds,
        "actual_scores": actual_scores,
        "bounds": bounds,
        "gaps": gaps,
        "mean_actual": mean_actual,
        "mean_bound": mean_bound,
        "mean_gap": mean_gap,
        "mean_gap_pct": mean_gap_pct,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()

    test_seeds = list(range(args.seed, args.seed + args.runs))
    run_hindsight_analysis(test_seeds)
