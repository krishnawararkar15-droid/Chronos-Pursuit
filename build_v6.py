import os
import sys
import re

def main():
    with open("my_bot_v4.py", "r", encoding="utf-8") as f:
        text = f.read()

    # 1. Update CONFIG with winning Tune 3 parameters, time guards, and feature flags
    old_cfg_pattern = re.compile(r'CONFIG: Dict\[str, Any\] = \{.*?\n\}', re.DOTALL)
    new_cfg = '''CONFIG: Dict[str, Any] = {
    "total_ticks": 300,
    "tick_budget_s": 0.35,
    "soft_time_limit_s": 0.20,     # Stage F: 200ms soft limit for planning
    "hard_time_limit_s": 0.35,     # Stage F: 350ms hard limit for immediate safe fallback
    "debug_log_ticks": 5,
    "debug_log_path": "debug.log",
    "log_timing": False,
    "verbose_stderr": False,       # Keep stderr clean and fast during official matches
    "risk_lookahead_H": 15,
    "risk_safety_margin": 8.0,
    "risk_penalty_weight": 6.0,
    "avg_income_per_tick": 70.0,
    "bank_threshold_min": 220.0,   # Empirically validated winning threshold (+181.4 on VALIDATE)
    "bank_threshold_max": 450.0,   # Empirically validated winning threshold
    "dynamic_bank_coef": 3.5,      # Empirically validated coefficient
    "opportunistic_bank_dist": 1,
    "min_opportunistic_loot": 50.0,
    "switch_gain": 0.15,
    "endgame_margin": 4,           # Empirically validated safe endgame buffer
    "safehouse_congestion_pen": 2.0,
    "enable_chaining": True,
    "chain_max_depth": 3,
    "chain_capacity_cutoff": 450.0,
    "enable_gated_risk": True,
    "enable_horizon_planner": False, # Stage C: Implemented, toggled via CONFIG flag
    "horizon_ticks": 40,
    "horizon_beam_width": 30,
    "horizon_time_budget_s": 0.20,
}'''
    text = old_cfg_pattern.sub(new_cfg, text, count=1)

    # 2. Add evaluate_horizon_planner method before evaluate_chained_sequences
    hz_code = '''    def evaluate_horizon_planner(
        self,
        runner: Runner,
        dist_m: Dict[int, float],
        prev_m: Dict[int, Optional[int]],
        world: World,
        reserved_drop_ids: Set[int],
        avg_lambda: float,
        t_start: float,
    ) -> List[Tuple[float, int, int]]:
        """
        STAGE C: Rolling Horizon Beam Search Planner.
        Maximizes total banked value over next H ticks with strict feasibility checks.
        """
        time_limit = CONFIG.get("horizon_time_budget_s", 0.20)
        if time.perf_counter() - t_start > time_limit:
            return []

        cands = [d for d in world.drops if d.node_id != runner.current_node and d.drop_id not in reserved_drop_ids]
        if not cands:
            return []

        H = CONFIG.get("horizon_ticks", 40)
        beam_width = CONFIG.get("horizon_beam_width", 30)
        max_cap = runner.max_capacity
        curr_loot = runner.carrying_loot
        ticks_left = world.ticks_left

        safe_maps = []
        for s in world.safehouses:
            s_dist, s_prev = self.graph_engine.get_static_paths(s)
            safe_maps.append((s, s_dist, s_prev))

        def get_nearest_safe_hops(u: int) -> Tuple[int, int]:
            best_s = world.safehouses[0] if world.safehouses else 0
            min_h = 999
            for s, s_dist, s_prev in safe_maps:
                if u in s_dist and s_dist[u] != INF:
                    p = self.graph_engine.path(s, u, prev=s_prev)
                    h = len(p) - 1 if p else 999
                    if h < min_h:
                        min_h = h
                        best_s = s
            return best_s, min_h

        hops_cache: Dict[Tuple[int, int], int] = {}
        def get_hops(u: int, v: int) -> int:
            if u == v:
                return 0
            key = (u, v)
            if key in hops_cache:
                return hops_cache[key]
            p = self.graph_engine.path(u, v)
            h = len(p) - 1 if p else 999
            hops_cache[key] = h
            return h

        first_cands = []
        for d1 in cands:
            if d1.node_id not in dist_m or dist_m[d1.node_id] == INF or dist_m[d1.node_id] >= 1e5:
                continue
            p1 = self.graph_engine.path(runner.current_node, d1.node_id, prev=prev_m)
            if not p1:
                continue
            h1 = len(p1) - 1
            if h1 <= 0 or h1 >= d1.ttl_remaining or (h1 + 2 > ticks_left):
                continue
            _, h_safe1 = get_nearest_safe_hops(d1.node_id)
            if h1 + 1 + h_safe1 + 1 > ticks_left:
                continue
            v1_arr = d1.current_value * math.exp(-d1.leak_lambda * h1)
            take1 = min(max_cap - curr_loot, v1_arr)
            if take1 <= 0:
                continue
            rate1 = (curr_loot + take1) / (h1 + 1 + h_safe1 + 1)
            first_cands.append((rate1, d1, h1, take1, h_safe1))

        if not first_cands:
            return []

        first_cands.sort(key=lambda x: x[0], reverse=True)
        top_initial = first_cands[:8]

        chain_pool_set = {d.drop_id: d for _, d, _, _, _ in top_initial}
        for _, d1, _, _, _ in top_initial[:4]:
            for d in cands:
                if d.drop_id not in chain_pool_set:
                    if get_hops(d1.node_id, d.node_id) <= 4:
                        chain_pool_set[d.drop_id] = d

        chain_pool = list(chain_pool_set.values())[:14]
        cand_map = {d.drop_id: idx for idx, d in enumerate(chain_pool)}

        beam = []
        best_rate_by_first: Dict[int, float] = {}
        hops_to_first: Dict[int, int] = {}

        for rate1, d1, h1, take1, h_safe1 in top_initial:
            best_rate_by_first[d1.drop_id] = rate1
            hops_to_first[d1.drop_id] = h1
            t1 = h1 + 1
            idx1 = cand_map[d1.drop_id]
            beam.append((d1.node_id, t1, curr_loot + take1, 0.0, 1 << idx1, d1.drop_id, rate1))

        for step in range(4):
            if time.perf_counter() - t_start > time_limit:
                break
            next_beam = []
            for st_node, st_elapsed, st_carry, st_banked, st_mask, f_did, _ in beam:
                if st_elapsed >= H or world.tick + st_elapsed >= 300:
                    continue

                if st_carry > 0:
                    for s in world.safehouses:
                        h_s = get_hops(st_node, s)
                        if h_s >= 999:
                            continue
                        t_dep = st_elapsed + h_s + 1
                        if world.tick + t_dep > 300:
                            continue
                        new_b = st_banked + st_carry
                        rate_dep = new_b / max(1, t_dep)
                        if rate_dep > best_rate_by_first.get(f_did, 0.0):
                            best_rate_by_first[f_did] = rate_dep
                        next_beam.append((s, t_dep, 0.0, new_b, st_mask, f_did, rate_dep))

                if st_carry < max_cap:
                    for d in chain_pool:
                        idx = cand_map[d.drop_id]
                        if (st_mask & (1 << idx)) != 0:
                            continue
                        h_d = get_hops(st_node, d.node_id)
                        if h_d >= 999:
                            continue
                        t_arr = st_elapsed + h_d
                        if t_arr >= d.ttl_remaining:
                            continue
                        _, h_safe = get_nearest_safe_hops(d.node_id)
                        if world.tick + t_arr + 1 + h_safe + 1 > 300:
                            continue
                        v_arr = d.current_value * math.exp(-d.leak_lambda * t_arr)
                        take = min(max_cap - st_carry, v_arr)
                        if take <= 0:
                            continue
                        new_carry = st_carry + take
                        t_col = t_arr + 1
                        cyc = t_col + h_safe + 1
                        rate_chain = (st_banked + new_carry) / max(1, cyc)
                        if rate_chain > best_rate_by_first.get(f_did, 0.0):
                            best_rate_by_first[f_did] = rate_chain
                        next_beam.append((d.node_id, t_col, new_carry, st_banked, st_mask | (1 << idx), f_did, rate_chain))

            if not next_beam:
                break
            next_beam.sort(key=lambda x: x[6], reverse=True)
            beam = next_beam[:beam_width]

        results = []
        for did, best_rate in best_rate_by_first.items():
            results.append((best_rate, did, hops_to_first[did]))
        return results

'''
    target_chaining = '    def evaluate_chained_sequences('
    assert target_chaining in text, 'target_chaining not found!'
    text = text.replace(target_chaining, hz_code + target_chaining)

    # 3. Update decide signature to accept t_start: float = 0.0
    text = text.replace(
        '    def decide(self, world: World) -> List[Dict[str, Any]]:',
        '    def decide(self, world: World, t_start: float = 0.0) -> List[Dict[str, Any]]:'
    )

    # 4. Routing logic inside decide: supports both Horizon Planner and Chaining with soft budget
    old_routing = '''            if runner.carrying_loot < runner.max_capacity:
                # Stage 3a: Multi-drop chaining evaluation
                chain_candidates = self.evaluate_chained_sequences(runner, dist_m, prev_m, world, reserved_drop_ids)
                if chain_candidates:
                    for util, did, hops_drop in chain_candidates:
                        if did == self.runner_prev_drop.get(rid):
                            util *= (1.0 + CONFIG["switch_gain"])
                        candidate_pairings.append((util, rid, did, hops_drop))
                else:
                    for drop in world.drops:
                        if drop.node_id == runner.current_node or drop.drop_id in reserved_drop_ids:
                            continue
                        util, hops_drop, hops_safe = self.compute_drop_utility(runner, drop, dist_m, prev_m, world)
                        if util > 0.0:
                            if drop.drop_id == self.runner_prev_drop.get(rid):
                                util *= (1.0 + CONFIG["switch_gain"])
                            candidate_pairings.append((util, rid, drop.drop_id, hops_drop))'''

    new_routing = '''            if runner.carrying_loot < runner.max_capacity:
                chain_candidates = []
                if CONFIG.get("enable_horizon_planner", False):
                    chain_candidates = self.evaluate_horizon_planner(
                        runner, dist_m, prev_m, world, reserved_drop_ids, avg_lambda, t_start
                    )
                if not chain_candidates and CONFIG.get("enable_chaining", True):
                    chain_candidates = self.evaluate_chained_sequences(
                        runner, dist_m, prev_m, world, reserved_drop_ids
                    )
                if chain_candidates:
                    for util, did, hops_drop in chain_candidates:
                        if did == self.runner_prev_drop.get(rid):
                            util *= (1.0 + CONFIG["switch_gain"])
                        candidate_pairings.append((util, rid, did, hops_drop))
                else:
                    for drop in world.drops:
                        if drop.node_id == runner.current_node or drop.drop_id in reserved_drop_ids:
                            continue
                        util, hops_drop, hops_safe = self.compute_drop_utility(runner, drop, dist_m, prev_m, world)
                        if util > 0.0:
                            if drop.drop_id == self.runner_prev_drop.get(rid):
                                util *= (1.0 + CONFIG["switch_gain"])
                            candidate_pairings.append((util, rid, drop.drop_id, hops_drop))'''
    assert old_routing in text, 'old_routing not found!'
    text = text.replace(old_routing, new_routing)

    # 5. Stage F Hard Watchdog in step()
    old_step_call = '            candidate_actions = self.decide(world)'
    new_step_call = '''            if time.perf_counter() - t_start > CONFIG.get("hard_time_limit_s", 0.35):
                # Stage F Emergency Hard Timeout Guard
                fallback_ids = self.known_runner_ids or {r.id for r in world.runners}
                candidate_actions = [{"runner_id": rid, "action": "HOLD"} for rid in sorted(fallback_ids)]
            else:
                candidate_actions = self.decide(world, t_start=t_start)'''
    assert old_step_call in text, 'old_step_call not found!'
    text = text.replace(old_step_call, new_step_call)

    with open("my_bot_v6.py", "w", encoding="utf-8") as f:
        f.write(text)

    print("my_bot_v6.py successfully generated!")

if __name__ == "__main__":
    main()
