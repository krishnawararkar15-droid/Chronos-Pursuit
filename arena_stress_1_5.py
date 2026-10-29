"""
Subway Escape - PRACTICE ARENA (STRESS VARIANT 1: Speed x1.5, Radius x1.3, Decay x1.5, TTL x0.7)
"""

import json
import math
import os
import queue
import random
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field

TOTAL_TICKS = 300
TIME_LIMIT_SECONDS = 1.0
STARTUP_GRACE_SECONDS = 2.0
MAX_CONSECUTIVE_MISSES = 3

NUM_NODES = 60
NUM_MONEY_SPOTS = 10
NUM_SAFEHOUSES = 4
NUM_POLICE = 6
WORLD_SIZE = 500.0
STUN_TICKS = 3
POLICE_RADIUS = 15.0 * 1.3  # 19.5
RUNNER_CAPACITY = 500.0
MAX_DROPS_ON_MAP = 8


@dataclass
class Node:
    id: int
    x: float
    y: float
    type: str


@dataclass
class Edge:
    a: int
    b: int
    base_weight: float
    current_weight: float = 0.0


@dataclass
class Runner:
    id: int
    node: int
    x: float
    y: float
    loot: float = 0.0
    status: str = "ACTIVE"
    stun_left: int = 0


@dataclass
class Drop:
    drop_id: int
    node_id: int
    target_safehouse: int
    base_value: float
    leak: float
    ttl: int
    spawn_tick: int


@dataclass
class Cop:
    id: int
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    speed: float = 3.75
    goal_x: float = 0.0
    goal_y: float = 0.0
    radius: float = POLICE_RADIUS


@dataclass
class BotStats:
    score: float = 0.0
    collections: int = 0
    collected_value: float = 0.0
    deposits: int = 0
    captures: int = 0
    loot_lost: float = 0.0
    invalid_actions: int = 0
    misses: int = 0
    disqualified: bool = False
    total_response_ms: float = 0.0
    max_response_ms: float = 0.0
    answered_ticks: int = 0


class BotProcess:
    def __init__(self, bot_id, command, log_path):
        self.bot_id = bot_id
        self.command = command
        self.lines = queue.Queue()
        self.alive = False
        self.first_ask = True
        self.error = None
        self._log_file = open(log_path, "w", encoding="utf-8")
        try:
            self.proc = subprocess.Popen(
                command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._log_file,
                text=True, bufsize=1, encoding="utf-8")
            self.alive = True
            threading.Thread(target=self._read_loop, daemon=True).start()
        except Exception as problem:
            self.error = str(problem)

    def _read_loop(self):
        for line in self.proc.stdout:
            self.lines.put(line)
        self.lines.put(None)

    def ask(self, payload):
        if not self.alive:
            return None, 0.0
        while True:
            try:
                stale = self.lines.get_nowait()
                if stale is None:
                    self.alive = False
                    return None, 0.0
            except queue.Empty:
                break

        limit = TIME_LIMIT_SECONDS + (STARTUP_GRACE_SECONDS if self.first_ask else 0.0)
        self.first_ask = False
        started = time.time()
        try:
            self.proc.stdin.write(payload + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError):
            self.alive = False
            return None, 0.0
        try:
            line = self.lines.get(timeout=limit)
        except queue.Empty:
            return None, time.time() - started
        if line is None:
            self.alive = False
            return None, time.time() - started
        return line, time.time() - started

    def stop(self):
        try:
            self.proc.terminate()
        except Exception:
            pass
        self._log_file.close()


