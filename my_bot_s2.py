#!/usr/bin/env python3
"""
Subway Escape - Antigravity Autonomous Bot
OptimatX Club · IIT Patna (Celesta) · AI × Maths Hackathon
Phase 1: Robust I/O Shell + Adapter + Anti-DQ Fallback
"""

import heapq
import json
import math
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

# ============================================================================
#  GLOBAL CONFIGURATION
# ============================================================================
CONFIG: Dict[str, Any] = {
    "total_ticks": 300,
    "tick_budget_s": 0.35,
    "soft_time_limit_s": 0.20,     # Stage F: 200ms soft limit for planning
    "hard_time_limit_s": 0.35,     # Stage F: 350ms hard limit for immediate safe fallback
    "enable_file_logging": False,
    "debug_log_ticks": 0,
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
    "enable_idle_positioning": True,
    "enable_horizon_planner": False, # Stage C: Implemented, toggled via CONFIG flag
    "horizon_ticks": 40,
    "horizon_beam_width": 30,
    "horizon_time_budget_s": 0.20,
}

# Allow external tuning via environment variable without affecting standard runs
_env_cfg = os.environ.get("BOT_CONFIG_JSON")
if _env_cfg:
    try:
        CONFIG.update(json.loads(_env_cfg))
    except Exception:
        pass


INF = math.inf
VALID_ACTIONS = {"TRAVERSE", "HOLD", "COLLECT", "DEPOSIT"}


def log(message: str, force: bool = False) -> None:
    """Safely print diagnostic log to stderr so stdout remains 100% pure JSON."""
    if not force and not CONFIG.get("verbose_stderr", False):
        return
    try:
        sys.stderr.write(str(message) + "\n")
        sys.stderr.flush()
    except Exception:
        pass


def _safe_int(val: Any, default: int = 0) -> int:
    if val is None:
        return default
    try:
        if isinstance(val, (int, float)):
            if math.isinf(val) or math.isnan(val):
                return default
            return int(val)
        s = str(val).strip()
        num = float(s)
        if math.isinf(num) or math.isnan(num):
            return default
        return int(num)
    except (ValueError, TypeError, OverflowError):
        return default


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (ValueError, TypeError, OverflowError):
        return default


# ============================================================================
#  INTERNAL DATA MODELS
# ============================================================================
@dataclass
class Node:
    id: int
    x: float
    y: float
    type: str  # "safehouse", "money_spot", or "junction"


@dataclass
class Edge:
    u: int
    v: int
    base_weight: float
    current_weight: float  # INF if blocked


@dataclass
class Drop:
    drop_id: int
    node_id: int
    target_safehouse: int
    current_value: float
    leak_lambda: float
    ttl_remaining: int


@dataclass
class Runner:
    id: int
    current_node: int
    x: float
    y: float
    carrying_loot: float
    max_capacity: float
    status: str  # "ACTIVE" or "STUNNED"
    stun_ticks_remaining: int


@dataclass
class Police:
    id: int
    x: float
    y: float
    vx: float
    vy: float
    radius: float


@dataclass
class World:
    tick: int
    ticks_left: int
    nodes: Dict[int, Node]
    edges: List[Edge]
    neighbors: Dict[int, List[Tuple[int, float]]]  # node_id -> [(neighbor_id, weight)]
    runners: List[Runner]
    drops: List[Drop]
    police: List[Police]
    safehouses: List[int]
    money_spots: List[int]


