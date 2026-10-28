# PRD — Subway Escape Bot (AI × Maths Hackathon, IIT Patna / Celesta)

## 1. One-line goal
Build a **crash-proof, stdlib-only Python bot** that maximizes *deposited* capital over 300 ticks by combining shortest paths on a dynamic graph, time-decay-aware task assignment, and predictive (space-time) police avoidance — tuned on a local simulator.

## 2. What the judges actually score
Total capital **deposited** in safehouses at tick 300. Not collected, not carried. Rank = score (likely averaged over some maps/seeds). Prizes: top 3 teams.

## 3. Hard constraints (from the problem PDF)
| Item | Value |
|---|---|
| Ticks | exactly 300 |
| Time per tick | 1 s (aim for < 0.3 s) |
| Memory | 256 MB |
| I/O | Interactive JSON via stdin/stdout, one state in → one response out per tick |
| DQ rule | 3 **consecutive** ticks with no valid response → process killed, bot disqualified |
| Actions | `TRAVERSE` (needs `target_node`), `HOLD`, `COLLECT`, `DEPOSIT` |
| Response | `{"runner_actions":[{"runner_id":1,"action":"TRAVERSE","target_node":3}]}` |
| Money decay | `M(t) = M0 * exp(-λ t)`, plus TTL expiry and engine threshold floor |
| Police | circular capture region, kinematic `(x,y,vx,vy)`; inflates edge `current_weight` non-linearly, `∞` if blocked |
| Capture | runner STUNNED 3 ticks (ignores commands) **and carried loot → 0** (deposited money is safe) |
| Manual control | prohibited |

> **Update:** the organizers released an official repo (`unknown-tech-ui/Subway_Escape`) with `docs`, `practice_arena`, `practice_logs`, `sample_bot`, `submission`, `templates`, `third_party`, `tools`. It overrides any assumption in this PRD. Our local test harness = the official practice arena; the "standard library only / single bot.py" requirement applies only if the repo doesn't say otherwise.

## 4. Unknowns (resolved by reading the repo in Phase 0)
1. Exact JSON schema of the incoming state (field names for runners, nodes, edges, drops, police, tick, λ, TTL).
2. Does a TRAVERSE take 1 tick per edge or multiple ticks (edge length / speed)? Can runners be mid-edge? (PDF says HOLD "mid-edge" is possible → yes.)
3. How many runners per team; carry capacity; can several runners stand on one node.
4. Is COLLECT automatic on arrival or an explicit action? (PDF lists it as an explicit action.)
5. Is DEPOSIT automatic at a safehouse or explicit? (explicit per PDF.)
6. Submission format (single file? language? filename?) and **whether re-submission is allowed** before 31 Oct 11:59 PM IST.
7. Scoring across multiple matches/seeds? Tie-breakers?
8. Leakage λ: per-drop, per-runner, or global? Does carried inventory decay at the same rate?

> Design rule: the bot must run correctly even if I guess some of these wrong. Everything schema-dependent lives in ONE adapter module/section.

## 5. Why teams lose vs. win (the separator)
**Teams that lose**
1. **Crash / invalid JSON / debug prints on stdout** → 3 missed ticks → DQ → score 0. (Most common failure in interactive-bot contests.)
2. Mis-parse the schema, never test against real input.
3. Greedy "nearest drop" with no deposit logic → carry a huge pile, get caught, lose it all.
4. Ignore TTL/decay → walk 20 ticks to a worthless drop.
5. Ignore police motion → only react after entering the hazard radius.
6. Multiple runners chase the same drop.
7. No endgame logic → carrying loot at tick 300 = worth zero.
8. Over-engineer (RL, heavy search) and blow the 1 s limit or never finish.

**Teams that win**
1. Robust I/O shell: try/except around everything, fallback action, watchdog timer, stderr-only logging.
2. Value-aware planning: value of a drop = `M0*exp(-λ·t_arrival)` if not past TTL, divided by time cost.
3. **Deposit economics**: decide *when* to bank using the marginal gain of one more pickup vs. decay + capture risk.
4. **Predictive police avoidance**: extrapolate police `(x+vx·k, y+vy·k)` for k future ticks and penalize edges/nodes whose arrival time falls inside radius + margin.
5. Runner coordination: unique assignment (Hungarian / greedy-with-reservation), zones.
6. Hard endgame deadline: stop collecting when `dist_to_safehouse + margin > ticks_left`.
7. Parameters tuned on a local simulator (hundreds of seeds), not by feel.

