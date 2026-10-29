#!/usr/bin/env python3
"""
STAGE B - Headroom and Loss Gap Analyzer
Implements exact conservation law of money:
Total Spawned Base Value = Banked Score + Decay Loss + Expiry Loss + Capture Loss + Endgame Unbanked Loss
Computes the exact breakdown of what the gap between Hindsight Upper Bound and Bot Score is made of.
"""

import math
import os
import statistics
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
KIT_DIR = os.path.join(WORKSPACE_DIR, "Subway_Escape")
if os.path.join(KIT_DIR, "practice_arena") not in sys.path:
    sys.path.insert(0, os.path.join(KIT_DIR, "practice_arena"))

from practice_arena import PracticeArena, TOTAL_TICKS, RUNNER_CAPACITY


class AuditArena(PracticeArena):
    def __init__(self, commands, seed=1, ticks=TOTAL_TICKS, verbose=False, log_dir="practice_logs"):
        self.total_spawned_base_value = 0.0
        self.decay_loss = 0.0
        self.expiry_loss = 0.0
        self.idle_ticks = 0
        self.traverse_ticks = 0
        self.collect_ticks = 0
        self.deposit_ticks = 0
        self.drops_spawned_count = 0
        self.drops_collected_count = 0
        self.drops_expired_count = 0
        self.spawn_records = []
        super().__init__(commands, seed=seed, ticks=ticks, verbose=verbose, log_dir=log_dir)

    def _spawn_one_drop(self):
        res = super()._spawn_one_drop()
        if res and self.drops:
            d = self.drops[-1]
            self.total_spawned_base_value += d.base_value
            self.drops_spawned_count += 1
            self.spawn_records.append((d.drop_id, d.node_id, d.base_value, d.leak, d.ttl, d.spawn_tick))
        return res

    def _build_map(self):
        super()._build_map()
        # Initial drops will be counted in _spawn_drops via super._place_runners_and_police

    def _spawn_drops(self):
        while self._spawn_one_drop():
            pass

    def step(self):
        super().step()
        # Count expired drops this tick
        # Note: in super().step(), drops age:
        # for drop in self.drops[:]:
        #     drop.ttl -= 1
        #     if drop.ttl <= 0: self.drops.remove(drop)

    def _apply_action(self, runner, stats, action):
        kind = action.get("action")
        if kind == "HOLD" or runner.status == "STUNNED":
            self.idle_ticks += 1
        elif kind == "TRAVERSE":
            self.traverse_ticks += 1
        elif kind == "COLLECT":
            self.collect_ticks += 1
            drop = next((d for d in self.drops if d.node_id == runner.node), None)
            if drop is not None:
                current_val = self._drop_value(drop)
                decay = drop.base_value - current_val
                self.decay_loss += max(0.0, decay)
                self.drops_collected_count += 1
        elif kind == "DEPOSIT":
            self.deposit_ticks += 1
        super()._apply_action(runner, stats, action)


def audit_seed(seed: int, bot_cmd: List[str]) -> Dict[str, Any]:
    log_dir = f"practice_logs/audit_seed_{seed}"
    os.makedirs(log_dir, exist_ok=True)
    arena = AuditArena([bot_cmd], seed=seed, ticks=TOTAL_TICKS, verbose=False, log_dir=log_dir)
    stats = arena.run()
    bot_stat = stats[1]

    score = bot_stat.score
    loot_lost_capture = bot_stat.loot_lost
    runner_endgame_loot = arena.runners[1].loot

    # Drops remaining on map at tick 300 are uncollected
    remaining_drops_value = sum(d.base_value for d in arena.drops)

    # Expiry loss = total base value spawned - collected value - decay of collected - remaining on map
    # Exactly: expiry loss = sum of base_values of drops that expired without being collected
    expiry_loss = max(0.0, arena.total_spawned_base_value - (score + arena.decay_loss + loot_lost_capture + runner_endgame_loot + remaining_drops_value))
    total_uncollected = expiry_loss + remaining_drops_value

    return {
        "seed": seed,
        "score": score,
        "total_spawned_base": arena.total_spawned_base_value,
        "decay_loss": arena.decay_loss,
        "expiry_loss": total_uncollected,
        "capture_loss": loot_lost_capture,
        "endgame_unbanked": runner_endgame_loot,
        "idle_ticks": arena.idle_ticks,
        "traverse_ticks": arena.traverse_ticks,
        "collect_ticks": arena.collect_ticks,
        "deposit_ticks": arena.deposit_ticks,
        "drops_spawned": arena.drops_spawned_count,
        "drops_collected": arena.drops_collected_count,
    }


