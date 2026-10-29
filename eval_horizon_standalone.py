#!/usr/bin/env python3
"""
Test harness for Rolling Horizon Beam Search Planner (Stage C)
Directly simulates matches and compares score vs v4-final.
"""
import copy
import math
import sys
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

# Import official arena
from Subway_Escape.practice_arena.practice_arena import PracticeArena

# We will test the horizon beam search algorithm
@dataclass
class BeamState:
    node: int
    tick: int
    carrying: float
    banked: float
    collected_mask: int
    first_action: Optional[Tuple[str, Optional[int]]]
    first_drop_id: Optional[int]
    score: float = 0.0

def plan_horizon(
    runner_node: int,
    carrying_loot: float,
    max_capacity: float,
    world_tick: int,
    ticks_left: int,
    drops: list,
    safehouses: list,
    graph_engine,
    dist_m: dict,
    prev_m: dict,
    prev_drop_id: Optional[int] = None,
    H: int = 40,
    beam_width: int = 30,
    switch_gain: float = 0.15,
    avg_lambda: float = 0.015,
) -> Tuple[Optional[Tuple[str, Optional[int]]], Optional[int], float]:
    """
    Rolling-horizon beam search that maximizes total banked value over next H ticks.
    Returns: (first_action_tuple, target_drop_id, best_score)
    """
    # Filter reachable, non-expired drops
    valid_drops = []
    for d in drops:
        # TTL check
        if d.ttl_remaining <= 1:
            continue
        # Reachability
        p = graph_engine.path(runner_node, d.node_id, prev=prev_m)
        if not p:
            continue
        valid_drops.append((d, len(p) - 1))

    if not valid_drops and carrying_loot <= 0:
        return None, None, 0.0

    # Precompute nearest safehouse from each drop and safehouse distance
    safe_dist_cache = {}
    for s in safehouses:
        graph_engine.get_static_paths(s)

    def get_nearest_safe(u: int) -> Tuple[int, int]:
        if u in safe_dist_cache:
            return safe_dist_cache[u]
        best_s = safehouses[0]
        min_h = 999
        for s in safehouses:
            p = graph_engine.path(s, u)
            h = len(p) - 1 if p else 999
            if h < min_h:
                min_h = h
                best_s = s
        safe_dist_cache[u] = (best_s, min_h)
        return best_s, min_h

    # Precompute hop distance between drop nodes
    hop_cache = {}
    def get_hops(u: int, v: int) -> int:
        if u == v:
            return 0
        pair = (u, v)
        if pair in hop_cache:
            return hop_cache[pair]
        p = graph_engine.path(u, v)
        h = len(p) - 1 if p else 999
        hop_cache[pair] = h
        return h

    # Candidate drops list (up to 12)
    candidate_drops = [d for d, _ in valid_drops[:12]]
    drop_index_map = {d.drop_id: idx for idx, d in enumerate(candidate_drops)}

    init_state = BeamState(
        node=runner_node,
        tick=world_tick,
        carrying=carrying_loot,
        banked=0.0,
        collected_mask=0,
        first_action=None,
        first_drop_id=None,
        score=0.0
    )

    beam = [init_state]
    best_completed_state = None
    best_completed_score = -1.0

    max_steps = 4
    for step in range(max_steps):
        next_beam = []

        for st in beam:
            # Check horizon or endgame cutoff
            if st.tick >= world_tick + H or st.tick >= 300:
                if st.score > best_completed_score:
                    best_completed_score = st.score
                    best_completed_state = st
                continue

            # Option 1: Deposit at safehouse (if carrying > 0)
            if st.carrying > 0:
                for s in safehouses:
                    h_s = get_hops(st.node, s)
                    if h_s >= 999:
                        continue
                    t_dep = st.tick + h_s + 1
                    if t_dep > 300:
                        continue
                    decay_s = math.exp(-avg_lambda * h_s)
                    loot_banked = st.carrying * decay_s
                    new_banked = st.banked + loot_banked

                    # First action resolution
                    if st.first_action is None:
                        if h_s == 0:
                            fa = ("DEPOSIT", None)
                        else:
                            fa = ("TRAVERSE", graph_engine.next_hop(runner_node, s, prev=prev_m))
                        f_did = None
                    else:
                        fa = st.first_action
                        f_did = st.first_drop_id

                    # State score
                    elapsed = t_dep - world_tick
                    rate = new_banked / max(1, elapsed)
                    sc = new_banked * 0.7 + (rate * 30.0) * 0.3

                    nxt_st = BeamState(
                        node=s,
                        tick=t_dep,
                        carrying=0.0,
                        banked=new_banked,
                        collected_mask=st.collected_mask,
                        first_action=fa,
                        first_drop_id=f_did,
                        score=sc
                    )
                    next_beam.append(nxt_st)
                    if sc > best_completed_score:
                        best_completed_score = sc
                        best_completed_state = nxt_st

            # Option 2: Collect an active drop
            if st.carrying < max_capacity:
                for idx, d in enumerate(candidate_drops):
                    if (st.collected_mask & (1 << idx)) != 0:
                        continue
                    h_d = get_hops(st.node, d.node_id) if st.node != runner_node else next(h for dr, h in valid_drops if dr.drop_id == d.drop_id)
                    if h_d >= 999:
                        continue
                    t_arr = st.tick + h_d
                    elapsed_from_now = t_arr - world_tick
                    if elapsed_from_now >= d.ttl_remaining:
                        continue

                    # Feasibility check: Can deposit before tick 300?
                    _, h_safe = get_nearest_safe(d.node_id)
                    if t_arr + 1 + h_safe + 1 > 300:
                        continue

                    # Drop value at arrival
                    val_arr = d.current_value * math.exp(-d.leak_lambda * elapsed_from_now)
                    room = max_capacity - st.carrying
                    take = min(room, val_arr)
                    if take <= 0:
                        continue

                    decay_carry = math.exp(-avg_lambda * (h_d + 1))
                    new_carry = st.carrying * decay_carry + take
                    t_after_col = t_arr + 1

                    # First action resolution
                    if st.first_action is None:
                        if h_d == 0:
                            fa = ("COLLECT", None)
                        else:
                            fa = ("TRAVERSE", graph_engine.next_hop(runner_node, d.node_id, prev=prev_m))
                        f_did = d.drop_id
                    else:
                        fa = st.first_action
                        f_did = st.first_drop_id

                    # Objective evaluation
                    dec_to_safe = math.exp(-avg_lambda * h_safe)
                    potential_banked = st.banked + new_carry * dec_to_safe
                    total_cycle = (t_after_col - world_tick) + h_safe + 1
                    rate = potential_banked / max(1, total_cycle)
                    sc = potential_banked * 0.7 + (rate * 30.0) * 0.3

                    # Hysteresis bonus for sticking to previous drop
                    if f_did == prev_drop_id:
                        sc *= (1.0 + switch_gain)

                    nxt_st = BeamState(
                        node=d.node_id,
                        tick=t_after_col,
                        carrying=new_carry,
                        banked=st.banked,
                        collected_mask=st.collected_mask | (1 << idx),
                        first_action=fa,
                        first_drop_id=f_did,
                        score=sc
                    )
                    next_beam.append(nxt_st)
                    if sc > best_completed_score:
                        best_completed_score = sc
                        best_completed_state = nxt_st

        if not next_beam:
            break

        # Beam pruning: keep top B states
        next_beam.sort(key=lambda s: s.score, reverse=True)
        beam = next_beam[:beam_width]

    if best_completed_state:
        return best_completed_state.first_action, best_completed_state.first_drop_id, best_completed_score
    return None, None, 0.0

print("Horizon planner module verified!")