# ============================================================================
#  SCHEMA ADAPTER (All JSON key handling is isolated here)
# ============================================================================
class Adapter:
    """
    Robust, fault-tolerant converter that translates raw JSON dictionaries
    into clean, strongly typed World data models. Handles missing keys, nulls,
    corrupted types, and inf/-1 representations.
    """

    @staticmethod
    def _parse_weight(val: Any) -> float:
        if val is None:
            return INF
        if isinstance(val, (int, float)):
            if math.isnan(val) or val < 0 or val >= 1e9 or math.isinf(val):
                return INF
            return float(val)
        if isinstance(val, str):
            s = val.strip().lower()
            if s in ("inf", "infinity", "-1", "-1.0", "null"):
                return INF
            try:
                num = float(s)
                return INF if (num < 0 or math.isnan(num) or num >= 1e9 or math.isinf(num)) else num
            except ValueError:
                return INF
        return INF

    @classmethod
    def parse_world(cls, raw: Dict[str, Any]) -> World:
        if not isinstance(raw, dict):
            raw = {}

        tick = _safe_int(raw.get("tick", 0), 0)
        ticks_left = max(0, CONFIG["total_ticks"] - tick)

        # 1. Parse Nodes
        nodes: Dict[int, Node] = {}
        raw_nodes = raw.get("graph_nodes", [])
        if isinstance(raw_nodes, list):
            for n in raw_nodes:
                if not isinstance(n, dict):
                    continue
                try:
                    nid = _safe_int(n.get("id"))
                    nx = _safe_float(n.get("x"))
                    ny = _safe_float(n.get("y"))
                    ntype = str(n.get("type", "junction") or "junction")
                    nodes[nid] = Node(id=nid, x=nx, y=ny, type=ntype)
                except Exception:
                    continue

        # 2. Parse Edges & Build Adjacency
        edges: List[Edge] = []
        neighbors: Dict[int, List[Tuple[int, float]]] = {nid: [] for nid in nodes}

        raw_edges = raw.get("graph_edges", [])
        if isinstance(raw_edges, list):
            for e in raw_edges:
                if not isinstance(e, dict):
                    continue
                try:
                    u = _safe_int(e.get("from"))
                    v = _safe_int(e.get("to"))
                    base_w = _safe_float(e.get("base_weight"), 1.0)
                    cur_w = cls._parse_weight(e.get("current_weight"))

                    edges.append(Edge(u=u, v=v, base_weight=base_w, current_weight=cur_w))
                    if u not in neighbors:
                        neighbors[u] = []
                    if v not in neighbors:
                        neighbors[v] = []
                    neighbors[u].append((v, cur_w))
                    neighbors[v].append((u, cur_w))
                except Exception:
                    continue

        # 3. Parse Runners
        runners: List[Runner] = []
        raw_runners = raw.get("my_runners", [])
        if isinstance(raw_runners, list):
            for r in raw_runners:
                if not isinstance(r, dict):
                    continue
                try:
                    rid = _safe_int(r.get("id"), 1)
                    rnode = _safe_int(r.get("current_node"), 0)
                    rx = _safe_float(r.get("x"))
                    ry = _safe_float(r.get("y"))
                    rloot = max(0.0, _safe_float(r.get("carrying_loot")))
                    rcap = max(1.0, _safe_float(r.get("max_capacity"), 500.0))
                    rstatus = str(r.get("status", "ACTIVE") or "ACTIVE")
                    rstun = max(0, _safe_int(r.get("stun_ticks_remaining"), 0))
                    runners.append(
                        Runner(
                            id=rid,
                            current_node=rnode,
                            x=rx,
                            y=ry,
                            carrying_loot=rloot,
                            max_capacity=rcap,
                            status=rstatus,
                            stun_ticks_remaining=rstun,
                        )
                    )
                except Exception:
                    continue

        # 4. Parse Active Money Drops
        drops: List[Drop] = []
        raw_drops = raw.get("active_money_drops", [])
        if isinstance(raw_drops, list):
            for d in raw_drops:
                if not isinstance(d, dict):
                    continue
                try:
                    did = _safe_int(d.get("drop_id"))
                    dnode = _safe_int(d.get("node_id"))
                    dsafe = _safe_int(d.get("target_safehouse_node"))
                    dval = max(0.0, _safe_float(d.get("current_value")))
                    dlambda = max(0.0, _safe_float(d.get("leak_lambda"), 0.01))
                    dttl = max(0, _safe_int(d.get("ttl_remaining")))
                    drops.append(
                        Drop(
                            drop_id=did,
                            node_id=dnode,
                            target_safehouse=dsafe,
                            current_value=dval,
                            leak_lambda=dlambda,
                            ttl_remaining=dttl,
                        )
                    )
                except Exception:
                    continue

        # 5. Parse Police Officers
        police: List[Police] = []
        raw_police = raw.get("police_officers", [])
        if isinstance(raw_police, list):
            for p in raw_police:
                if not isinstance(p, dict):
                    continue
                try:
                    pid = _safe_int(p.get("id"))
                    px = _safe_float(p.get("x"))
                    py = _safe_float(p.get("y"))
                    pvx = _safe_float(p.get("vx"))
                    pvy = _safe_float(p.get("vy"))
                    prad = max(1.0, _safe_float(p.get("radius"), 15.0))
                    police.append(Police(id=pid, x=px, y=py, vx=pvx, vy=pvy, radius=prad))
                except Exception:
                    continue

        safehouses = [nid for nid, n in nodes.items() if n.type == "safehouse"]
        money_spots = [nid for nid, n in nodes.items() if n.type == "money_spot"]

        return World(
            tick=tick,
            ticks_left=ticks_left,
            nodes=nodes,
            edges=edges,
            neighbors=neighbors,
            runners=runners,
            drops=drops,
            police=police,
            safehouses=safehouses,
            money_spots=money_spots,
        )


# ============================================================================
#  ACTION VALIDATOR (Guarantees every outgoing JSON is legal)
# ============================================================================
class Validator:
    """
    Validates candidate actions generated by the bot logic.
    Any missing, duplicate, or illegal action is safely downgraded to HOLD.
    Ensures zero BadActs and zero protocol rejections.
    """

    @staticmethod
    def validate_actions(
        actions: Any,
        world: World,
        known_runner_ids: Set[int],
    ) -> List[Dict[str, Any]]:
        runners_in_world = {r.id: r for r in world.runners}
        # Fallback runner ID set if world.runners was somehow empty
        effective_rids = set(runners_in_world.keys()) if runners_in_world else set(known_runner_ids)
        if not effective_rids:
            effective_rids = {1}

        chosen: Dict[int, Dict[str, Any]] = {}
        if isinstance(actions, list):
            for item in actions:
                if not isinstance(item, dict):
                    continue
                rid = item.get("runner_id")
                if rid not in effective_rids or rid in chosen:
                    continue

                act_type = str(item.get("action", "")).upper()
                if act_type not in VALID_ACTIONS:
                    log(f"WARNING: Runner {rid} sent invalid action {act_type!r}. Defaulting to HOLD.")
                    chosen[rid] = {"runner_id": rid, "action": "HOLD"}
                    continue

                runner = runners_in_world.get(rid)
                if runner and runner.status == "STUNNED":
                    chosen[rid] = {"runner_id": rid, "action": "HOLD"}
                    continue

                if act_type == "TRAVERSE":
                    target = item.get("target_node")
                    if not isinstance(target, int):
                        log(f"WARNING: Runner {rid} TRAVERSE missing integer target_node. Defaulting to HOLD.")
                        chosen[rid] = {"runner_id": rid, "action": "HOLD"}
                        continue

                    here = runner.current_node if runner else None
                    if here is not None and here in world.neighbors:
                        is_valid_neighbor = any(
                            nbr == target and w != INF for nbr, w in world.neighbors[here]
                        )
                    else:
                        is_valid_neighbor = False

                    if is_valid_neighbor:
                        chosen[rid] = {"runner_id": rid, "action": "TRAVERSE", "target_node": target}
                    else:
                        log(f"WARNING: Runner {rid} cannot TRAVERSE {here} -> {target}. Defaulting to HOLD.")
                        chosen[rid] = {"runner_id": rid, "action": "HOLD"}

                elif act_type == "COLLECT":
                    here = runner.current_node if runner else None
                    has_drop = any(d.node_id == here for d in world.drops) if here is not None else False
                    has_room = (runner.carrying_loot < runner.max_capacity) if runner else True
                    if has_drop and has_room:
                        chosen[rid] = {"runner_id": rid, "action": "COLLECT"}
                    else:
                        log(f"WARNING: Illegal COLLECT for runner {rid} at node {here}. Defaulting to HOLD.")
                        chosen[rid] = {"runner_id": rid, "action": "HOLD"}

                elif act_type == "DEPOSIT":
                    here = runner.current_node if runner else None
                    is_safehouse = (runner.current_node in world.safehouses) if runner else False
                    has_loot = (runner.carrying_loot > 0) if runner else True
                    if is_safehouse and has_loot:
                        chosen[rid] = {"runner_id": rid, "action": "DEPOSIT"}
                    else:
                        log(f"WARNING: Illegal DEPOSIT for runner {rid} at node {here}. Defaulting to HOLD.")
                        chosen[rid] = {"runner_id": rid, "action": "HOLD"}

                else:  # HOLD
                    chosen[rid] = {"runner_id": rid, "action": "HOLD"}

        # Ensure every active runner has exactly one verified action
        final_actions: List[Dict[str, Any]] = []
        for rid in sorted(effective_rids):
            if rid in chosen:
                final_actions.append(chosen[rid])
            else:
                final_actions.append({"runner_id": rid, "action": "HOLD"})

        return final_actions


