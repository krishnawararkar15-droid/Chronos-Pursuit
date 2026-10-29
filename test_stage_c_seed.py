#!/usr/bin/env python3
"""
Test Horizon Planner directly on Seeds 1, 2, 3 and print detailed comparisons.
"""
import copy
import math
import os
import sys
import time

# Add arena path
KIT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Subway_Escape")
if os.path.join(KIT_DIR, "practice_arena") not in sys.path:
    sys.path.insert(0, os.path.join(KIT_DIR, "practice_arena"))

from practice_arena import PracticeArena

PYTHON = sys.executable

def test_seeds():
    seeds = [1, 2, 3, 4, 5]
    print(f"Testing Seeds {seeds}...")
    for s in seeds:
        # Run v4-final
        arena_v4 = PracticeArena(commands=[[PYTHON, "my_bot_v4.py"]], seed=s, ticks=300, verbose=False, log_dir=None)
        arena_v4.run()
        sc_v4 = arena_v4.match_stats["scores"].get(1, 0.0)

        # Run horizon bot
        # We will test passing BOT_CONFIG_JSON
        arena_hz = PracticeArena(commands=[[PYTHON, "my_bot.py"]], seed=s, ticks=300, verbose=False, log_dir=None)
        arena_hz.run()
        sc_hz = arena_hz.match_stats["scores"].get(1, 0.0)

        diff = sc_hz - sc_v4
        print(f"Seed {s}: v4=${sc_v4:,.1f} | hz=${sc_hz:,.1f} | Diff={diff:+,.1f}")

if __name__ == "__main__":
    test_seeds()
