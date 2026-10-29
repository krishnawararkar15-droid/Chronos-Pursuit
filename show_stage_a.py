import json

with open('stage_a_results.json') as f:
    d = json.load(f)

print("Completed sections in stage_a_results.json:")
for k in d:
    print(" -", k)

for s in ["solo_TUNE", "solo_VALIDATE"]:
    if s in d:
        p1 = d[s]['paired_v4_v1']
        p2 = d[s]['paired_v4_sm']
        v4 = d[s]['v4']
        v1 = d[s]['v1']
        sm = d[s]['sample']
        print(f"\n=== {s} ===")
        print(f"v4-final:   Mean=${v4['mean_score']:,.1f} | Med=${v4['median_score']:,.1f} | Caught={v4['mean_caught']:.2f} | BadActs={v4['total_bad_acts']} | MaxMs={v4['peak_max_ms']:.0f}ms")
        print(f"v1-safe:    Mean=${v1['mean_score']:,.1f} | Med=${v1['median_score']:,.1f} | Caught={v1['mean_caught']:.2f} | BadActs={v1['total_bad_acts']} | MaxMs={v1['peak_max_ms']:.0f}ms")
        print(f"sample_bot: Mean=${sm['mean_score']:,.1f} | Med=${sm['median_score']:,.1f} | Caught={sm['mean_caught']:.2f} | BadActs={sm['total_bad_acts']} | MaxMs={sm['peak_max_ms']:.0f}ms")
        print(f"Paired v4 vs v1:     +${p1['mean_diff']:,.1f} +/- ${p1['ci_95']:,.1f} [{p1['ci_lower']:,.1f}, {p1['ci_upper']:,.1f}] (Wins: {p1['improved']}/{p1['n']})")
        print(f"Paired v4 vs sample: +${p2['mean_diff']:,.1f} +/- ${p2['ci_95']:,.1f} [{p2['ci_lower']:,.1f}, {p2['ci_upper']:,.1f}] (Wins: {p2['improved']}/{p2['n']})")

for s in ["self_play_TUNE", "self_play_VALIDATE"]:
    if s in d:
        p = d[s]['paired']
        v4 = d[s]['v4']
        v1 = d[s]['v1']
        print(f"\n=== {s} ===")
        print(f"v4-final: Mean=${v4['mean_score']:,.1f} | Med=${v4['median_score']:,.1f} | Caught={v4['mean_caught']:.2f} | BadActs={v4['total_bad_acts']}")
        print(f"v1-safe:  Mean=${v1['mean_score']:,.1f} | Med=${v1['median_score']:,.1f} | Caught={v1['mean_caught']:.2f} | BadActs={v1['total_bad_acts']}")
        print(f"Paired Diff: +${p['mean_diff']:,.1f} +/- ${p['ci_95']:,.1f} (Wins: {p['improved']}/{p['n']})")

for m in ["arena_stress_1_5_TUNE", "arena_stress_1_5_VALIDATE", "arena_stress_2_0_TUNE", "arena_stress_2_0_VALIDATE"]:
    if m in d:
        p = d[m]['paired_v4_v1']
        v4 = d[m]['v4']
        v1 = d[m]['v1']
        sm = d[m]['sample']
        print(f"\n=== {m} ===")
        print(f"v4-final:   Mean=${v4['mean_score']:,.1f} | Med=${v4['median_score']:,.1f} | Caught={v4['mean_caught']:.2f} | BadActs={v4['total_bad_acts']}")
        print(f"v1-safe:    Mean=${v1['mean_score']:,.1f} | Med=${v1['median_score']:,.1f} | Caught={v1['mean_caught']:.2f} | BadActs={v1['total_bad_acts']}")
        print(f"sample_bot: Mean=${sm['mean_score']:,.1f} | Med=${sm['median_score']:,.1f} | Caught={sm['mean_caught']:.2f} | BadActs={sm['total_bad_acts']}")
        print(f"Paired v4 vs v1: +${p['mean_diff']:,.1f} +/- ${p['ci_95']:,.1f} (Wins: {p['improved']}/{p['n']})")