## 6. Product requirements

### P0 (must ship today)
- R1 Never crash; always emit valid JSON for every runner every tick; never print anything else to stdout.
- R2 Schema adapter + auto-logging of first N raw states to `debug.log` (stderr/file).
- R3 Dijkstra on `current_weight` (treat `inf`/null as blocked); path reconstruction; next-hop selection.
- R4 State machine per runner: `SEEK → COLLECT → RETURN → DEPOSIT`, plus `STUNNED` (send HOLD) and `EVADE`.
- R5 Safe default: if no sensible action → `HOLD`.
- R6 Time guard: per-tick compute budget ≤ 0.35 s; fall back to greedy if exceeded.

### P1 (the winning edge)
- R7 Drop scoring: `score = value_at_arrival / (travel_ticks + ε)` with TTL feasibility and a "can I still bank it?" check.
- R8 Deposit policy: bank when carried value × decay-over-detour + risk exceeds expected marginal pickup gain; always bank when endgame deadline near.
- R9 Space-time police risk model (predicted positions, radius + safety margin, stun-cost-aware edge penalties).
- R10 Multi-runner assignment without conflicts; reservation table for drops and safehouses.
- R11 Endgame planner (last ~40 ticks): backward-feasible plan so all carried loot is deposited by tick 300.

### P2 (if time remains)
- R12 Local simulator + parameter sweep (random search) to tune weights/margins.
- R13 Lookahead rollout (2–3 candidate plans per runner, pick best by simulated expected value).
- R14 Opponent-agnostic robustness tests (extreme police density, blocked graph, zero drops).

## 7. Algorithm design (summary)
- **Graph**: adjacency dict `u → {v: current_weight}`; precompute static all-pairs (Floyd–Warshall or Dijkstra from each safehouse) on `base_weight` for fast heuristics; re-run Dijkstra each tick on `current_weight` from each runner.
- **Risk-augmented cost**: `cost(u,v) = current_weight(u,v) + λ_risk · P_hit(u,v,t_arrival) · (carried_value + stun_penalty)`. Where `P_hit` ∈ {0,1} or soft (sigmoid of distance to predicted police minus radius).
- **Drop utility** for runner r: `U(d) = [M0_d·e^{-λ·τ(r→d)} − risk_cost] · e^{-λ·τ(d→nearest safehouse)} / (τ(r→d) + τ(d→safe))`, only if `τ(r→d) < TTL_remaining` and bankable before tick 300.
- **Assignment**: build runner×drop utility matrix; solve with greedy-by-best-utility with reservations (Hungarian only if small and cheap).
- **Bank-now test**: bank if `carried·(1−e^{−λ·Δ_next}) + risk_next ≥ gain_next` or capacity full or deadline.
- **Stun handling**: if `STUNNED`, send `HOLD` (commands ignored anyway); after release, replan from scratch.
- **Mid-edge**: if runner is mid-edge and police approach, allow `HOLD` or reversal only if rules permit (verify from rulebook).

## 8. Non-functional requirements
- Python 3.8+ compatible, **standard library only** (no numpy), single file `bot.py` (plus optional `starter` wrapper if mandatory).
- Deterministic given same input (seeded RNG).
- Memory < 100 MB, per-tick < 0.35 s.
- All logs → `stderr` or file, never `stdout`.

## 9. Success metrics
1. Zero crashes / invalid outputs across 1000 simulated + replayed matches.
2. ≥ 2× the score of a "nearest-drop greedy" baseline on the local simulator.
3. 0 loot lost at tick 300 (all carried banked) in ≥ 95 % of runs.
4. Capture events per match minimized vs. baseline (≥ 60 % reduction).

## 10. Risks and mitigations
| Risk | Mitigation |
|---|---|
| Wrong schema guess | Phase 0 collects real sample; adapter is the only schema-aware code |
| Timeouts | watchdog + cheap fallback + budget guard |
| Rules differ from simulator | Keep simulator assumptions in one config; prefer robust heuristics over fragile constants |
| Late submission | Submit working baseline by end of Phase 3, improve after (if re-submission allowed) |
| Over-fitting to simulator | Randomize map/λ/police params widely in sweep |

## 11. Deliverables
`bot.py` (submission), `sim.py` (local simulator), `tests/` (schema + edge-case tests), `README.md` (short write-up of approach — useful for your profile/portfolio), `debug.log` sample.
