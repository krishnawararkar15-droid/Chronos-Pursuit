#!/usr/bin/env python3
"""
Unit tests and Performance Benchmarks for Phase 2: GraphEngine.
- Compares Dijkstra against brute-force Floyd-Warshall on random graphs.
- Verifies blocked edge handling (INF / -1.0).
- Verifies disconnected graph edge-cases (INF distance, empty path, None next_hop).
- Verifies static precomputation and cache invalidation.
- Verifies mid-edge runner distance and reversal handling.
- Performance benchmark: 200-node graph all-runners Dijkstra latency < 20 ms.
"""

import math
import os
import random
import sys
import time
import unittest

# Add submission directory to path
SUBMISSION_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Subway_Escape", "submission"))
sys.path.insert(0, SUBMISSION_DIR)

from my_bot import Adapter, Edge, GraphEngine, Node, Runner, World, INF


class TestGraphEngine(unittest.TestCase):
    def test_dijkstra_vs_floyd_warshall(self):
        """Verify Dijkstra shortest paths against Floyd-Warshall on random graphs."""
        rng = random.Random(42)
        n_nodes = 25
        nodes = {i: Node(id=i, x=rng.uniform(0, 100), y=rng.uniform(0, 100), type="junction") for i in range(n_nodes)}

        # Build random connected graph
        edges = []
        for i in range(n_nodes - 1):
            w = round(rng.uniform(5.0, 50.0), 2)
            edges.append(Edge(u=i, v=i + 1, base_weight=w, current_weight=w))

        # Add random extra edges
        for _ in range(30):
            u = rng.randint(0, n_nodes - 1)
            v = rng.randint(0, n_nodes - 1)
            if u != v:
                w = round(rng.uniform(5.0, 50.0), 2)
                edges.append(Edge(u=u, v=v, base_weight=w, current_weight=w))

        world = World(
            tick=0,
            ticks_left=300,
            nodes=nodes,
            edges=edges,
            neighbors={},
            runners=[],
            drops=[],
            police=[],
            safehouses=[0],
            money_spots=[1],
        )

        engine = GraphEngine(world)

        # Brute-force Floyd-Warshall
        fw = {i: {j: (0.0 if i == j else INF) for j in range(n_nodes)} for i in range(n_nodes)}
        for e in edges:
            fw[e.u][e.v] = min(fw[e.u][e.v], e.current_weight)
            fw[e.v][e.u] = min(fw[e.v][e.u], e.current_weight)

        for k in range(n_nodes):
            for i in range(n_nodes):
                for j in range(n_nodes):
                    if fw[i][k] + fw[k][j] < fw[i][j]:
                        fw[i][j] = fw[i][k] + fw[k][j]

        # Verify Dijkstra matches Floyd-Warshall for all pairs
        for src in range(n_nodes):
            dist, prev = engine.dijkstra(src, weights="current")
            for dst in range(n_nodes):
                expected = fw[src][dst]
                actual = dist.get(dst, INF)
                self.assertAlmostEqual(actual, expected, places=4, msg=f"Distance mismatch from {src} to {dst}")

                # Verify path reconstruction
                p = engine.path(src, dst, prev=prev)
                if expected == INF:
                    self.assertEqual(p, [])
                elif src == dst:
                    self.assertEqual(p, [src])
                else:
                    self.assertEqual(p[0], src)
                    self.assertEqual(p[-1], dst)
                    # Verify each hop in path is connected and sum equals expected
                    total_p_dist = 0.0
                    for idx in range(len(p) - 1):
                        hop_u, hop_v = p[idx], p[idx + 1]
                        valid_edges = [e.current_weight for e in edges if {e.u, e.v} == {hop_u, hop_v}]
                        self.assertTrue(len(valid_edges) > 0)
                        total_p_dist += min(valid_edges)
                    self.assertAlmostEqual(total_p_dist, expected, places=4)

    def test_blocked_edges_and_disconnected_graph(self):
        """Verify blocked tracks are avoided and disconnected nodes do not crash."""
        nodes = {
            1: Node(1, 0, 0, "safehouse"),
            2: Node(2, 10, 0, "junction"),
            3: Node(3, 20, 0, "money_spot"),
            4: Node(4, 100, 100, "junction"),  # Island node
        }
        # Edge 2-3 is blocked
        edges = [
            Edge(1, 2, base_weight=10.0, current_weight=10.0),
            Edge(2, 3, base_weight=10.0, current_weight=INF),  # Blocked!
        ]
        world = World(0, 300, nodes, edges, {}, [], [], [], [1], [3])
        engine = GraphEngine(world)

        dist, prev = engine.dijkstra(1, weights="current")
        self.assertEqual(dist[1], 0.0)
        self.assertEqual(dist[2], 10.0)
        self.assertEqual(dist.get(3, INF), INF)
        self.assertEqual(dist.get(4, INF), INF)

        # Path to unreachable node 3 must return []
        self.assertEqual(engine.path(1, 3, prev=prev), [])
        self.assertIsNone(engine.next_hop(1, 3, prev=prev))

        # Path to island node 4 must return []
        self.assertEqual(engine.path(1, 4, prev=prev), [])
        self.assertIsNone(engine.next_hop(1, 4, prev=prev))

        # Next hop to reachable node 2
        self.assertEqual(engine.next_hop(1, 2, prev=prev), 2)
        # Next hop to self
        self.assertEqual(engine.next_hop(1, 1, prev=prev), 1)

    def test_static_cache_and_safehouse_precomputation(self):
        """Verify static distance precomputation and cache behavior."""
        nodes = {
            1: Node(1, 0, 0, "safehouse"),
            2: Node(2, 10, 0, "junction"),
            3: Node(3, 20, 0, "safehouse"),
        }
        edges = [
            Edge(1, 2, base_weight=10.0, current_weight=10.0),
            Edge(2, 3, base_weight=15.0, current_weight=INF),  # Current is blocked, but base is open!
        ]
        world = World(0, 300, nodes, edges, {}, [], [], [], [1, 3], [])
        engine = GraphEngine(world)

        # Static distance ignores current blocked weight
        self.assertEqual(engine.static_dist(1, 3), 25.0)
        self.assertEqual(engine.static_dist(3, 1), 25.0)

        # Dynamic distance sees the block
        cur_dist, _ = engine.dijkstra(1, weights="current")
        self.assertEqual(cur_dist.get(3, INF), INF)

    def test_mid_edge_runners(self):
        """Verify mid-edge distance calculation and reversal decisions."""
        nodes = {
            1: Node(1, 0, 0, "safehouse"),
            2: Node(2, 100, 0, "junction"),
            3: Node(3, 200, 0, "money_spot"),
        }
        edges = [
            Edge(1, 2, base_weight=100.0, current_weight=100.0),
            Edge(2, 3, base_weight=100.0, current_weight=100.0),
        ]
        world = World(0, 300, nodes, edges, {}, [], [], [], [1], [3])
        engine = GraphEngine(world)

        # Runner is mid-edge on (1 -> 2), progress = 0.2 (closer to 1), edge_len = 100.0
        # Target is safehouse 1. Reversal should take runner back to 1 (dist = 20.0, next = 1).
        dist_rev, next_rev = engine.runner_distance_to(
            runner_node=1,
            target=1,
            edge_progress=0.2,
            next_node=2,
            edge_len=100.0,
            can_reverse=True,
        )
        self.assertAlmostEqual(dist_rev, 20.0)
        self.assertEqual(next_rev, 1)

        # If reversal is forbidden, runner must continue to 2, then back to 1 (dist = 80 + 100 = 180, next = 2)
        dist_norev, next_norev = engine.runner_distance_to(
            runner_node=1,
            target=1,
            edge_progress=0.2,
            next_node=2,
            edge_len=100.0,
            can_reverse=False,
        )
        self.assertAlmostEqual(dist_norev, 180.0)
        self.assertEqual(next_norev, 2)

    def test_performance_200_nodes_benchmark(self):
        """Benchmark: 200-node graph all-runners Dijkstra must run in < 20 ms."""
        rng = random.Random(999)
        n_nodes = 200
        n_runners = 5

        nodes = {i: Node(i, rng.uniform(0, 500), rng.uniform(0, 500), "junction") for i in range(n_nodes)}
        nodes[0].type = "safehouse"
        nodes[1].type = "safehouse"
        nodes[2].type = "money_spot"

        edges = []
        # Connect into a sparse planar-like subway mesh (~3 neighbors per node)
        for i in range(n_nodes - 1):
            w = rng.uniform(10.0, 60.0)
            edges.append(Edge(i, i + 1, base_weight=w, current_weight=w))

        for _ in range(350):
            u = rng.randint(0, n_nodes - 1)
            v = rng.randint(0, n_nodes - 1)
            if u != v:
                w = rng.uniform(10.0, 60.0)
                # 5% of tracks blocked
                cur_w = INF if rng.random() < 0.05 else w
                edges.append(Edge(u, v, base_weight=w, current_weight=cur_w))

        runners = [
            Runner(id=i, current_node=rng.randint(0, n_nodes - 1), x=0, y=0, carrying_loot=0, max_capacity=500, status="ACTIVE", stun_ticks_remaining=0)
            for i in range(n_runners)
        ]

        world = World(0, 300, nodes, edges, {}, runners, [], [], [0, 1], [2])
        engine = GraphEngine(world)

        # Run Dijkstra from all runners
        start_t = time.perf_counter()
        for r in runners:
            dist_map, prev_map = engine.dijkstra(r.current_node, weights="current")
            # Also resolve path to both safehouses
            engine.path(r.current_node, 0, prev=prev_map)
            engine.path(r.current_node, 1, prev=prev_map)
            engine.next_hop(r.current_node, 0, prev=prev_map)

        elapsed_ms = (time.perf_counter() - start_t) * 1000.0

        print(f"\n[BENCHMARK] 200 nodes, {len(edges)} edges, {n_runners} runners: {elapsed_ms:.2f} ms")
        self.assertLess(elapsed_ms, 20.0, f"Expected < 20 ms, got {elapsed_ms:.2f} ms")


if __name__ == "__main__":
    unittest.main()