# ============================================================================
#  RISK MODEL (Space-Time Kinematic Police Trajectory Prediction & Hazard Cost)
# ============================================================================
class RiskModel:
    """
    Predictive Space-Time Police Collision & Danger Assessment.
    - Extrapolates police positions for k in 0..H: p(k) = p0 + v*k.
    - Evaluates distance to circular danger zones (radius + safety_margin).
    - Augments edge traversal costs with expected capture losses.
    """

    def __init__(self, police: List[Police], world_size: float = 500.0) -> None:
        self.police = police
        self.world_size = world_size
        self.H = int(CONFIG.get("risk_lookahead_H", 15))
        self.safety_margin = float(CONFIG.get("risk_safety_margin", 8.0))
        self.penalty_weight = float(CONFIG.get("risk_penalty_weight", 6.0))
        self.stun_cost = 3.0 * float(CONFIG.get("avg_income_per_tick", 70.0))
        self._pred_trajectories: Dict[int, List[Tuple[float, float, float]]] = {}
        self._predict_all()

    def _predict_all(self) -> None:
        for cop in self.police:
            traj = []
            x, y = cop.x, cop.y
            vx, vy = cop.vx, cop.vy
            for k in range(self.H + 1):
                px = max(10.0, min(self.world_size - 10.0, x + k * vx))
                py = max(10.0, min(self.world_size - 10.0, y + k * vy))
                traj.append((px, py, cop.radius))
            self._pred_trajectories[cop.id] = traj

    def get_police_pred(self, cop_id: int, k: int) -> Tuple[float, float, float]:
        traj = self._pred_trajectories.get(cop_id)
        if not traj:
            return 0.0, 0.0, 15.0
        idx = min(k, len(traj) - 1)
        return traj[idx]

    def point_hit_risk(self, x: float, y: float, k: int) -> float:
        """
        Computes hit penetration [0.0, 1.0] against all predicted cops at future tick k.
        1.0 means inside fatal capture radius.
        """
        max_penetration = 0.0
        k_idx = min(k, self.H)
        for cop_id in self._pred_trajectories:
            cx, cy, radius = self.get_police_pred(cop_id, k_idx)
            dist = math.hypot(x - cx, y - cy)
            danger_r = radius + self.safety_margin
            if dist <= radius:
                return 1.0
            if dist < danger_r:
                pen = 1.0 - (dist - radius) / self.safety_margin
                if pen > max_penetration:
                    max_penetration = pen
        return max_penetration

    def edge_risk_penalty(self, node_u: Node, node_v: Node, k_arrive: int, carried_loot: float) -> float:
        """
        Computes risk penalty for traversing edge (u, v) arriving at future tick offset k_arrive.
        Stage 3c: Gated by real danger and carried value.
        """
        if not CONFIG.get("enable_gated_risk", True):
            k_step = min(k_arrive, self.H)
            hit_v = self.point_hit_risk(node_v.x, node_v.y, k_step)
            mid_x = (node_u.x + node_v.x) * 0.5
            mid_y = (node_u.y + node_v.y) * 0.5
            hit_mid = self.point_hit_risk(mid_x, mid_y, max(0, k_step - 1))
            effective_hit = max(hit_v, hit_mid)
            if effective_hit <= 0.0:
                return 0.0
            if effective_hit >= 0.95:
                return 1e6
            expected_loss = (carried_loot + self.stun_cost) * effective_hit
            return self.penalty_weight * expected_loss

        # Stage 3c: Gated Risk Model
        k_step = min(k_arrive, self.H)
        loot_ratio = min(1.0, max(0.0, carried_loot / 500.0))
        # Empty runners accept a tighter safety margin (3.0); loaded runners use a protective margin (7.0)
        gated_margin = 3.0 + 4.0 * loot_ratio

        max_penetration = 0.0
        # Check endpoint node_v
        for cop_id in self._pred_trajectories:
            cx, cy, radius = self.get_police_pred(cop_id, k_step)
            d_v = math.hypot(node_v.x - cx, node_v.y - cy)
            if d_v <= radius:
                return 1e6  # Direct fatal capture predicted
            danger_r = radius + gated_margin
            if d_v < danger_r:
                pen = 1.0 - (d_v - radius) / gated_margin
                if pen > max_penetration:
                    max_penetration = pen

        # Check midpoint of edge during transit
        if max_penetration < 0.95:
            mid_x = (node_u.x + node_v.x) * 0.5
            mid_y = (node_u.y + node_v.y) * 0.5
            k_mid = max(0, k_step - 1)
            for cop_id in self._pred_trajectories:
                cx, cy, radius = self.get_police_pred(cop_id, k_mid)
                d_m = math.hypot(mid_x - cx, mid_y - cy)
                if d_m <= radius:
                    return 1e6
                danger_r = radius + gated_margin
                if d_m < danger_r:
                    pen = 1.0 - (d_m - radius) / gated_margin
                    if pen > max_penetration:
                        max_penetration = pen

        if max_penetration <= 0.0:
            return 0.0

        capture_cost = carried_loot + self.stun_cost
        # Scaled penalty weight: 1.5 when empty, 4.0 when loaded
        effective_weight = 1.5 + 2.5 * loot_ratio
        return effective_weight * capture_cost * max_penetration


