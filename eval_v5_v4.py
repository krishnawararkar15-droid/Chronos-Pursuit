import sys
import os
from run_eval import evaluate_sweep, compute_paired_diff

SEEDS = list(range(1, 11))
PYTHON = sys.executable

v4_stats, t_v4 = evaluate_sweep([PYTHON, 'my_bot_v4.py'], SEEDS, workers=10, log_dir_prefix='practice_logs/cmp_v4')
v5_stats, t_v5 = evaluate_sweep([PYTHON, 'my_bot_v5.py'], SEEDS, workers=10, log_dir_prefix='practice_logs/cmp_v5')

v4_mean = sum(s.score for s in v4_stats.values()) / len(SEEDS)
v5_mean = sum(s.score for s in v5_stats.values()) / len(SEEDS)
paired = compute_paired_diff(v5_stats, v4_stats, SEEDS)

print(f"v4 Mean: ${v4_mean:,.1f}")
print(f"v5 Mean: ${v5_mean:,.1f}")
print(f"Paired Diff (v5 - v4): +${paired['mean_diff']:,.1f} +/- ${paired['ci_95']:,.1f} (Wins: {paired['improved']}/{paired['n']})")

for s in SEEDS:
    d = v5_stats[s].score - v4_stats[s].score
    print(f"Seed {s:2d}: v4=${v4_stats[s].score:10,.1f} | v5=${v5_stats[s].score:10,.1f} | Diff={d:+10,.1f}")
