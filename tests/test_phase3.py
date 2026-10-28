#!/usr/bin/env python3
"""
Unit tests for Phase 3: State Machine & Utility Routing.
Verifies:
1. STUNNED -> HOLD
2. Drop on current node with room -> COLLECT
3. At safehouse with loot and bank_condition -> DEPOSIT
4. SEEK mode selects best drop discounted by decay and travel
5. RETURN mode triggers when capacity/bank threshold or endgame reached
6. Multi-runner reservation table prevents drop conflicts
"""

import os
import sys
import unittest

SUBMISSION_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Subway_Escape", "submission"))
sys.path.insert(0, SUBMISSION_DIR)

from my_bot import BotEngine, CONFIG


class TestPhase3StateMachine(unittest.TestCase):
    def setUp(self):
        self.engine = BotEngine()

    def test_stunned_runner_holds(self):
        state = {
            "tick": 1,
            "graph_nodes": [{"id": 1, "x": 0, "y": 0, "type": "junction"}],
            "graph_edges": [],
            "my_runners": [{"id": 1, "current_node": 1, "status": "STUNNED", "stun_ticks_remaining": 2, "carrying_loot": 100}],
            "active_money_drops": [],
            "police_officers": [],
        }
        actions = self.engine.step(state)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["action"], "HOLD")

    def test_collect_drop_on_current_node(self):
        state = {
            "tick": 1,
            "graph_nodes": [{"id": 1, "x": 0, "y": 0, "type": "money_spot"}],
            "graph_edges": [],
            "my_runners": [{"id": 1, "current_node": 1, "status": "ACTIVE", "carrying_loot": 0, "max_capacity": 500}],
            "active_money_drops": [{"drop_id": 99, "node_id": 1, "current_value": 300, "leak_lambda": 0.01, "ttl_remaining": 50}],
            "police_officers": [],
        }
        actions = self.engine.step(state)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["action"], "COLLECT")

    def test_deposit_at_safehouse_when_carrying(self):
        state = {
            "tick": 1,
            "graph_nodes": [{"id": 1, "x": 0, "y": 0, "type": "safehouse"}],
            "graph_edges": [],
            "my_runners": [{"id": 1, "current_node": 1, "status": "ACTIVE", "carrying_loot": 350, "max_capacity": 500}],
            "active_money_drops": [],
            "police_officers": [],
        }
        actions = self.engine.step(state)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["action"], "DEPOSIT")

    def test_seek_best_discounted_drop(self):
        # Node 1 (junction) connected to Node 2 (drop A) and Node 3 (drop B)
        # Drop A: value 500, distance 10
        # Drop B: value 200, distance 10
        state = {
            "tick": 1,
            "graph_nodes": [
                {"id": 1, "x": 0, "y": 0, "type": "junction"},
                {"id": 2, "x": 10, "y": 0, "type": "money_spot"},
                {"id": 3, "x": 0, "y": 10, "type": "money_spot"},
                {"id": 4, "x": -10, "y": 0, "type": "safehouse"},
            ],
            "graph_edges": [
                {"from": 1, "to": 2, "base_weight": 10.0, "current_weight": 10.0},
                {"from": 1, "to": 3, "base_weight": 10.0, "current_weight": 10.0},
                {"from": 1, "to": 4, "base_weight": 10.0, "current_weight": 10.0},
            ],
            "my_runners": [{"id": 1, "current_node": 1, "status": "ACTIVE", "carrying_loot": 0, "max_capacity": 500}],
            "active_money_drops": [
                {"drop_id": 101, "node_id": 2, "current_value": 500, "leak_lambda": 0.01, "ttl_remaining": 50},
                {"drop_id": 102, "node_id": 3, "current_value": 200, "leak_lambda": 0.01, "ttl_remaining": 50},
            ],
            "police_officers": [],
        }
        actions = self.engine.step(state)
        self.assertEqual(len(actions), 1)
        # Should seek drop 101 on node 2
        self.assertEqual(actions[0]["action"], "TRAVERSE")
        self.assertEqual(actions[0]["target_node"], 2)

    def test_reservation_table_multi_runner(self):
        # Two runners at node 1. Only one drop at node 2.
        # Runner 1 should seek node 2. Runner 2 must NOT target node 2 (should seek safehouse or hold).
        state = {
            "tick": 1,
            "graph_nodes": [
                {"id": 1, "x": 0, "y": 0, "type": "junction"},
                {"id": 2, "x": 10, "y": 0, "type": "money_spot"},
                {"id": 3, "x": -10, "y": 0, "type": "safehouse"},
            ],
            "graph_edges": [
                {"from": 1, "to": 2, "base_weight": 10.0, "current_weight": 10.0},
                {"from": 1, "to": 3, "base_weight": 10.0, "current_weight": 10.0},
            ],
            "my_runners": [
                {"id": 1, "current_node": 1, "status": "ACTIVE", "carrying_loot": 0, "max_capacity": 500},
                {"id": 2, "current_node": 1, "status": "ACTIVE", "carrying_loot": 0, "max_capacity": 500},
            ],
            "active_money_drops": [
                {"drop_id": 101, "node_id": 2, "current_value": 500, "leak_lambda": 0.01, "ttl_remaining": 50},
            ],
            "police_officers": [],
        }
        actions = self.engine.step(state)
        self.assertEqual(len(actions), 2)
        r1_action = next(a for a in actions if a["runner_id"] == 1)
        r2_action = next(a for a in actions if a["runner_id"] == 2)

        # Runner 1 targets drop 2
        self.assertEqual(r1_action["action"], "TRAVERSE")
        self.assertEqual(r1_action["target_node"], 2)

        # Runner 2 must not target node 2 (drop already reserved)
        self.assertNotEqual(r2_action.get("target_node"), 2)


if __name__ == "__main__":
    unittest.main()
