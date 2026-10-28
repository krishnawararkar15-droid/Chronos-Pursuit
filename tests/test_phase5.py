#!/usr/bin/env python3
"""
Unit tests for Phase 5: Space-Time Risk Model & Collision Avoidance.
"""

import math
import os
import sys
import unittest

SUBMISSION_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Subway_Escape", "submission"))
sys.path.insert(0, SUBMISSION_DIR)

from my_bot import BotEngine, GraphEngine, Node, Police, RiskModel, World, INF


class TestPhase5RiskModel(unittest.TestCase):
    def test_trajectory_prediction_clamping(self):
        cop = Police(id=1, x=450.0, y=100.0, vx=20.0, vy=0.0, radius=15.0)
        rm = RiskModel([cop], world_size=500.0)

        # At k=0: (450, 100)
        p0 = rm.get_police_pred(1, 0)
        self.assertAlmostEqual(p0[0], 450.0)
        self.assertAlmostEqual(p0[1], 100.0)

        # At k=5: 450 + 100 = 550, clamped to 490.0
        p5 = rm.get_police_pred(1, 5)
        self.assertAlmostEqual(p5[0], 490.0)

    def test_point_hit_risk(self):
        cop = Police(id=1, x=100.0, y=100.0, vx=0.0, vy=0.0, radius=15.0)
        rm = RiskModel([cop], world_size=500.0)

        # Directly inside capture radius (dist = 10 <= 15)
        hit_inside = rm.point_hit_risk(100.0, 110.0, 0)
        self.assertEqual(hit_inside, 1.0)

        # In safety buffer (dist = 18, radius = 15, margin = 8 -> danger = 23)
        hit_buffer = rm.point_hit_risk(100.0, 118.0, 0)
        self.assertTrue(0.0 < hit_buffer < 1.0)

        # Completely outside (dist = 50 >= 23)
        hit_safe = rm.point_hit_risk(100.0, 150.0, 0)
        self.assertEqual(hit_safe, 0.0)

    def test_risk_augmented_dijkstra_avoids_police(self):
        # Path 1: 1 -> 2 -> 4 (dist = 110, but node 2 is inside cop radius at k=1)
        # Path 2: 1 -> 3 -> 4 (dist = 110, safe from cop)
        nodes = {
            1: Node(1, 100, 100, "junction"),
            2: Node(2, 130, 100, "junction"),
            3: Node(3, 100, 180, "junction"),
            4: Node(4, 130, 180, "junction"),
        }
        edges = []
        world = World(0, 300, nodes, edges, {}, [], [], [], [], [])
        engine = GraphEngine(world)
        engine.adj_current = {
            1: [(2, 30.0), (3, 80.0)],
            2: [(4, 80.0), (1, 30.0)],
            3: [(4, 30.0), (1, 80.0)],
            4: [(2, 80.0), (3, 30.0)],
        }
        # Cop is sitting at node 2 (130, 100)
        cop = Police(1, 130.0, 100.0, 0.0, 0.0, radius=15.0)
        rm = RiskModel([cop])

        dist, prev = engine.dijkstra_risk(1, rm, carried_loot=200.0)
        # Path to 4 should avoid node 2 and go via node 3
        path_to_4 = engine.path(1, 4, prev=prev)
        self.assertEqual(path_to_4, [1, 3, 4])


if __name__ == "__main__":
    unittest.main()
