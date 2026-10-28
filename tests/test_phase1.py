#!/usr/bin/env python3
"""
Unit tests and Fuzzing for Phase 1: Robust I/O Shell + Adapter + Validator.
Fuzzes the bot engine with 200 corrupted, malformed, empty, and partial states.
Verifies zero crashes, valid JSON output, and strict invariant adherence.
"""

import json
import math
import os
import random
import sys
import unittest

# Add submission directory to path
SUBMISSION_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Subway_Escape", "submission"))
sys.path.insert(0, SUBMISSION_DIR)

from my_bot import Adapter, BotEngine, Validator, INF, VALID_ACTIONS


class TestPhase1(unittest.TestCase):
    def setUp(self):
        self.engine = BotEngine()

    def test_real_sample_state(self):
        sample_state = {
            "tick": 12,
            "graph_nodes": [
                {"id": 1, "x": 52.4, "y": 310.9, "type": "safehouse"},
                {"id": 6, "x": 188.0, "y": 97.2, "type": "money_spot"},
                {"id": 20, "x": 240.5, "y": 401.7, "type": "junction"},
            ],
            "graph_edges": [
                {"from": 1, "to": 20, "base_weight": 93.4, "current_weight": 96.1},
                {"from": 20, "to": 6, "base_weight": 55.0, "current_weight": -1.0},
            ],
            "my_runners": [
                {
                    "id": 1,
                    "current_node": 20,
                    "x": 240.5,
                    "y": 401.7,
                    "carrying_loot": 270.5,
                    "max_capacity": 500.0,
                    "status": "ACTIVE",
                    "stun_ticks_remaining": 0,
                }
            ],
            "active_money_drops": [
                {
                    "drop_id": 1012,
                    "node_id": 6,
                    "target_safehouse_node": 1,
                    "current_value": 412.8,
                    "leak_lambda": 0.011,
                    "ttl_remaining": 47,
                }
            ],
            "police_officers": [
                {"id": 1, "x": 200.2, "y": 130.0, "vx": 2.1, "vy": -0.8, "radius": 15.0}
            ],
        }
        actions = self.engine.step(sample_state)
        self.assertIsInstance(actions, list)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["runner_id"], 1)
        self.assertIn(actions[0]["action"], VALID_ACTIONS)

    def test_adapter_weight_parsing(self):
        self.assertEqual(Adapter._parse_weight(10.5), 10.5)
        self.assertEqual(Adapter._parse_weight(0), 0.0)
        self.assertEqual(Adapter._parse_weight(-1.0), INF)
        self.assertEqual(Adapter._parse_weight(None), INF)
        self.assertEqual(Adapter._parse_weight(float("nan")), INF)
        self.assertEqual(Adapter._parse_weight(float("inf")), INF)
        self.assertEqual(Adapter._parse_weight("inf"), INF)
        self.assertEqual(Adapter._parse_weight("-1"), INF)
        self.assertEqual(Adapter._parse_weight(1e12), INF)
        self.assertEqual(Adapter._parse_weight("42.5"), 42.5)

    def test_empty_state_resilience(self):
        # Empty dict should not crash
        actions = self.engine.step({})
        self.assertIsInstance(actions, list)
        self.assertTrue(len(actions) >= 1)
        self.assertEqual(actions[0]["action"], "HOLD")

    def test_validator_downgrades_illegal_actions(self):
        world = Adapter.parse_world({
            "tick": 1,
            "graph_nodes": [
                {"id": 1, "x": 0, "y": 0, "type": "junction"},
                {"id": 2, "x": 10, "y": 10, "type": "safehouse"},
            ],
            "graph_edges": [
                {"from": 1, "to": 2, "base_weight": 10, "current_weight": -1.0}, # Blocked!
            ],
            "my_runners": [
                {"id": 1, "current_node": 1, "carrying_loot": 0, "status": "ACTIVE"},
            ],
        })
        # Attempt illegal traverse to blocked node 2
        bad_action = [{"runner_id": 1, "action": "TRAVERSE", "target_node": 2}]
        res = Validator.validate_actions(bad_action, world, {1})
        self.assertEqual(res[0]["action"], "HOLD")

        # Attempt illegal deposit at junction 1
        bad_deposit = [{"runner_id": 1, "action": "DEPOSIT"}]
        res2 = Validator.validate_actions(bad_deposit, world, {1})
        self.assertEqual(res2[0]["action"], "HOLD")

        # Attempt illegal collect when no drop exists
        bad_collect = [{"runner_id": 1, "action": "COLLECT"}]
        res3 = Validator.validate_actions(bad_collect, world, {1})
        self.assertEqual(res3[0]["action"], "HOLD")

    def test_fuzzing_200_corrupted_states(self):
        """Fuzz with 200 random malformed, corrupted, and edge-case states."""
        rng = random.Random(1337)
        keys_pool = ["tick", "graph_nodes", "graph_edges", "my_runners", "active_money_drops", "police_officers"]

        for i in range(200):
            corrupted: dict = {}
            # Random subset of keys
            num_keys = rng.randint(0, len(keys_pool))
            chosen_keys = rng.sample(keys_pool, num_keys)

            for k in chosen_keys:
                noise_type = rng.choice(["none", "empty_list", "garbage_str", "int", "float", "corrupt_items"])
                if noise_type == "none":
                    corrupted[k] = None
                elif noise_type == "empty_list":
                    corrupted[k] = []
                elif noise_type == "garbage_str":
                    corrupted[k] = "CORRUPTED_STRING_DATA"
                elif noise_type == "int":
                    corrupted[k] = rng.randint(-1000, 1000)
                elif noise_type == "float":
                    corrupted[k] = rng.choice([float("nan"), float("inf"), -1.0, 0.0, 99999.9])
                elif noise_type == "corrupt_items":
                    # Generate item list with bad keys, missing values, string types
                    corrupted[k] = [
                        {"id": "not_an_int", "x": None, "current_weight": "bad"},
                        None,
                        42,
                        {},
                        {"from": None, "to": 9999, "base_weight": -5},
                    ]

            # Feed to engine
            actions = self.engine.step(corrupted)

            # Assert invariants
            self.assertIsInstance(actions, list, f"Fuzz iteration {i} failed to return a list")
            self.assertTrue(len(actions) >= 1, f"Fuzz iteration {i} returned empty actions list")
            for act in actions:
                self.assertIsInstance(act, dict)
                self.assertIn("runner_id", act)
                self.assertIn("action", act)
                self.assertIn(act["action"], VALID_ACTIONS)
                # Verify JSON serializability
                serialized = json.dumps({"runner_actions": [act]})
                deserialized = json.loads(serialized)
                self.assertIn("runner_actions", deserialized)


if __name__ == "__main__":
    unittest.main()