class PracticeArena:
    def __init__(self, commands, seed=1, ticks=TOTAL_TICKS, verbose=False, log_dir="practice_logs"):
        self.rng = random.Random(seed)
        self.seed = seed
        self.ticks = ticks
        self.verbose = verbose
        self.commands = {i + 1: cmd for i, cmd in enumerate(commands)}
        self.stats = {bot_id: BotStats() for bot_id in self.commands}
        self.misses_in_a_row = {bot_id: 0 for bot_id in self.commands}
        self.bots = {}
        self.log_dir = log_dir

        self.nodes = {}
        self.edges = []
        self.runners = {}
        self.drops = []
        self.cops = []
        self.next_drop_id = 1
        self.tick = 0

        self._build_map()
        self._place_runners_and_police()
        self._update_edge_weights()

    def _build_map(self):
        rng = self.rng
        points = []
        while len(points) < NUM_NODES:
            x, y = rng.uniform(10, WORLD_SIZE - 10), rng.uniform(10, WORLD_SIZE - 10)
            if all(math.hypot(x - px, y - py) > 22 for px, py in points):
                points.append((x, y))

        kinds = (["safehouse"] * NUM_SAFEHOUSES + ["money_spot"] * NUM_MONEY_SPOTS
                 + ["junction"] * (NUM_NODES - NUM_SAFEHOUSES - NUM_MONEY_SPOTS))
        rng.shuffle(kinds)
        for i, ((x, y), kind) in enumerate(zip(points, kinds), start=1):
            self.nodes[i] = Node(i, x, y, kind)

        pairs = set()
        for a in self.nodes.values():
            closest = sorted((math.hypot(a.x - b.x, a.y - b.y), b.id) for b in self.nodes.values() if b.id != a.id)
            for _, other in closest[:3]:
                pairs.add((min(a.id, other), max(a.id, other)))

        parent = {i: i for i in self.nodes}
        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i
        for a, b in pairs:
            parent[find(a)] = find(b)
        while len({find(i) for i in self.nodes}) > 1:
            best = None
            for a in self.nodes.values():
                for b in self.nodes.values():
                    if find(a.id) != find(b.id):
                        d = math.hypot(a.x - b.x, a.y - b.y)
                        if best is None or d < best[0]:
                            best = (d, a.id, b.id)
            _, a, b = best
            pairs.add((min(a, b), max(a, b)))
            parent[find(a)] = find(b)

        for a, b in sorted(pairs):
            d = math.hypot(self.nodes[a].x - self.nodes[b].x, self.nodes[a].y - self.nodes[b].y)
            self.edges.append(Edge(a, b, d, d))

    def _place_runners_and_police(self):
        for bot_id in self.commands:
            start = self.rng.choice(list(self.nodes))
            node = self.nodes[start]
            self.runners[bot_id] = Runner(bot_id, start, node.x, node.y)
        for cop_id in range(1, NUM_POLICE + 1):
            # Speed x1.5 (2.25 to 5.25)
            cop = Cop(cop_id, self.rng.uniform(40, 460), self.rng.uniform(40, 460),
                      speed=self.rng.uniform(2.25, 5.25), radius=POLICE_RADIUS)
            cop.goal_x, cop.goal_y = self.rng.uniform(20, 480), self.rng.uniform(20, 480)
            self.cops.append(cop)
        self._spawn_drops()

    def _move_police(self):
        for cop in self.cops:
            dx, dy = cop.goal_x - cop.x, cop.goal_y - cop.y
            dist = math.hypot(dx, dy)
            if dist < cop.speed * 1.5:
                cop.goal_x, cop.goal_y = self.rng.uniform(20, 480), self.rng.uniform(20, 480)
                dx, dy = cop.goal_x - cop.x, cop.goal_y - cop.y
                dist = math.hypot(dx, dy) or 1.0
            cop.vx, cop.vy = dx / dist * cop.speed, dy / dist * cop.speed
            cop.x += cop.vx
            cop.y += cop.vy

    def _update_edge_weights(self):
        for edge in self.edges:
            a, b = self.nodes[edge.a], self.nodes[edge.b]
            closest = float("inf")
            for cop in self.cops:
                dx, dy = b.x - a.x, b.y - a.y
                length_sq = dx * dx + dy * dy
                t = 0.0 if length_sq == 0 else max(0.0, min(1.0, ((cop.x - a.x) * dx + (cop.y - a.y) * dy) / length_sq))
                closest = min(closest, math.hypot(cop.x - (a.x + t * dx), cop.y - (a.y + t * dy)))
            if closest <= POLICE_RADIUS:
                edge.current_weight = float("inf")
            else:
                closeness = max(0.0, 1.0 - (closest - POLICE_RADIUS) / 45.0)
                edge.current_weight = edge.base_weight + 60.0 * closeness * closeness

    def _drop_value(self, drop):
        return drop.base_value * math.exp(-drop.leak * (self.tick - drop.spawn_tick))

    def _spawn_one_drop(self):
        if len(self.drops) >= MAX_DROPS_ON_MAP:
            return False
        taken = {d.node_id for d in self.drops}
        spots = [n.id for n in self.nodes.values() if n.type == "money_spot" and n.id not in taken]
        safes = [n.id for n in self.nodes.values() if n.type == "safehouse"]
        if not spots:
            return False
        # Decay x1.5 (0.006 to 0.030), TTL x0.7 (24 to 56 ticks)
        self.drops.append(Drop(self.next_drop_id, self.rng.choice(spots), self.rng.choice(safes),
                               self.rng.uniform(150, 750), self.rng.uniform(0.006, 0.030),
                               self.rng.randint(24, 56), self.tick))
        self.next_drop_id += 1
        return True

    def _spawn_drops(self):
        while self._spawn_one_drop():
            pass

    def _state_for(self, bot_id):
        return json.dumps({
            "tick": self.tick,
            "graph_nodes": [{"id": n.id, "x": n.x, "y": n.y, "type": n.type} for n in self.nodes.values()],
            "graph_edges": [{"from": e.a, "to": e.b, "base_weight": e.base_weight,
                             "current_weight": -1.0 if e.current_weight == float("inf") else e.current_weight}
                            for e in self.edges],
            "my_runners": [{"id": r.id, "current_node": r.node, "x": r.x, "y": r.y,
                            "carrying_loot": r.loot, "max_capacity": RUNNER_CAPACITY,
                            "status": r.status, "stun_ticks_remaining": r.stun_left}
                           for r in self.runners.values() if r.id == bot_id],
            "active_money_drops": [{"drop_id": d.drop_id, "node_id": d.node_id,
                                    "target_safehouse_node": d.target_safehouse,
                                    "current_value": self._drop_value(d), "leak_lambda": d.leak,
                                    "ttl_remaining": d.ttl} for d in self.drops],
            "police_officers": [{"id": c.id, "x": c.x, "y": c.y, "vx": c.vx, "vy": c.vy, "radius": c.radius}
                                for c in self.cops],
        })

    def _read_actions(self, bot_id, answer):
        if answer is None:
            return None
        try:
            data = json.loads(answer.strip())
            actions = data["runner_actions"]
            if not isinstance(actions, list):
                raise ValueError("runner_actions must be a list")
            return [a for a in actions if isinstance(a, dict)]
        except Exception:
            return None

    def step(self):
        self._move_police()
        self._update_edge_weights()
        for runner in self.runners.values():
            if runner.status == "STUNNED":
                runner.stun_left -= 1
                if runner.stun_left <= 0:
                    runner.status = "ACTIVE"

        answers = {}
        for bot_id, bot in self.bots.items():
            stats = self.stats[bot_id]
            if stats.disqualified:
                continue
            raw, seconds = bot.ask(self._state_for(bot_id))
            allowed = TIME_LIMIT_SECONDS + (STARTUP_GRACE_SECONDS if self.tick == 0 else 0.0)
            actions = self._read_actions(bot_id, raw) if seconds <= allowed else None
            if actions is None:
                stats.misses += 1
                self.misses_in_a_row[bot_id] += 1
                if self.misses_in_a_row[bot_id] >= MAX_CONSECUTIVE_MISSES or not bot.alive:
                    stats.disqualified = True
                continue
            self.misses_in_a_row[bot_id] = 0
            stats.answered_ticks += 1
            stats.total_response_ms += seconds * 1000
            stats.max_response_ms = max(stats.max_response_ms, seconds * 1000)
            answers[bot_id] = actions

        for bot_id, runner in self.runners.items():
            stats = self.stats[bot_id]
            if runner.status == "STUNNED" or stats.disqualified:
                continue
            mine = [a for a in answers.get(bot_id, []) if a.get("runner_id") == runner.id]
            if not mine:
                continue
            self._apply_action(runner, stats, mine[0])

        for runner in self.runners.values():
            for cop in self.cops:
                if math.hypot(runner.x - cop.x, runner.y - cop.y) <= cop.radius:
                    stats = self.stats[runner.id]
                    if runner.status != "STUNNED":
                        stats.captures += 1
                    stats.loot_lost += runner.loot
                    runner.status, runner.stun_left, runner.loot = "STUNNED", STUN_TICKS, 0.0
                    break

        for drop in self.drops[:]:
            drop.ttl -= 1
            if drop.ttl <= 0:
                self.drops.remove(drop)
        if self.rng.random() < 0.6:
            self._spawn_one_drop()
        self.tick += 1

    def _apply_action(self, runner, stats, action):
        kind = action.get("action")
        if kind == "HOLD":
            return
        if kind == "TRAVERSE":
            target = action.get("target_node")
            edge_ok = any({e.a, e.b} == {runner.node, target} and e.current_weight != float("inf") for e in self.edges)
            if target in self.nodes and edge_ok:
                runner.node, runner.x, runner.y = target, self.nodes[target].x, self.nodes[target].y
            else:
                stats.invalid_actions += 1
        elif kind == "COLLECT":
            drop = next((d for d in self.drops if d.node_id == runner.node), None)
            if drop is None:
                stats.invalid_actions += 1
                return
            value = self._drop_value(drop)
            taken = min(RUNNER_CAPACITY - runner.loot, value)
            runner.loot += taken
            self.drops.remove(drop)
            stats.collections += 1
            stats.collected_value += taken
        elif kind == "DEPOSIT":
            if self.nodes[runner.node].type == "safehouse" and runner.loot > 0:
                stats.score += runner.loot
                stats.deposits += 1
                runner.loot = 0.0
            else:
                stats.invalid_actions += 1
        else:
            stats.invalid_actions += 1

    def run(self):
        os.makedirs(self.log_dir, exist_ok=True)
        for bot_id, command in self.commands.items():
            log_path = os.path.join(self.log_dir, f"bot{bot_id}_seed{self.seed}_stderr.log")
            bot = BotProcess(bot_id, command, log_path)
            if bot.error:
                self.stats[bot_id].disqualified = True
            self.bots[bot_id] = bot
        try:
            for _ in range(self.ticks):
                self.step()
        finally:
            for bot in self.bots.values():
                bot.stop()
        return self.stats
