#!/usr/bin/env python3
"""
Unit tests for Phase 6 (Economics & Optimal Stopping) and Phase 7 (Multi-Runner Coordination & Endgame).
"""

import math
import os
import sys
import unittest

SUBMISSION_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Subway_Escape", "submission"))
sys.path.insert(0, SUBMISSION_DIR)

from my_bot import BotEngine, Drop, Node, Police, RiskModel, Runner, World, CONFIG, INF


class TestPhase6And7(unittest.TestCase):
    def setUp(self):
        self.engine = BotEngine()

    def test_dynamic_bank_threshold_from_lambda(self):
        nodes = {1: Node(1, 0, 0, "junction"), 2: Node(2, 50, 0, "safehouse")}
        runner = Runner(1, 1, 0, 0, carrying_loot=250.0, max_capacity=500, status="ACTIVE", stun_ticks_remaining=0)
        world = World(0, 300, nodes, [], {}, [runner], [], [], [2], [])

        # High lambda (0.02) -> threshold is low (~180) -> carrying 250 triggers bank_now
        self.assertTrue(self.engine.bank_now_test(runner, best_drop_utility=10.0, hops_to_safe=2, world=world, avg_lambda=0.02))

        # Low lambda (0.005) -> threshold is high (~420) -> carrying 250 does NOT trigger bank_now if utility is good
        self.assertFalse(self.engine.bank_now_test(runner, best_drop_utility=50.0, hops_to_safe=2, world=world, avg_lambda=0.005))

    def test_opportunistic_banking(self):
        # Runner is at node 1 (safehouse) with 80 loot
        nodes = {1: Node(1, 0, 0, "safehouse")}
        runner = Runner(1, 1, 0, 0, carrying_loot=80.0, max_capacity=500, status="ACTIVE", stun_ticks_remaining=0)
        world = World(10, 290, nodes, [], {}, [runner], [], [], [1], [])
        self.engine.graph_engine.update_world(world)

        actions = self.engine.decide(world)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["action"], "DEPOSIT")

    def test_endgame_drainage_enforcement(self):
        # At tick 295 (ticks_left = 5). Safehouse is at node 2 (1 hop away).
        # Runner has 200 loot. A lucrative drop exists at node 3 (1 hop away).
        # In endgame, runner must return to safehouse 2, NOT seek drop 3!
        nodes = {
            1: Node(1, 0, 0, "junction"),
            2: Node(2, 10, 0, "safehouse"),
            3: Node(3, -10, 0, "money_spot"),
        }
        edges = []
        runner = Runner(1, 1, 0, 0, carrying_loot=200.0, max_capacity=500, status="ACTIVE", stun_ticks_remaining=0)
        drop = Drop(drop_id=1, node_id=3, target_safehouse=2, current_value=900.0, leak_lambda=0.01, ttl_remaining=50)
        world = World(295, 5, nodes, edges, {}, [runner], [drop], [], [2], [3])
        self.engine.graph_engine.update_world(world)
        self.engine.graph_engine.adj_current = {
            1: [(2, 10.0), (3, 10.0)],
            2: [(1, 10.0)],
            3: [(1, 10.0)],
        }

        actions = self.engine.decide(world)
        self.assertEqual(len(actions), 1)
        # Must return to safehouse 2
        self.assertEqual(actions[0]["action"], "TRAVERSE")
        self.assertEqual(actions[0]["target_node"], 2)

    def test_panic_deposit_on_safehouse(self):
        # Runner is standing on safehouse 1 with 150 loot.
        # Cop is rushing directly to capture runner next tick!
        nodes = {1: Node(1, 100, 100, "safehouse")}
        runner = Runner(1, 1, 100, 100, carrying_loot=150.0, max_capacity=500, status="ACTIVE", stun_ticks_remaining=0)
        # Cop at (105, 100) within radius 15
        cop = Police(1, 105.0, 100.0, 0.0, 0.0, radius=15.0)
        world = World(10, 290, nodes, [], {}, [runner], [], [cop], [1], [])
        self.engine.graph_engine.update_world(world)

        actions = self.engine.decide(world)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["action"], "DEPOSIT")


if __name__ == "__main__":
    unittest.main()
