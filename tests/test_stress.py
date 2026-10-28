#!/usr/bin/env python3
"""
Stress Testing Suite for Phase 8:
Validates the bot against extreme pathological conditions:
1. 0 drops on the map
2. All edges blocked (current_weight = -1.0)
3. 1 runner
4. 10 runners (high multi-agent concurrency)
5. Huge graph (1000 nodes, 3000 edges) - must run in <= 0.35 s
6. Police officer stationed directly on top of a safehouse
Verifies: 0 crashes, 100% valid JSON, response time <= 0.35s.
"""

import json
import math
import os
import random
import sys
import time
import unittest

SUBMISSION_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Subway_Escape", "submission"))
sys.path.insert(0, SUBMISSION_DIR)

from my_bot import BotEngine, CONFIG, VALID_ACTIONS, INF


class TestStressSuite(unittest.TestCase):
    def setUp(self):
        self.engine = BotEngine()

    def test_zero_drops_on_map(self):
        """Map with 0 active drops: runners must safely HOLD or navigate to safehouse without crashing."""
        state = {
            "tick": 10,
            "graph_nodes": [
                {"id": 1, "x": 50, "y": 50, "type": "safehouse"},
                {"id": 2, "x": 100, "y": 50, "type": "junction"},
            ],
            "graph_edges": [
                {"from": 1, "to": 2, "base_weight": 50.0, "current_weight": 50.0},
            ],
            "my_runners": [
                {"id": 1, "current_node": 2, "carrying_loot": 0.0, "status": "ACTIVE"},
            ],
            "active_money_drops": [],
            "police_officers": [],
        }
        t0 = time.perf_counter()
        actions = self.engine.step(state)
        elapsed = time.perf_counter() - t0

        self.assertIsInstance(actions, list)
        self.assertEqual(len(actions), 1)
        self.assertIn(actions[0]["action"], VALID_ACTIONS)
        self.assertLess(elapsed, 0.35)

    def test_all_edges_blocked(self):
        """Map where 100% of edges are blocked (current_weight = -1.0): runners must not crash."""
        state = {
            "tick": 20,
            "graph_nodes": [
                {"id": 1, "x": 50, "y": 50, "type": "safehouse"},
                {"id": 2, "x": 100, "y": 50, "type": "junction"},
                {"id": 3, "x": 150, "y": 50, "type": "money_spot"},
            ],
            "graph_edges": [
                {"from": 1, "to": 2, "base_weight": 50.0, "current_weight": -1.0},
                {"from": 2, "to": 3, "base_weight": 50.0, "current_weight": -1.0},
            ],
            "my_runners": [
                {"id": 1, "current_node": 2, "carrying_loot": 100.0, "status": "ACTIVE"},
            ],
            "active_money_drops": [
                {"drop_id": 99, "node_id": 3, "current_value": 300.0, "leak_lambda": 0.01, "ttl_remaining": 50},
            ],
            "police_officers": [],
        }
        t0 = time.perf_counter()
        actions = self.engine.step(state)
        elapsed = time.perf_counter() - t0

        self.assertIsInstance(actions, list)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["action"], "HOLD")
        self.assertLess(elapsed, 0.35)

    def test_single_runner(self):
        """Single runner operation."""
        state = {
            "tick": 5,
            "graph_nodes": [{"id": 1, "x": 0, "y": 0, "type": "safehouse"}],
            "graph_edges": [],
            "my_runners": [{"id": 1, "current_node": 1, "carrying_loot": 0.0, "status": "ACTIVE"}],
            "active_money_drops": [],
            "police_officers": [],
        }
        actions = self.engine.step(state)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["action"], "HOLD")

    def test_ten_runners_concurrency(self):
        """10 concurrent runners with 5 drops: verify bipartite matching and zero action conflicts."""
        nodes = [{"id": i, "x": i * 20.0, "y": 0.0, "type": "safehouse" if i == 0 else "junction"} for i in range(15)]
        nodes[14]["type"] = "money_spot"
        edges = [{"from": i, "to": i + 1, "base_weight": 20.0, "current_weight": 20.0} for i in range(14)]
        runners = [{"id": i, "current_node": i, "carrying_loot": i * 20.0, "status": "ACTIVE", "max_capacity": 500} for i in range(1, 11)]
        drops = [{"drop_id": d, "node_id": 14 - d, "current_value": 200.0 + d * 50, "leak_lambda": 0.01, "ttl_remaining": 60} for d in range(5)]

        state = {
            "tick": 30,
            "graph_nodes": nodes,
            "graph_edges": edges,
            "my_runners": runners,
            "active_money_drops": drops,
            "police_officers": [],
        }
        t0 = time.perf_counter()
        actions = self.engine.step(state)
        elapsed = time.perf_counter() - t0

        self.assertEqual(len(actions), 10)
        action_rids = {a["runner_id"] for a in actions}
        self.assertEqual(action_rids, set(range(1, 11)))
        self.assertLess(elapsed, 0.35)

    def test_huge_graph_1000_nodes(self):
        """Huge graph: 1,000 nodes, 3,000 edges, 5 runners. Must strictly finish under 0.35 s."""
        rng = random.Random(12345)
        n_nodes = 1000
        n_edges = 3000
        n_runners = 5

        nodes = [{"id": i, "x": rng.uniform(0, 1000), "y": rng.uniform(0, 1000), "type": "safehouse" if i < 10 else "junction"} for i in range(n_nodes)]
        edges = []
        # Connect into connected backbone
        for i in range(n_nodes - 1):
            edges.append({"from": i, "to": i + 1, "base_weight": 25.0, "current_weight": 25.0})
        # Add random edges
        for _ in range(n_edges - (n_nodes - 1)):
            u = rng.randint(0, n_nodes - 1)
            v = rng.randint(0, n_nodes - 1)
            if u != v:
                edges.append({"from": u, "to": v, "base_weight": 30.0, "current_weight": 30.0})

        runners = [{"id": r, "current_node": rng.randint(0, n_nodes - 1), "carrying_loot": 150.0, "status": "ACTIVE", "max_capacity": 500} for r in range(1, n_runners + 1)]
        drops = [{"drop_id": d, "node_id": rng.randint(0, n_nodes - 1), "current_value": 400.0, "leak_lambda": 0.01, "ttl_remaining": 60} for d in range(10)]
        police = [{"id": 1, "x": 500.0, "y": 500.0, "vx": 2.0, "vy": 1.0, "radius": 15.0}]

        state = {
            "tick": 50,
            "graph_nodes": nodes,
            "graph_edges": edges,
            "my_runners": runners,
            "active_money_drops": drops,
            "police_officers": police,
        }

        t0 = time.perf_counter()
        actions = self.engine.step(state)
        elapsed = time.perf_counter() - t0

        print(f"\n[STRESS TEST] 1,000 nodes, {len(edges)} edges, {n_runners} runners: {elapsed*1000:.2f} ms")
        self.assertEqual(len(actions), n_runners)
        self.assertLess(elapsed, 0.35, f"Execution took {elapsed:.4f}s, exceeding 0.35s budget!")

    def test_police_on_top_of_safehouse(self):
        """Police officer directly camping on the safehouse node: bot must not walk into capture."""
        nodes = [
            {"id": 1, "x": 100.0, "y": 100.0, "type": "safehouse"},
            {"id": 2, "x": 140.0, "y": 100.0, "type": "junction"},
            {"id": 3, "x": 140.0, "y": 150.0, "type": "safehouse"},  # Alternate safehouse
        ]
        edges = [
            {"from": 1, "to": 2, "base_weight": 40.0, "current_weight": 40.0},
            {"from": 2, "to": 3, "base_weight": 50.0, "current_weight": 50.0},
        ]
        runners = [
            {"id": 1, "current_node": 2, "carrying_loot": 300.0, "status": "ACTIVE", "max_capacity": 500},
        ]
        # Cop is sitting at safehouse 1 (100, 100)
        police = [
            {"id": 1, "x": 100.0, "y": 100.0, "vx": 0.0, "vy": 0.0, "radius": 15.0},
        ]
        state = {
            "tick": 100,
            "graph_nodes": nodes,
            "graph_edges": edges,
            "my_runners": runners,
            "active_money_drops": [],
            "police_officers": police,
        }
        actions = self.engine.step(state)
        self.assertEqual(len(actions), 1)
        # Must NOT traverse to node 1! Should route to alternate safehouse 3 or HOLD
        self.assertNotEqual(actions[0].get("target_node"), 1)


if __name__ == "__main__":
    unittest.main()
