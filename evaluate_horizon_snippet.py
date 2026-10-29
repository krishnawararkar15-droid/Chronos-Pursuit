    def evaluate_horizon_planner(
        self,
        runner: Runner,
        dist_m: Dict[int, float],
        prev_m: Dict[int, Optional[int]],
        world: World,
        reserved_drop_ids: Set[int],
        avg_lambda: float,
        t_start: float,
    ) -> List[Tuple[float, int, int]]:
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

        hop_cache: Dict[Tuple[int, int], int] = {}
        def get_hops(u: int, v: int) -> int:
            if u == v:
                return 0
            key = (u, v)
            if key in hop_cache:
                return hop_cache[key]
            p = self.graph_engine.path(u, v)
            h = len(p) - 1 if p else 999
            hop_cache[key] = h
            return h

        # 1. Filter viable first drops
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
        # Top initial candidate drops
        top_initial = first_cands[:8]

        # Candidate pool for chaining: top initial drops PLUS drops geographically close to them
        chain_pool_set = {d.drop_id: d for _, d, _, _, _ in top_initial}
        for _, d1, _, _, _ in top_initial[:4]:
            for d in cands:
                if d.drop_id not in chain_pool_set:
                    if get_hops(d1.node_id, d.node_id) <= 4:
                        chain_pool_set[d.drop_id] = d

        chain_pool = list(chain_pool_set.values())[:12]
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

        # Beam expansion over H ticks
        max_steps = 4
        for step in range(max_steps):
            if time.perf_counter() - t_start > time_limit:
                break
            next_beam = []

            for st_node, st_elapsed, st_carry, st_banked, st_mask, f_did, _ in beam:
                if st_elapsed >= H or world.tick + st_elapsed >= 300:
                    continue

                # Transition 1: Deposit at safehouse
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

                # Transition 2: Chain next drop
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