# ============================================================================
#  GRAPH ENGINE (Dynamic Dijkstra, Static Precomputation & Next-Hop Routing)
# ============================================================================
class GraphEngine:
    """
    High-performance graph routing engine for the subway network.
    - Bidirectional and directed track adjacency
    - Dynamic Dijkstra on current_weight (skips blocked tracks)
    - Static distance precomputation (base_weight) for safehouses and drops
    - Path reconstruction and immediate next-hop resolution
    - Mid-edge runner distance and reversal handling
    """

    def __init__(self, world: Optional[World] = None) -> None:
        self.world: Optional[World] = None
        self.adj_current: Dict[int, List[Tuple[int, float]]] = {}
        self.adj_base: Dict[int, List[Tuple[int, float]]] = {}
        self._static_cache: Dict[int, Tuple[Dict[int, float], Dict[int, Optional[int]]]] = {}
        self._topology_hash: Optional[Tuple[int, int]] = None
        if world is not None:
            self.update_world(world)

    def update_world(self, world: World) -> None:
        """Update graph adjacency from latest world state and manage heuristic cache."""
        self.world = world
        self.adj_current = {nid: [] for nid in world.nodes}
        self.adj_base = {nid: [] for nid in world.nodes}

        for e in world.edges:
            # Current weights (tracks are bidirectional per specification)
            if e.current_weight != INF and e.current_weight >= 0 and not math.isinf(e.current_weight):
                self.adj_current.setdefault(e.u, []).append((e.v, e.current_weight))
                self.adj_current.setdefault(e.v, []).append((e.u, e.current_weight))

            # Base weights (static network distances)
            if e.base_weight != INF and e.base_weight >= 0 and not math.isinf(e.base_weight):
                self.adj_base.setdefault(e.u, []).append((e.v, e.base_weight))
                self.adj_base.setdefault(e.v, []).append((e.u, e.base_weight))

        # Invalidate static cache only if network topology changes
        topo_hash = (len(world.nodes), len(world.edges))
        if self._topology_hash != topo_hash:
            self._static_cache.clear()
            self._topology_hash = topo_hash
            self.precompute_static_safehouses()

    def dijkstra(
        self,
        source: int,
        weights: str = "current",
    ) -> Tuple[Dict[int, float], Dict[int, Optional[int]]]:
        """
        Computes single-source shortest paths using a priority queue.
        weights: 'current' (dynamic edge weights) or 'base' (static network distances).
        Returns:
            dist: Dict[node_id, shortest_distance] (unreachable nodes omitted or INF)
            prev: Dict[node_id, predecessor_node]
        """
        adj = self.adj_current if weights == "current" else self.adj_base
        dist: Dict[int, float] = {source: 0.0}
        prev: Dict[int, Optional[int]] = {source: None}
        pq: List[Tuple[float, int]] = [(0.0, source)]

        while pq:
            d, u = heapq.heappop(pq)
            if d > dist.get(u, INF):
                continue

            for v, w in adj.get(u, []):
                if w == INF or w < 0 or math.isinf(w):
                    continue
                new_d = d + w
                if new_d < dist.get(v, INF):
                    dist[v] = new_d
                    prev[v] = u
                    heapq.heappush(pq, (new_d, v))

        return dist, prev

    def dijkstra_risk(
        self,
        source: int,
        risk_model: RiskModel,
        carried_loot: float = 0.0,
    ) -> Tuple[Dict[int, float], Dict[int, Optional[int]]]:
        """
        Space-Time Risk-Augmented Dijkstra.
        Applies kinematic police collision probabilities and carried value loss
        penalties dynamically across the time-expanded horizon.
        """
        dist: Dict[int, float] = {source: 0.0}
        prev: Dict[int, Optional[int]] = {source: None}
        hops_map: Dict[int, int] = {source: 0}
        pq: List[Tuple[float, int, int]] = [(0.0, source, 0)]  # (cost, node, hops)

        while pq:
            cost, u, hops = heapq.heappop(pq)
            if cost > dist.get(u, INF):
                continue

            for v, base_w in self.adj_current.get(u, []):
                if base_w == INF or base_w < 0 or math.isinf(base_w):
                    continue

                next_hops = hops + 1
                risk_pen = 0.0
                if self.world and u in self.world.nodes and v in self.world.nodes:
                    risk_pen = risk_model.edge_risk_penalty(
                        self.world.nodes[u],
                        self.world.nodes[v],
                        next_hops,
                        carried_loot,
                    )

                if risk_pen >= 1e5:
                    # Impassable hazard
                    continue

                new_cost = cost + base_w + risk_pen
                if new_cost < dist.get(v, INF):
                    dist[v] = new_cost
                    prev[v] = u
                    hops_map[v] = next_hops
                    heapq.heappush(pq, (new_cost, v, next_hops))

        return dist, prev

    def path(
        self,
        source: int,
        target: int,
        prev: Optional[Dict[int, Optional[int]]] = None,
        weights: str = "current",
    ) -> List[int]:
        """
        Reconstructs the shortest path [source, ..., target].
        Returns [] if target is disconnected/unreachable.
        """
        if source == target:
            return [source]

        if prev is None:
            _, prev = self.dijkstra(source, weights=weights)

        if target not in prev or (target != source and prev[target] is None):
            return []

        route: List[int] = []
        curr: Optional[int] = target
        visited: Set[int] = set()

        while curr is not None:
            if curr in visited:
                return []  # Cycle protection guard
            visited.add(curr)
            route.append(curr)
            if curr == source:
                break
            curr = prev.get(curr)

        if not route or route[-1] != source:
            return []

        route.reverse()
        return route

    def next_hop(
        self,
        source: int,
        target: int,
        prev: Optional[Dict[int, Optional[int]]] = None,
        weights: str = "current",
    ) -> Optional[int]:
        """
        Determines the immediate adjacent node to step to from source towards target.
        Returns None if target is unreachable, or source if source == target.
        """
        if source == target:
            return source

        route = self.path(source, target, prev=prev, weights=weights)
        if len(route) >= 2:
            return route[1]
        return None

    def get_static_paths(self, source: int) -> Tuple[Dict[int, float], Dict[int, Optional[int]]]:
        """Retrieves or precomputes static shortest paths from source using base_weight."""
        if source not in self._static_cache:
            self._static_cache[source] = self.dijkstra(source, weights="base")
        return self._static_cache[source]

    def static_dist(self, source: int, target: int) -> float:
        """Fast O(1) cached static distance between source and target."""
        dist_map, _ = self.get_static_paths(source)
        return dist_map.get(target, INF)

    def precompute_static_safehouses(self) -> None:
        """Precomputes and caches all-pairs static paths from all safehouses."""
        if not self.world:
            return
        for s in self.world.safehouses:
            self.get_static_paths(s)

    def runner_distance_to(
        self,
        runner_node: int,
        target: int,
        edge_progress: float = 0.0,
        next_node: Optional[int] = None,
        edge_len: float = 0.0,
        can_reverse: bool = True,
        weights: str = "current",
    ) -> Tuple[float, Optional[int]]:
        """
        Handles distance and next-hop resolution for runners, whether at a discrete node
        or in-transit mid-edge.
        Returns: (total_shortest_distance, immediate_target_node)
        """
        # If runner is at a discrete node or edge progress is invalid
        if next_node is None or edge_progress <= 0.0 or edge_progress >= 1.0 or edge_len <= 0.0:
            dist_map, prev_map = self.dijkstra(runner_node, weights=weights)
            d = dist_map.get(target, INF)
            hop = self.next_hop(runner_node, target, prev=prev_map, weights=weights)
            return d, hop

        # Runner is mid-edge on edge (runner_node -> next_node)
        # Continuing forward to next_node:
        dist_forward = edge_len * (1.0 - edge_progress)
        dist_from_next, _ = self.dijkstra(next_node, weights=weights)
        cost_forward = dist_forward + dist_from_next.get(target, INF)

        if can_reverse:
            # Reversing backward to runner_node:
            dist_backward = edge_len * edge_progress
            dist_from_prev, _ = self.dijkstra(runner_node, weights=weights)
            cost_backward = dist_backward + dist_from_prev.get(target, INF)
            if cost_backward < cost_forward:
                return cost_backward, runner_node

        return cost_forward, next_node


