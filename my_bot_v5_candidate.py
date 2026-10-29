#!/usr/bin/env python3
"""
Candidate bot implementing STAGE C (Horizon planner) and STAGE D (Exact endgame).
Uses Rolling-Horizon Beam Search for multi-drop sequence evaluation
and Exact Marginal Rate Stopping for bank_now_test.
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
    "debug_log_ticks": 0,
    "debug_log_path": "debug.log",
    "log_timing": False,
    "verbose_stderr": False,
    "risk_lookahead_H": 15,
    "risk_safety_margin": 8.0,
    "risk_penalty_weight": 6.0,
    "avg_income_per_tick": 70.0,
    "opportunistic_bank_dist": 1,
    "min_opportunistic_loot": 50.0,
    "switch_gain": 0.15,
    "endgame_margin": 2,
    "safehouse_congestion_pen": 2.0,
    "enable_chaining": True,
    "enable_gated_risk": True,
    # STAGE C & D CONFIG
    "enable_horizon_planner": True,
    "horizon_ticks": 40,
    "horizon_beam_width": 30,
    "horizon_time_budget_s": 0.20,
    "enable_exact_endgame": True,
}

_env_cfg = os.environ.get("BOT_CONFIG_JSON")
if _env_cfg:
    try:
        CONFIG.update(json.loads(_env_cfg))
    except Exception:
        pass

INF = math.inf
VALID_ACTIONS = {"TRAVERSE", "HOLD", "COLLECT", "DEPOSIT"}


def log(message: str, force: bool = False) -> None:
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
    type: str


@dataclass
class Edge:
    u: int
    v: int
    base_weight: float
    current_weight: float


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
    status: str
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
    neighbors: Dict[int, List[Tuple[int, float]]]
    runners: List[Runner]
    drops: List[Drop]
    police: List[Police]
    safehouses: List[int]
    money_spots: List[int]


# ============================================================================
#  SCHEMA ADAPTER
# ============================================================================
class Adapter:
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

        police_list: List[Police] = []
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
                    police_list.append(Police(id=pid, x=px, y=py, vx=pvx, vy=pvy, radius=prad))
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
            police=police_list,
            safehouses=safehouses,
            money_spots=money_spots,
        )


# ============================================================================
#  KINEMATIC RISK MODEL
# ============================================================================
class RiskModel:
    def __init__(self, police_units: List[Police]) -> None:
        self.police_units = police_units

    def point_hit_risk(self, x: float, y: float, tau: int) -> float:
        margin = CONFIG["risk_safety_margin"]
        total_p_safe = 1.0

        for cop in self.police_units:
            pred_x = cop.x + cop.vx * tau
            pred_y = cop.y + cop.vy * tau
            dist = math.hypot(x - pred_x, y - pred_y)
            threat_r = cop.radius + margin

            if dist < threat_r:
                p_hit = 1.0 - (dist / threat_r)
                p_hit = max(0.0, min(1.0, p_hit))
                total_p_safe *= (1.0 - p_hit)

        return 1.0 - total_p_safe

    def edge_risk_penalty(self, u: Node, v: Node, tau: int, carried_loot: float) -> float:
        margin = CONFIG["risk_safety_margin"]
        p_u = self.point_hit_risk(u.x, u.y, max(0, tau - 1))
        p_v = self.point_hit_risk(v.x, v.y, tau)

        cop_approaching = False
        mid_x = (u.x + v.x) / 2.0
        mid_y = (u.y + v.y) / 2.0
        for cop in self.police_units:
            d_mid = math.hypot(mid_x - (cop.x + cop.vx * tau), mid_y - (cop.y + cop.vy * tau))
            if d_mid < cop.radius + margin * 0.75:
                cop_approaching = True
                break

        edge_hit_prob = max(p_u, p_v)
        if cop_approaching:
            edge_hit_prob = max(edge_hit_prob, 0.45)

        if CONFIG.get("enable_gated_risk", True) and carried_loot < 50.0:
            if edge_hit_prob > 0.85:
                return 1e6
            return edge_hit_prob * 1.5

        if edge_hit_prob > 0.7:
            return 1e6

        return CONFIG["risk_penalty_weight"] * (edge_hit_prob ** 2) * max(10.0, carried_loot)


# ============================================================================
#  GRAPH ENGINE
# ============================================================================
class GraphEngine:
    def __init__(self) -> None:
        self.world: Optional[World] = None
        self.adj_current: Dict[int, List[Tuple[int, float]]] = {}
        self.adj_base: Dict[int, List[Tuple[int, float]]] = {}
        self._static_cache: Dict[int, Tuple[Dict[int, float], Dict[int, Optional[int]]]] = {}

    def update_world(self, world: World) -> None:
        self.world = world
        self.adj_current = {nid: [] for nid in world.nodes}
        self.adj_base = {nid: [] for nid in world.nodes}

        for e in world.edges:
            self.adj_base[e.u].append((e.v, e.base_weight))
            self.adj_base[e.v].append((e.u, e.base_weight))
            self.adj_current[e.u].append((e.v, e.current_weight))
            self.adj_current[e.v].append((e.u, e.current_weight))

    def dijkstra(self, source: int, weights: str = "current") -> Tuple[Dict[int, float], Dict[int, Optional[int]]]:
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
        dist: Dict[int, float] = {source: 0.0}
        prev: Dict[int, Optional[int]] = {source: None}
        hops_map: Dict[int, int] = {source: 0}
        pq: List[Tuple[float, int, int]] = [(0.0, source, 0)]

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
                return []
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
        if source == target:
            return source

        route = self.path(source, target, prev=prev, weights=weights)
        if len(route) >= 2:
            return route[1]
        return None

    def get_static_paths(self, source: int) -> Tuple[Dict[int, float], Dict[int, Optional[int]]]:
        if source not in self._static_cache:
            self._static_cache[source] = self.dijkstra(source, weights="base")
        return self._static_cache[source]

    def static_dist(self, source: int, target: int) -> float:
        dist_map, _ = self.get_static_paths(source)
        return dist_map.get(target, INF)


# ============================================================================
#  VALIDATOR
# ============================================================================
class Validator:
    @staticmethod
    def validate_actions(
        actions: List[Dict[str, Any]],
        world: World,
        known_runner_ids: Set[int],
    ) -> List[Dict[str, Any]]:
        runners_by_id = {r.id: r for r in world.runners}
        clean_actions: List[Dict[str, Any]] = []
        seen_runners: Set[int] = set()

        for a in actions:
            if not isinstance(a, dict):
                continue
            rid = _safe_int(a.get("runner_id"))
            act_type = str(a.get("action", "HOLD") or "HOLD").upper().strip()

            if rid not in runners_by_id or rid in seen_runners:
                continue

            seen_runners.add(rid)
            runner = runners_by_id[rid]
            here = runner.current_node

            if act_type not in VALID_ACTIONS:
                act_type = "HOLD"

            if runner.status == "STUNNED":
                clean_actions.append({"runner_id": rid, "action": "HOLD"})
                continue

            if act_type == "TRAVERSE":
                target_node = _safe_int(a.get("target_node"))
                valid_nbr = False
                for nbr, w in world.neighbors.get(here, []):
                    if nbr == target_node and w != INF and not math.isinf(w):
                        valid_nbr = True
                        break

                if valid_nbr:
                    clean_actions.append({
                        "runner_id": rid,
                        "action": "TRAVERSE",
                        "target_node": target_node,
                    })
                else:
                    clean_actions.append({"runner_id": rid, "action": "HOLD"})

            elif act_type == "COLLECT":
                has_drop = any(d.node_id == here for d in world.drops)
                if has_drop and runner.carrying_loot < runner.max_capacity:
                    clean_actions.append({"runner_id": rid, "action": "COLLECT"})
                else:
                    clean_actions.append({"runner_id": rid, "action": "HOLD"})

            elif act_type == "DEPOSIT":
                if here in world.safehouses and runner.carrying_loot > 0:
                    clean_actions.append({"runner_id": rid, "action": "DEPOSIT"})
                else:
                    clean_actions.append({"runner_id": rid, "action": "HOLD"})

            else:
                clean_actions.append({"runner_id": rid, "action": "HOLD"})

        for rid in sorted(runners_by_id):
            if rid not in seen_runners:
                clean_actions.append({"runner_id": rid, "action": "HOLD"})

        return clean_actions


# ============================================================================
#  BOT DECISION ENGINE
# ============================================================================
class BotEngine:
    def __init__(self) -> None:
        self.known_runner_ids: Set[int] = set()
        self.graph_engine = GraphEngine()
        self.runner_prev_drop: Dict[int, Optional[int]] = {}
        self.runner_prev_utility: Dict[int, float] = {}

    def compute_drop_utility(
        self,
        runner: Runner,
        drop: Drop,
        dist_map: Dict[int, float],
        prev_map: Dict[int, Optional[int]],
        world: World,
    ) -> Tuple[float, int, int]:
        dnode = drop.node_id
        if dnode not in dist_map or dist_map[dnode] == INF or dist_map[dnode] >= 1e5:
            return -1.0, 999, 999

        path_to_drop = self.graph_engine.path(runner.current_node, dnode, prev=prev_map)
        hops_to_drop = max(0, len(path_to_drop) - 1)

        if hops_to_drop >= drop.ttl_remaining:
            return -1.0, hops_to_drop, 999

        safe_dist, _ = min(
            ((self.graph_engine.static_dist(dnode, s), s) for s in world.safehouses),
            default=(INF, world.safehouses[0] if world.safehouses else 0)
        )
        if safe_dist == INF or math.isinf(safe_dist) or safe_dist >= 1e5:
            return -1.0, hops_to_drop, 999
        hops_drop_to_safe = max(1, int(safe_dist / 35.0))

        if hops_to_drop + 1 + hops_drop_to_safe > world.ticks_left:
            return -1.0, hops_to_drop, hops_drop_to_safe

        v_arrive = drop.current_value * math.exp(-drop.leak_lambda * hops_to_drop)
        if v_arrive <= 0.0:
            return -1.0, hops_to_drop, hops_drop_to_safe

        base_travel = self.graph_engine.static_dist(runner.current_node, dnode)
        risk_cost = max(0.0, dist_map[dnode] - base_travel)

        decay_to_safe = math.exp(-drop.leak_lambda * hops_drop_to_safe)
        net_value = max(0.0, v_arrive - 0.15 * risk_cost)

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

    def bank_now_test(
        self,
        runner: Runner,
        best_drop_utility: float,
        hops_to_safe: int,
        world: World,
        avg_lambda: float,
    ) -> bool:
        """
        STAGE D: Exact Stopping Condition.
        Compares instantaneous banking rate vs best drop sequence rate.
        """
        carrying = runner.carrying_loot
        capacity = runner.max_capacity

        if carrying <= 0.0:
            return False

        # Exact endgame deadline: Must bank all carried loot before match ends!
        if world.ticks_left <= hops_to_safe + CONFIG.get("endgame_margin", 2):
            return True

        if carrying >= capacity * 0.95:
            return True

        if best_drop_utility <= 0.0:
            return True

        v_bank_now = carrying * math.exp(-avg_lambda * hops_to_safe)
        rate_bank_now = v_bank_now / max(1, hops_to_safe + 1)
        if rate_bank_now > best_drop_utility:
            return True

        return False

    def decide(self, world: World, t_start: float = 0.0) -> List[Dict[str, Any]]:
        raw_actions: List[Dict[str, Any]] = []
        assigned_targets: Dict[int, Tuple[str, Optional[int]]] = {}
        reserved_drop_ids: Set[int] = set()
        targeted_safehouses: Dict[int, int] = {}

        risk_model = RiskModel(world.police)
        lambdas = [d.leak_lambda for d in world.drops]
        avg_lambda = sum(lambdas) / len(lambdas) if lambdas else 0.01

        drops_by_node: Dict[int, Drop] = {}
        for d in world.drops:
            if d.node_id not in drops_by_node or d.current_value > drops_by_node[d.node_id].current_value:
                drops_by_node[d.node_id] = d

        runners_needing_routing: List[Runner] = []
        runner_maps: Dict[int, Tuple[Dict[int, float], Dict[int, Optional[int]]]] = {}

        for runner in world.runners:
            rid = runner.id
            here = runner.current_node
            carrying = runner.carrying_loot
            capacity = runner.max_capacity

            if runner.status == "STUNNED":
                log(f"[tick {world.tick:03d}] Runner {rid}: mode=STUNNED target={here} action=HOLD")
                raw_actions.append({"runner_id": rid, "action": "HOLD"})
                continue

            hit_here_now = risk_model.point_hit_risk(world.nodes[here].x, world.nodes[here].y, 1)
            if here in drops_by_node and carrying < capacity and hit_here_now < 0.35:
                drop_here = drops_by_node[here]
                reserved_drop_ids.add(drop_here.drop_id)
                log(f"[tick {world.tick:03d}] Runner {rid}: mode=COLLECT drop={drop_here.drop_id} val={drop_here.current_value:.1f} action=COLLECT")
                raw_actions.append({"runner_id": rid, "action": "COLLECT"})
                continue

            if here in world.safehouses and carrying >= CONFIG["min_opportunistic_loot"]:
                log(f"[tick {world.tick:03d}] Runner {rid}: mode=OPPORTUNISTIC_DEPOSIT safehouse={here} loot={carrying:.1f} action=DEPOSIT")
                raw_actions.append({"runner_id": rid, "action": "DEPOSIT"})
                continue

            dist_m, prev_m = self.graph_engine.dijkstra_risk(here, risk_model, carrying)
            runner_maps[rid] = (dist_m, prev_m)
            runners_needing_routing.append(runner)

        candidate_pairings: List[Tuple[float, int, int, int]] = []

        for runner in runners_needing_routing:
            rid = runner.id
            dist_m, prev_m = runner_maps[rid]

            if runner.carrying_loot < runner.max_capacity:
                # STAGE C: Rolling Horizon Planner
                chain_candidates = []
                if CONFIG.get("enable_horizon_planner", True):
                    chain_candidates = self.evaluate_horizon_planner(
                        runner, dist_m, prev_m, world, reserved_drop_ids, avg_lambda, t_start
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

        candidate_pairings.sort(key=lambda item: item[0], reverse=True)
        assigned_runners: Set[int] = set()

        for util, rid, did, hops_drop in candidate_pairings:
            if rid in assigned_runners or did in reserved_drop_ids:
                continue

            runner = next((r for r in runners_needing_routing if r.id == rid), None)
            if runner is None:
                continue

            dist_m, prev_m = runner_maps[rid]
            reachable_safes = [s for s in world.safehouses if s in dist_m and dist_m[s] != INF]
            nearest_safe = min(reachable_safes, key=lambda s: dist_m[s], default=None)
            hops_to_safe = max(0, len(self.graph_engine.path(runner.current_node, nearest_safe, prev=prev_m)) - 1) if nearest_safe is not None else 999

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

        # Route remaining unassigned runners
        for runner in runners_needing_routing:
            rid = runner.id
            if rid in assigned_runners:
                continue

            dist_m, prev_m = runner_maps[rid]
            reachable_safes = [s for s in world.safehouses if s in dist_m and dist_m[s] != INF]

            if runner.carrying_loot > 0 and reachable_safes:
                def safe_cost(s: int) -> float:
                    base_d = dist_m[s]
                    congestion = targeted_safehouses.get(s, 0) * CONFIG["safehouse_congestion_pen"] * 35.0
                    return base_d + congestion

                chosen_safe = min(reachable_safes, key=safe_cost)
                targeted_safehouses[chosen_safe] = targeted_safehouses.get(chosen_safe, 0) + 1
                assigned_targets[rid] = ("RETURN", chosen_safe)
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
                    hit_step = risk_model.point_hit_risk(world.nodes[step_node].x, world.nodes[step_node].y, 1)
                    hit_here = risk_model.point_hit_risk(world.nodes[here].x, world.nodes[here].y, 1)

                    if hit_step >= 0.8:
                        if here in world.safehouses and carrying > 0:
                            log(f"[tick {world.tick:03d}] Runner {rid}: PANIC DEPOSIT at safehouse {here}")
                            act = {"runner_id": rid, "action": "DEPOSIT"}
                        elif hit_here < 0.5:
                            log(f"[tick {world.tick:03d}] Runner {rid}: HAZARD EVASION HOLD at {here}")
                            act = {"runner_id": rid, "action": "HOLD"}
                        else:
                            best_esc, min_hit = None, 2.0
                            for nbr, w in self.graph_engine.adj_current.get(here, []):
                                if w != INF and nbr in world.nodes:
                                    nhit = risk_model.point_hit_risk(world.nodes[nbr].x, world.nodes[nbr].y, 1)
                                    if nhit < min_hit:
                                        min_hit = nhit
                                        best_esc = nbr
                            if best_esc is not None and min_hit < hit_here:
                                log(f"[tick {world.tick:03d}] Runner {rid}: EMERGENCY DETOUR to {best_esc}")
                                act = {"runner_id": rid, "action": "TRAVERSE", "target_node": best_esc}
                            else:
                                act = {"runner_id": rid, "action": "HOLD"}
                    else:
                        act = {"runner_id": rid, "action": "TRAVERSE", "target_node": step_node}
                else:
                    if here in world.safehouses and carrying > 0:
                        act = {"runner_id": rid, "action": "DEPOSIT"}
                    else:
                        act = {"runner_id": rid, "action": "HOLD"}

            raw_actions.append(act)

        return raw_actions

    def step(self, raw_state: Dict[str, Any]) -> List[Dict[str, Any]]:
        t_start = time.perf_counter()
        raw_tick = raw_state.get("tick", 0) if isinstance(raw_state, dict) else 0
        tick = _safe_int(raw_tick, 0)

        try:
            world = Adapter.parse_world(raw_state)
            for r in world.runners:
                self.known_runner_ids.add(r.id)

            self.graph_engine.update_world(world)
            candidate_actions = self.decide(world, t_start=t_start)
            final_actions = Validator.validate_actions(candidate_actions, world, self.known_runner_ids)

        except Exception as e:
            log(f"CRITICAL ENGINE ERROR at tick {tick}: {e}\n{traceback.format_exc()}")
            fallback_ids = self.known_runner_ids or {1}
            final_actions = [{"runner_id": rid, "action": "HOLD"} for rid in sorted(fallback_ids)]

        elapsed_ms = (time.perf_counter() - t_start) * 1000.0
        if CONFIG["log_timing"]:
            log(f"[tick {tick:03d}] latency: {elapsed_ms:5.2f} ms | actions: {len(final_actions)}")

        return final_actions


def main() -> None:
    engine = BotEngine()

    while True:
        try:
            line = sys.stdin.readline()
            if not line:
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
