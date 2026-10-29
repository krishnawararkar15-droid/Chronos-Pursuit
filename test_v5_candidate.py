#!/usr/bin/env python3
"""
Test script to run my_bot_v5_candidate.py vs my_bot_v4.py on Seeds 1..10
"""
import copy
import math
import os
import sys

KIT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Subway_Escape")
if os.path.join(KIT_DIR, "practice_arena") not in sys.path:
    sys.path.insert(0, os.path.join(KIT_DIR, "practice_arena"))

from practice_arena import PracticeArena

PYTHON = sys.executable

def compare(seeds=range(1, 11)):
    print(f"Comparing v4-final vs candidate on seeds {list(seeds)}...")
    diffs = []
    for s in seeds:
        a_v4 = PracticeArena(commands=[[PYTHON, "my_bot_v4.py"]], seed=s, ticks=300, verbose=False, log_dir="practice_logs/cand_test_v4")
        st_v4 = a_v4.run()
        s_v4 = st_v4[1].score

        a_cand = PracticeArena(commands=[[PYTHON, "my_bot_v5_candidate.py"]], seed=s, ticks=300, verbose=False, log_dir="practice_logs/cand_test_v5")
        st_cand = a_cand.run()
        s_cand = st_cand[1].score

        d = s_cand - s_v4
        diffs.append(d)
        print(f"Seed {s:2d}: v4=${s_v4:10,.1f} | cand=${s_cand:10,.1f} | Diff={d:+10,.1f}")

    print("-" * 50)
    print(f"Mean Diff: ${sum(diffs)/len(diffs):+,.1f} (Wins: {sum(1 for d in diffs if d > 0)}/{len(diffs)})")

if __name__ == "__main__":
    compare()
