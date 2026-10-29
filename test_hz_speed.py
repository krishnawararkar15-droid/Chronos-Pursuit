#!/usr/bin/env python3
import json
import time
from Subway_Escape.practice_arena.practice_arena import PracticeArena
import my_bot
from my_bot import Adapter, World, RiskModel, Runner, Drop

# Read a tick state from debug.log
with open("debug.log") as f:
    lines = [line.strip() for line in f if line.strip()]

state = json.loads(lines[0])
world = Adapter.parse_world(state)
engine = my_bot.BotEngine()
engine.graph_engine.update_world(world)

runner = world.runners[0]
risk_model = RiskModel(world.police)
dist_m, prev_m = engine.graph_engine.dijkstra_risk(runner.current_node, risk_model, runner.carrying_loot)

# Test horizon planner speed
from eval_horizon_standalone import plan_horizon
t0 = time.perf_counter()
for _ in range(50):
    plan_horizon(
        runner_node=runner.current_node,
        carrying_loot=runner.carrying_loot,
        max_capacity=runner.max_capacity,
        world_tick=world.tick,
        ticks_left=world.ticks_left,
        drops=world.drops,
        safehouses=world.safehouses,
        graph_engine=engine.graph_engine,
        dist_m=dist_m,
        prev_m=prev_m,
        prev_drop_id=None,
        H=40,
        beam_width=30
    )
dt = (time.perf_counter() - t0) / 50 * 1000.0
print(f"plan_horizon execution time: {dt:.2f} ms per call")
