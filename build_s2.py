with open("my_bot.py", "r", encoding="utf-8") as f:
    text = f.read()

# 1. Update CONFIG
text = text.replace(
    '"enable_horizon_planner": False,',
    '"enable_idle_positioning": True,\n    "enable_horizon_planner": False,'
)

# 2. Add attributes in BotEngine.__init__
old_init = '''        self.runner_prev_drop: Dict[int, Optional[int]] = {}
        self.runner_prev_utility: Dict[int, float] = {}'''

new_init = '''        self.runner_prev_drop: Dict[int, Optional[int]] = {}
        self.runner_prev_utility: Dict[int, float] = {}
        self.seen_drop_ids: Set[int] = set()
        self.spot_drop_count: Dict[int, int] = {}
        self.spot_total_value: Dict[int, float] = {}'''
assert old_init in text, 'old_init not found'
text = text.replace(old_init, new_init)

# 3. Add update_spawn_stats and find_best_idle_position methods before decide()
methods_code = '''    def update_spawn_stats(self, world: World) -> None:
        for d in world.drops:
            if d.drop_id not in self.seen_drop_ids:
                self.seen_drop_ids.add(d.drop_id)
                self.spot_drop_count[d.node_id] = self.spot_drop_count.get(d.node_id, 0) + 1
                self.spot_total_value[d.node_id] = self.spot_total_value.get(d.node_id, 0.0) + d.initial_value

    def find_best_idle_position(
        self,
        runner: Runner,
        dist_m: Dict[int, float],
        prev_m: Dict[int, Optional[int]],
        world: World,
    ) -> Optional[int]:
        if world.ticks_left <= 25 or runner.carrying_loot > 0:
            return None
        if not self.spot_drop_count:
            return None

        best_node = None
        best_score = -1.0
        curr_tick = max(1, world.tick)

        for node_id, count in self.spot_drop_count.items():
            if node_id not in dist_m or dist_m[node_id] == INF or dist_m[node_id] >= 1e5:
                continue
            p = self.graph_engine.path(runner.current_node, node_id, prev=prev_m)
            h_to = len(p) - 1 if p else 999
            if h_to >= 15:
                continue

            min_h_safe = 999
            for s in world.safehouses:
                d_s = self.graph_engine.static_dist(node_id, s)
                if d_s != INF:
                    h_s = int(round(d_s / 35.0))
                    if h_s < min_h_safe:
                        min_h_safe = h_s

            if h_to + min_h_safe + 5 > world.ticks_left:
                continue

            val_sum = self.spot_total_value.get(node_id, 100.0)
            expected_remaining = (val_sum / curr_tick) * world.ticks_left
            score = expected_remaining / (h_to + min_h_safe + 2)

            if score > best_score:
                best_score = score
                best_node = node_id

        return best_node

'''
target_decide = '    def decide('
assert target_decide in text, 'target_decide not found'
text = text.replace(target_decide, methods_code + target_decide)

# 4. In decide(), call update_spawn_stats and apply idle positioning
call_update = '''        risk_model = RiskModel(world.police)
        self.update_spawn_stats(world)'''
text = text.replace('        risk_model = RiskModel(world.police)', call_update)

old_hold = '''            else:
                assigned_targets[rid] = ("HOLD", None)
                self.runner_prev_drop[rid] = None
                self.runner_prev_utility[rid] = 0.0'''

new_hold = '''            else:
                if CONFIG.get("enable_idle_positioning", False):
                    best_pos_node = self.find_best_idle_position(runner, dist_m, prev_m, world)
                    if best_pos_node is not None:
                        assigned_targets[rid] = ("POSITION", best_pos_node)
                    else:
                        assigned_targets[rid] = ("HOLD", None)
                else:
                    assigned_targets[rid] = ("HOLD", None)
                self.runner_prev_drop[rid] = None
                self.runner_prev_utility[rid] = 0.0'''
assert old_hold in text, 'old_hold not found'
text = text.replace(old_hold, new_hold)

with open("my_bot_s2.py", "w", encoding="utf-8") as f:
    f.write(text)

print("my_bot_s2.py built successfully.")