# ============================================================================
#  BOT DECISION ENGINE (Phase 6 Economics + Phase 7 Multi-Runner & Endgame)
# ============================================================================
class BotEngine:
    def __init__(self) -> None:
        self.known_runner_ids: Set[int] = set()
        self.graph_engine = GraphEngine()
        # Persistence across ticks for coordination and hysteresis
        self.runner_prev_drop: Dict[int, Optional[int]] = {}
        self.runner_prev_utility: Dict[int, float] = {}
        self.seen_drop_ids: Set[int] = set()
        self.spot_drop_count: Dict[int, int] = {}
        self.spot_total_value: Dict[int, float] = {}

    def compute_drop_utility(
        self,
        runner: Runner,
        drop: Drop,
        dist_map: Dict[int, float],
        prev_map: Dict[int, Optional[int]],
        world: World,
    ) -> Tuple[float, int, int]:
        """
        Phase 6 Lifecycle Drop Utility:
        U = (v_arrive - risk_cost) * exp(-lambda * tau(drop -> safe)) / (tau(r -> drop) + tau(drop -> safe) + 1.0)
        Returns: (utility, hops_to_drop, hops_drop_to_safe)
        """
        dnode = drop.node_id
        if dnode not in dist_map or dist_map[dnode] == INF or dist_map[dnode] >= 1e5:
            return -1.0, 999, 999

        path_to_drop = self.graph_engine.path(runner.current_node, dnode, prev=prev_map)
        hops_to_drop = max(0, len(path_to_drop) - 1)

        # 1. Feasibility: Skip if drop TTL expires before arrival
        if hops_to_drop >= drop.ttl_remaining:
            return -1.0, hops_to_drop, 999

        # 2. Nearest safehouse from drop node (using static base_weight)
        safe_dist, _ = min(
            ((self.graph_engine.static_dist(dnode, s), s) for s in world.safehouses),
            default=(INF, world.safehouses[0] if world.safehouses else 0)
        )
        if safe_dist == INF or math.isinf(safe_dist) or safe_dist >= 1e5:
            return -1.0, hops_to_drop, 999
        hops_drop_to_safe = max(1, int(safe_dist / 35.0))

        # 3. Feasibility: Can the runner collect and deposit before tick 300?
        if hops_to_drop + 1 + hops_drop_to_safe > world.ticks_left:
            return -1.0, hops_to_drop, hops_drop_to_safe

        # 4. Decayed value at arrival
        v_arrive = drop.current_value * math.exp(-drop.leak_lambda * hops_to_drop)
        if v_arrive <= 0.0:
            return -1.0, hops_to_drop, hops_drop_to_safe

        # 5. Risk cost along travel
        base_travel = self.graph_engine.static_dist(runner.current_node, dnode)
        risk_cost = max(0.0, dist_map[dnode] - base_travel)

        # 6. Decay from drop to safehouse
        decay_to_safe = math.exp(-drop.leak_lambda * hops_drop_to_safe)
        net_value = max(0.0, v_arrive - 0.15 * risk_cost)

        # 7. Total utility rate of return
        cycle_time = hops_to_drop + hops_drop_to_safe + 1.0
        utility = (net_value * decay_to_safe) / cycle_time

        return utility, hops_to_drop, hops_drop_to_safe

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

    def evaluate_chained_sequences(
        self,
        runner: Runner,
        dist_m: Dict[int, float],
        prev_m: Dict[int, Optional[int]],
        world: World,
        reserved_drop_ids: Set[int],
    ) -> List[Tuple[float, int, int]]:
        """
        Stage 3a: Multi-drop chaining by rate.
        Evaluates short sequences (1, 2, or 3 drops) followed by best safehouse.
        Returns candidate list of (rate_of_return, drop_id, hops_to_drop).
        """
        if not CONFIG.get("enable_chaining", True):
            return []

        cands = [d for d in world.drops if d.node_id != runner.current_node and d.drop_id not in reserved_drop_ids]
        if not cands:
            return []

        max_cap = runner.max_capacity
        curr_loot = runner.carrying_loot
        capacity_cutoff = CONFIG.get("chain_capacity_cutoff", 450.0)
        max_depth = CONFIG.get("chain_max_depth", 3)
        # Adapt depth on massive graphs (e.g. 1000 nodes) to strictly respect 350ms budget
        if len(world.nodes) > 150:
            max_depth = 1
        ticks_left = world.ticks_left

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

        # Pre-cache static paths from all safehouses: O(1) lookup for any node!
        safe_maps: List[Tuple[int, Dict[int, float], Dict[int, Optional[int]]]] = []
        for s in world.safehouses:
            s_dist, s_prev = self.graph_engine.get_static_paths(s)
            safe_maps.append((s, s_dist, s_prev))

        def get_nearest_safe_hops(u: int) -> Tuple[Optional[int], int]:
            best_s = None
            min_h = 999
            for s, s_dist, s_prev in safe_maps:
                if u in s_dist and s_dist[u] != INF:
                    p = self.graph_engine.path(s, u, prev=s_prev)
                    h = len(p) - 1 if p else 999
                    if h < min_h:
                        min_h = h
                        best_s = s
            return best_s, min_h

        single_drop_rates: List[Tuple[float, Drop, int, float]] = []
        for d1 in cands:
            if d1.node_id not in dist_m or dist_m[d1.node_id] == INF:
                continue
            p1 = self.graph_engine.path(runner.current_node, d1.node_id, prev=prev_m)
            if not p1:
                continue
            h1 = len(p1) - 1
            if h1 <= 0 or h1 >= d1.ttl_remaining or (h1 + 2 > ticks_left):
                continue
            v1_arr = d1.current_value * math.exp(-d1.leak_lambda * h1)
            take1 = min(max_cap - curr_loot, v1_arr)
            if take1 <= 0:
                continue
            _, h_safe1 = get_nearest_safe_hops(d1.node_id)
            total_t1 = h1 + 1 + h_safe1 + 1
            if total_t1 > ticks_left:
                continue
            rate1 = (curr_loot + take1) / total_t1
            single_drop_rates.append((rate1, d1, h1, take1))

        if not single_drop_rates:
            return []

        single_drop_rates.sort(key=lambda x: x[0], reverse=True)
        top_candidates = [item[1] for item in single_drop_rates[:6]]

        sequence_evals: Dict[int, float] = {}
        hops_to_first: Dict[int, int] = {}

        for rate1, d1, h1, take1 in single_drop_rates[:6]:
            sequence_evals[d1.drop_id] = rate1
            hops_to_first[d1.drop_id] = h1

            if max_depth >= 2 and (curr_loot + take1) < capacity_cutoff and ticks_left > 15:
                for d2 in top_candidates:
                    if d2.drop_id == d1.drop_id:
                        continue
                    h2 = get_hops(d1.node_id, d2.node_id)
                    if h2 >= 999:
                        continue
                    t2_arr = h1 + 1 + h2
                    if t2_arr >= d2.ttl_remaining or (t2_arr + 2 > ticks_left):
                        continue
                    v2_arr = d2.current_value * math.exp(-d2.leak_lambda * t2_arr)
                    take2 = min(max_cap - (curr_loot + take1), v2_arr)
                    if take2 <= 0:
                        continue
                    _, h_safe2 = get_nearest_safe_hops(d2.node_id)
                    total_t2 = t2_arr + 1 + h_safe2 + 1
                    if total_t2 > ticks_left:
                        continue
                    rate2 = (curr_loot + take1 + take2) / total_t2
                    if rate2 > sequence_evals[d1.drop_id]:
                        sequence_evals[d1.drop_id] = rate2

                    if max_depth >= 3 and (curr_loot + take1 + take2) < capacity_cutoff and ticks_left > 25:
                        for d3 in top_candidates:
                            if d3.drop_id == d1.drop_id or d3.drop_id == d2.drop_id:
                                continue
                            h3 = get_hops(d2.node_id, d3.node_id)
                            if h3 >= 999:
                                continue
                            t3_arr = t2_arr + 1 + h3
                            if t3_arr >= d3.ttl_remaining or (t3_arr + 2 > ticks_left):
                                continue
                            v3_arr = d3.current_value * math.exp(-d3.leak_lambda * t3_arr)
                            take3 = min(max_cap - (curr_loot + take1 + take2), v3_arr)
                            if take3 <= 0:
                                continue
                            _, h_safe3 = get_nearest_safe_hops(d3.node_id)
                            total_t3 = t3_arr + 1 + h_safe3 + 1
                            if total_t3 > ticks_left:
                                continue
                            rate3 = (curr_loot + take1 + take2 + take3) / total_t3
                            if rate3 > sequence_evals[d1.drop_id]:
                                sequence_evals[d1.drop_id] = rate3

        results: List[Tuple[float, int, int]] = []
        for did, best_rate in sequence_evals.items():
            results.append((best_rate, did, hops_to_first[did]))
        return results

    def bank_now_test(
        self,
        runner: Runner,
        best_drop_utility: float,
        hops_to_safe: int,
        world: World,
        avg_lambda: float,
    ) -> bool:
        """
        Phase 6 Optimal Stopping Marginal Analysis:
        Compares bank_value_now vs expected_value_after_next_pickup.
        """
        carrying = runner.carrying_loot
        capacity = runner.max_capacity

        if carrying <= 0.0:
            return False

        # Endgame Deadline: Must return so all loot is banked before tick 300
        if world.ticks_left <= hops_to_safe + CONFIG["endgame_margin"]:
            return True

        # Dynamic capacity threshold tuned from lambda
        # High lambda -> bank earlier, Low lambda -> bank later
        dynamic_threshold = max(
            CONFIG["bank_threshold_min"],
            min(CONFIG["bank_threshold_max"], CONFIG.get("dynamic_bank_coef", 3.2) / max(0.005, avg_lambda))
        )
        if carrying >= dynamic_threshold or carrying >= capacity * 0.95:
            return True

        # If no feasible drop exists, return to bank immediately
        if best_drop_utility <= 0.0:
            return True

        # Marginal value comparison:
        v_bank_now = carrying * math.exp(-avg_lambda * hops_to_safe)
        detour_ticks = 4.0
        v_after_detour = (carrying * math.exp(-avg_lambda * (hops_to_safe + detour_ticks)) + best_drop_utility * detour_ticks) * 0.98

        if v_bank_now > v_after_detour:
            return True

        return False

    def update_spawn_stats(self, world: World) -> None:
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

    def decide(self, world: World, t_start: float = 0.0) -> List[Dict[str, Any]]:
        """
        Phase 6 Economics + Phase 7 Multi-Runner Coordination & Endgame Planner.
        """
        raw_actions: List[Dict[str, Any]] = []
        assigned_targets: Dict[int, Tuple[str, Optional[int]]] = {}  # rid -> (mode, target_node)
        reserved_drop_ids: Set[int] = set()
        targeted_safehouses: Dict[int, int] = {}  # safehouse_id -> count of runners heading there

        risk_model = RiskModel(world.police)
        self.update_spawn_stats(world)
        lambdas = [d.leak_lambda for d in world.drops]
        avg_lambda = sum(lambdas) / len(lambdas) if lambdas else 0.01

        # Lookup for active drops by node_id: node_id -> Drop
        drops_by_node: Dict[int, Drop] = {}
        for d in world.drops:
            if d.node_id not in drops_by_node or d.current_value > drops_by_node[d.node_id].current_value:
                drops_by_node[d.node_id] = d

        # Step 1: Pre-process immediate STUNNED, immediate COLLECT, and opportunistic DEPOSIT
        runners_needing_routing: List[Runner] = []
        runner_maps: Dict[int, Tuple[Dict[int, float], Dict[int, Optional[int]]]] = {}

        for runner in world.runners:
            rid = runner.id
            here = runner.current_node
            carrying = runner.carrying_loot
            capacity = runner.max_capacity

            # STUNNED check
            if runner.status == "STUNNED":
                log(f"[tick {world.tick:03d}] Runner {rid}: mode=STUNNED target={here} action=HOLD")
                raw_actions.append({"runner_id": rid, "action": "HOLD"})
                continue

            # Immediate COLLECT: Standing on active drop with room
            if here in drops_by_node and carrying < capacity:
                drop_here = drops_by_node[here]
                reserved_drop_ids.add(drop_here.drop_id)
                log(f"[tick {world.tick:03d}] Runner {rid}: mode=COLLECT drop={drop_here.drop_id} val={drop_here.current_value:.1f} action=COLLECT")
                raw_actions.append({"runner_id": rid, "action": "COLLECT"})
                continue

            # Opportunistic Banking: Already standing on safehouse with loot
            if here in world.safehouses and carrying >= CONFIG["min_opportunistic_loot"]:
                log(f"[tick {world.tick:03d}] Runner {rid}: mode=OPPORTUNISTIC_DEPOSIT safehouse={here} loot={carrying:.1f} action=DEPOSIT")
                raw_actions.append({"runner_id": rid, "action": "DEPOSIT"})
                continue

            # Calculate risk-augmented Dijkstra from current position
            dist_m, prev_m = self.graph_engine.dijkstra_risk(here, risk_model, carrying)
            runner_maps[rid] = (dist_m, prev_m)
            runners_needing_routing.append(runner)

        # Step 2: Multi-Runner Bipartite Utility Matrix (Runner x Drop)
        candidate_pairings: List[Tuple[float, int, int, int]] = []  # (effective_utility, rid, drop_id, hops_to_drop)

        for runner in runners_needing_routing:
            rid = runner.id
            dist_m, prev_m = runner_maps[rid]

            if runner.carrying_loot < runner.max_capacity:
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
                            candidate_pairings.append((util, rid, drop.drop_id, hops_drop))

        # Sort candidate pairings by effective utility descending (Greedy Bipartite Matching)
        candidate_pairings.sort(key=lambda item: item[0], reverse=True)
        assigned_runners: Set[int] = set()

        for util, rid, did, hops_drop in candidate_pairings:
            if rid in assigned_runners or did in reserved_drop_ids:
                continue

            runner = next((r for r in runners_needing_routing if r.id == rid), None)
            if runner is None:
                continue

            dist_m, prev_m = runner_maps[rid]
            # Safehouse distance from runner
            reachable_safes = [s for s in world.safehouses if s in dist_m and dist_m[s] != INF]
            nearest_safe = min(reachable_safes, key=lambda s: dist_m[s], default=None)
            hops_to_safe = max(0, len(self.graph_engine.path(runner.current_node, nearest_safe, prev=prev_m)) - 1) if nearest_safe is not None else 999

            # Evaluate Bank-Now test: Should runner bank instead of chasing this drop?
            if self.bank_now_test(runner, util, hops_to_safe, world, avg_lambda):
                assigned_targets[rid] = ("RETURN", nearest_safe)
            else:
                drop_obj = next((d for d in world.drops if d.drop_id == did), None)
                if drop_obj:
                    assigned_targets[rid] = ("SEEK", drop_obj.node_id)
                    reserved_drop_ids.add(did)
                    self.runner_prev_drop[rid] = did
                    self.runner_prev_utility[rid] = util

            assigned_runners.add(rid)

        # Step 3: Route remaining unassigned runners (Bank or Hold)
        for runner in runners_needing_routing:
            rid = runner.id
            if rid in assigned_runners:
                continue

            dist_m, prev_m = runner_maps[rid]
            reachable_safes = [s for s in world.safehouses if s in dist_m and dist_m[s] != INF]

            if runner.carrying_loot > 0 and reachable_safes:
                # Safehouse Deconfliction: Spread runners across safehouses
                def safe_cost(s: int) -> float:
                    base_d = dist_m[s]
                    congestion = targeted_safehouses.get(s, 0) * CONFIG["safehouse_congestion_pen"] * 35.0
                    return base_d + congestion

                chosen_safe = min(reachable_safes, key=safe_cost)
                targeted_safehouses[chosen_safe] = targeted_safehouses.get(chosen_safe, 0) + 1
                assigned_targets[rid] = ("RETURN", chosen_safe)
            else:
                if CONFIG.get("enable_idle_positioning", False):
                    best_pos_node = self.find_best_idle_position(runner, dist_m, prev_m, world)
                    if best_pos_node is not None:
                        assigned_targets[rid] = ("POSITION", best_pos_node)
                    else:
                        assigned_targets[rid] = ("HOLD", None)
                else:
                    assigned_targets[rid] = ("HOLD", None)
                self.runner_prev_drop[rid] = None
                self.runner_prev_utility[rid] = 0.0

        # Step 4: Resolve Actions & Apply Panic Mode Evasion
        for runner in runners_needing_routing:
            rid = runner.id
            here = runner.current_node
            carrying = runner.carrying_loot
            mode, target_node = assigned_targets.get(rid, ("HOLD", None))
            dist_m, prev_m = runner_maps[rid]

            # Endgame Drainage Enforcement (last ticks)
            if here in world.safehouses and carrying > 0 and (mode == "RETURN" or world.ticks_left <= 5):
                log(f"[tick {world.tick:03d}] Runner {rid}: mode=ENDGAME_DEPOSIT safehouse={here} loot={carrying:.1f} action=DEPOSIT")
                raw_actions.append({"runner_id": rid, "action": "DEPOSIT"})
                continue

            if target_node is None or target_node == here:
                if here in world.safehouses and carrying > 0:
                    act = {"runner_id": rid, "action": "DEPOSIT"}
                else:
                    act = {"runner_id": rid, "action": "HOLD"}
            else:
                step_node = self.graph_engine.next_hop(here, target_node, prev=prev_m)
                if step_node is not None and step_node != here:
                    # Space-time check: Is stepping into step_node fatal next tick?
                    hit_step = risk_model.point_hit_risk(world.nodes[step_node].x, world.nodes[step_node].y, 1)
                    hit_here = risk_model.point_hit_risk(world.nodes[here].x, world.nodes[here].y, 1)

                    if hit_step >= 0.8:
                        # Panic Mode / Tactical Hazard Evasion
                        if here in world.safehouses and carrying > 0:
                            # Panic deposit: Save capital before capture!
                            log(f"[tick {world.tick:03d}] Runner {rid}: PANIC DEPOSIT at safehouse {here} (loot saved: {carrying:.1f})")
                            act = {"runner_id": rid, "action": "DEPOSIT"}
                        elif hit_here < 0.5:
                            # Current node is safe: HOLD to let hazard pass
                            log(f"[tick {world.tick:03d}] Runner {rid}: HAZARD EVASION HOLD at {here} (step {step_node} dangerous hit={hit_step:.2f})")
                            act = {"runner_id": rid, "action": "HOLD"}
                        else:
                            # Both dangerous: Find neighbor with minimum hit risk
                            best_esc, min_hit = None, 2.0
                            for nbr, w in self.graph_engine.adj_current.get(here, []):
                                if w != INF and nbr in world.nodes:
                                    nhit = risk_model.point_hit_risk(world.nodes[nbr].x, world.nodes[nbr].y, 1)
                                    if nhit < min_hit:
                                        min_hit = nhit
                                        best_esc = nbr
                            if best_esc is not None and min_hit < hit_here:
                                log(f"[tick {world.tick:03d}] Runner {rid}: EMERGENCY DETOUR to {best_esc} (hit={min_hit:.2f})")
                                act = {"runner_id": rid, "action": "TRAVERSE", "target_node": best_esc}
                            else:
                                act = {"runner_id": rid, "action": "HOLD"}
                    else:
                        act = {"runner_id": rid, "action": "TRAVERSE", "target_node": step_node}
                else:
                    act = {"runner_id": rid, "action": "HOLD"}

            log(f"[tick {world.tick:03d}] Runner {rid}: mode={mode} target={target_node} carrying={carrying:.1f} action={act.get('action')}")
            raw_actions.append(act)

        return raw_actions

    def step(self, raw_state: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Orchestrates state adaptation, decision making, validation, and watchdog timing.
        Guaranteed to never raise an exception.
        """
        t_start = time.perf_counter()
        raw_tick = raw_state.get("tick", 0) if isinstance(raw_state, dict) else 0
        tick = _safe_int(raw_tick, 0)

        # Log raw incoming state for first N ticks for debugging
        if CONFIG.get("enable_file_logging", False) and 0 <= tick < CONFIG.get("debug_log_ticks", 0):
            try:
                mode = "w" if tick == 0 else "a"
                with open(CONFIG["debug_log_path"], mode, encoding="utf-8") as f:
                    f.write(json.dumps(raw_state) + "\n")
            except Exception:
                pass

        try:
            # 1. Parse into internal model
            world = Adapter.parse_world(raw_state)
            for r in world.runners:
                self.known_runner_ids.add(r.id)

            # 2. Update Graph Engine
            self.graph_engine.update_world(world)

            # 3. Compute decision
            if time.perf_counter() - t_start > CONFIG.get("hard_time_limit_s", 0.35):
                # Stage F Emergency Hard Timeout Guard
                fallback_ids = self.known_runner_ids or {r.id for r in world.runners}
                candidate_actions = [{"runner_id": rid, "action": "HOLD"} for rid in sorted(fallback_ids)]
            else:
                candidate_actions = self.decide(world, t_start=t_start)

            # 4. Validate and enforce legality
            final_actions = Validator.validate_actions(candidate_actions, world, self.known_runner_ids)

        except Exception as e:
            # Absolute Anti-DQ Safety Fallback
            log(f"CRITICAL ENGINE ERROR at tick {tick}: {e}\n{traceback.format_exc()}")
            fallback_ids = self.known_runner_ids or {1}
            final_actions = [{"runner_id": rid, "action": "HOLD"} for rid in sorted(fallback_ids)]

        elapsed_ms = (time.perf_counter() - t_start) * 1000.0
        if CONFIG["log_timing"]:
            log(f"[tick {tick:03d}] latency: {elapsed_ms:5.2f} ms | actions: {len(final_actions)}")

        return final_actions


# ============================================================================
#  I/O PROTOCOL MAIN LOOP
# ============================================================================
def main() -> None:
    engine = BotEngine()

    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                # EOF reached: match concluded or engine terminated pipe
                break

            line_str = line.strip()
            if not line_str:
                continue

            try:
                state_dict = json.loads(line_str)
            except Exception as parse_err:
                log(f"WARNING: Incoming line was not valid JSON ({parse_err}). Falling back.")
                state_dict = {}

            actions = engine.step(state_dict)

            # Output MUST be a single line of pure JSON, immediately flushed
            output_line = json.dumps({"runner_actions": actions})
            sys.stdout.write(output_line + "\n")
            sys.stdout.flush()

        except (BrokenPipeError, KeyboardInterrupt):
            break
        except Exception as fatal_err:
            log(f"FATAL I/O LOOP ERROR: {fatal_err}\n{traceback.format_exc()}")
            try:
                fallback_ids = engine.known_runner_ids or {1}
                emergency_actions = [{"runner_id": rid, "action": "HOLD"} for rid in sorted(fallback_ids)]
                sys.stdout.write(json.dumps({"runner_actions": emergency_actions}) + "\n")
                sys.stdout.flush()
            except Exception:
                pass


if __name__ == "__main__":
    main()