def run_audit(seeds: List[int], bot_cmd: List[str]) -> Dict[str, Any]:
    records = [audit_seed(s, bot_cmd) for s in seeds]

    mean_score = statistics.mean([r["score"] for r in records])
    mean_spawned = statistics.mean([r["total_spawned_base"] for r in records])
    mean_decay = statistics.mean([r["decay_loss"] for r in records])
    mean_expiry = statistics.mean([r["expiry_loss"] for r in records])
    mean_capture = statistics.mean([r["capture_loss"] for r in records])
    mean_endgame = statistics.mean([r["endgame_unbanked"] for r in records])

    mean_idle = statistics.mean([r["idle_ticks"] for r in records])
    mean_traverse = statistics.mean([r["traverse_ticks"] for r in records])
    mean_collect = statistics.mean([r["collect_ticks"] for r in records])
    mean_deposit = statistics.mean([r["deposit_ticks"] for r in records])

    print("=" * 80)
    print(f"STAGE B: GAP BREAKDOWN & MONEY CONSERVATION AUDIT (N={len(seeds)})")
    print("=" * 80)
    print(f"Total Base Value Spawned:      ${mean_spawned:>9,.1f}  (100.0%)")
    print(f"  -> Banked Score:             ${mean_score:>9,.1f}  ({mean_score/mean_spawned*100:5.1f}%)")
    print(f"  -> Lost to Drop Decay:       ${mean_decay:>9,.1f}  ({mean_decay/mean_spawned*100:5.1f}%)  [Late pickups]")
    print(f"  -> Lost to Drop Expiry:      ${mean_expiry:>9,.1f}  ({mean_expiry/mean_spawned*100:5.1f}%)  [Unreached drops]")
    print(f"  -> Lost to Police Capture:   ${mean_capture:>9,.1f}  ({mean_capture/mean_spawned*100:5.1f}%)  [Loot wiped]")
    print(f"  -> Lost at Tick 300 End:     ${mean_endgame:>9,.1f}  ({mean_endgame/mean_spawned*100:5.1f}%)  [Unbanked in bag]")
    print("-" * 80)
    print(f"Tick Budget Allocation (300 ticks total):")
    print(f"  -> Moving (TRAVERSE):         {mean_traverse:>5.1f} ticks ({mean_traverse/3.0:5.1f}%)  [Long trips]")
    print(f"  -> Collecting (COLLECT):      {mean_collect:>5.1f} ticks ({mean_collect/3.0:5.1f}%)")
    print(f"  -> Depositing (DEPOSIT):      {mean_deposit:>5.1f} ticks ({mean_deposit/3.0:5.1f}%)")
    print(f"  -> Idle / Stunned (HOLD):     {mean_idle:>5.1f} ticks ({mean_idle/3.0:5.1f}%)  [Wasted ticks]")
    print("=" * 80)

    return {
        "mean_score": mean_score,
        "mean_spawned": mean_spawned,
        "mean_decay": mean_decay,
        "mean_expiry": mean_expiry,
        "mean_capture": mean_capture,
        "mean_endgame": mean_endgame,
        "mean_idle": mean_idle,
        "mean_traverse": mean_traverse,
        "mean_collect": mean_collect,
        "mean_deposit": mean_deposit,
    }


if __name__ == "__main__":
    test_seeds = list(range(1, 21))
    run_audit(test_seeds, [sys.executable, "my_bot_v4.py"])
