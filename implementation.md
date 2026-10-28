# implementation.md — Subway Escape Bot (for Anti Gravity)

> **v2 — updated after the official repo was released:** https://github.com/unknown-tech-ui/Subway_Escape (folders: `docs`, `practice_arena`, `practice_logs`, `sample_bot`, `submission`, `templates`, `third_party`, `tools`). The repo is the **source of truth**. Where this file or the PRD conflicts with the repo's README/docs, the repo wins. We use the official `practice_arena` + `tools` as our test harness instead of writing a simulator from scratch.
>
> **How to use:** Paste `PRD.md` first, then paste this file. Tell Anti Gravity: *"Read both. Do ONLY the phase I name. Stop after its Definition of Done and show me the results."* Then run phases 0 → 9 in order.

## Global rules (apply to every phase)
1. Language, file layout and allowed libraries: **whatever `submission/` and the README specify.** If unspecified, default to Python 3 standard library only. Start from `templates/` / `sample_bot/` rather than from a blank file.
2. **stdout is sacred**: only the JSON response, one line per tick, flushed. All logs go to `stderr` or `debug.log`.
3. Every tick: wrap everything in `try/except`; on any error emit a valid fallback (`HOLD` for each runner you know of) — never crash.
4. All schema-specific field names live in ONE section/class: `Adapter`. Nothing else may touch raw JSON keys.
5. Treat `inf`, `null`, `"inf"`, `"Infinity"`, `1e9+` weights as blocked.
6. Per-tick compute budget ≤ 0.35 s (check with `time.perf_counter()`); if exceeded, return the greedy plan.
7. Keep tunable numbers in a `CONFIG` dict at the top of the file.
8. After each phase: run the tests, print a short summary of what changed, list any assumptions made.

---

## Phase 0 — Read the official repo (do this BEFORE any code)
**Human (5 min):** `git clone https://github.com/unknown-tech-ui/Subway_Escape.git` and open the folder in Anti Gravity. Also check the WhatsApp group for any announcement after the repo (fixes, rule changes, "Corrected" commits). Note: the repo was updated recently, so `git pull` again right before final submission.

**Prompt to Anti Gravity:**
> Read the entire repo: `README.md`, everything in `docs/`, `templates/`, `sample_bot/`, `submission/`, `tools/`, `practice_arena/`, and skim `practice_logs/` and `third_party/`. Do NOT write bot code yet. Produce `SPEC_NOTES.md` containing:
> 1. The exact stdin state JSON schema (field → type → meaning) taken from real files/logs.
> 2. The exact stdout action schema and every validation rule.
> 3. Game rules that affect strategy: ticks, traversal time per edge, mid-edge behavior, number of runners, capacity, COLLECT/DEPOSIT semantics, stun/capture details, police movement model, edge-weight inflation formula, decay/TTL/floor rules, win/score formula, tie-breakers.
> 4. **Submission rules:** exact file(s), language(s), allowed libraries, filename, how to package, whether and how many times we can re-submit, what `submission/` expects.
> 5. How to run the practice arena (exact commands), what it outputs, how many maps/seeds exist, and how to run many seeds automatically.
> 6. What `sample_bot` does and its approximate score in the arena (this is our baseline).
> 7. A list of anything still ambiguous.

**Done when:** `SPEC_NOTES.md` exists and the sample bot has been run in the practice arena with its score recorded. **Send me `SPEC_NOTES.md`** and I will adjust the later phases to the real rules before you continue.

---

## Phase 1 — Robust I/O shell + Adapter (the anti-DQ phase)
**Prompt to Anti Gravity:**
> Starting from the official template/sample bot (keep its I/O conventions) and `SPEC_NOTES.md`, create our bot file (in the format `submission/` requires) with:
> 1. A main loop that reads one JSON state per tick from stdin, calls `decide(state)`, prints one JSON line to stdout, flushes.
> 2. An `Adapter` class converting raw state → internal dataclasses: `Node(id, type, x, y)`, `Edge(u, v, base_w, cur_w)`, `Drop(node, m0, born_tick, ttl, lambda)`, `Runner(id, node, edge_progress, status, carrying, capacity)`, `Police(x, y, vx, vy, radius)`, `World(tick, ticks_left, ...)`.
> 3. Tolerant parsing: missing keys → defaults, inf/null weights → `math.inf`, unknown fields ignored.
> 4. Fallback: on any exception, output `HOLD` for all known runner ids (cache runner ids from previous ticks).
> 5. Raw-state logging for the first 5 ticks to `debug.log`, plus a per-tick timing line to stderr.
> 6. A `Validator` that checks the output JSON (valid action names, `target_node` present for TRAVERSE and adjacent to the runner's node) and downgrades illegal actions to `HOLD`.
> Do NOT implement strategy yet — every runner just HOLDs.

**Tests:** feed real states (from `practice_logs/` or the arena) through the bot; fuzz with 200 corrupted/partial states (missing keys, nulls, empty arrays) — bot must always print valid JSON.
**Done when:** zero crashes on fuzz, output validated, stdout contains nothing but JSON.

---

## Phase 2 — Graph engine
**Prompt:**
> Add a `GraphEngine` to `bot.py`:
> - Build adjacency from edges (respect direction if edges are directed; check `SPEC_NOTES.md`).
> - `dijkstra(source, weights='current')` returning `dist` and `prev`; blocked edges (inf) are skipped.
> - `path(source, target)` and `next_hop(source, target)`.
> - Precompute static distances (`base_weight`) from every safehouse and every drop node for cheap heuristics; cache and invalidate only when topology changes.
> - Handle mid-edge runners: distance from runner to a node = remaining edge distance + dist from that edge's endpoint (check rules for whether reversal is allowed).
> - Unit tests: random graphs vs. brute-force Floyd–Warshall; graph with blocked edges; disconnected target returns `inf` and the bot does not crash.

**Done when:** tests pass and a 200-node graph runs all-runners Dijkstra in < 20 ms.

---

## Phase 3 — Baseline strategy (SUBMITTABLE VERSION)
**Prompt:**
> Implement the per-runner state machine in `bot.py`:
> - `STUNNED` → `HOLD`.
> - If at a node with a collectable drop → `COLLECT`.
> - If at a safehouse with carried inventory > 0 and bank-condition true → `DEPOSIT`.
> - Otherwise choose a target:
>   - **SEEK**: best drop by `value_at_arrival / (travel + 1)`, where `value_at_arrival = m0 * exp(-lambda * (age + travel))`; skip drops whose TTL expires before arrival.
>   - **RETURN**: nearest safehouse by current Dijkstra distance.
> - Bank-condition v1: carried ≥ `CONFIG['bank_threshold']` OR no feasible drop OR `ticks_left <= dist_to_safehouse + CONFIG['endgame_margin']`.
> - Move with `TRAVERSE` to the next hop along the shortest path.
> - Reservation table so two runners never target the same drop in the same tick.
> Keep it simple and correct. Log each runner's mode and target per tick.

**Done when:** on the sample state it outputs sensible legal actions; no crash. **Submit this baseline to the portal now** (if re-submission is allowed, you can overwrite later). If only one submission is allowed, skip submitting until Phase 8.

---

## Phase 4 — Test harness on the OFFICIAL practice arena
**Prompt:**
> Use the official `practice_arena` and `tools/` as our evaluator. Do not rewrite the engine. Build `run_eval.py` that:
> - Runs our bot in the arena over all available maps/seeds (parallelize if safe), with the official timeout rules.
> - Prints a table: mean/median/min score per map, captures, loot lost at end, timeouts/invalid actions, max tick time.
> - Compares against `sample_bot` and a "do nothing" bot.
> - Saves each run's log so we can replay/debug (use the same format as `practice_logs/`).
> Only if the arena has too few maps/seeds or no randomization, write a small `sim_extra.py` that perturbs parameters (police speed, λ, drop density) for stress testing; document its assumptions in `SIM_ASSUMPTIONS.md`.

**Done when:** one command evaluates our bot vs sample_bot across all maps and prints the table.

---

## Phase 5 — Police prediction + space-time risk (BIGGEST WIN)
**Prompt:**
> Add a `RiskModel`:
> - Predict each police position for ticks `k = 0..H` (H ≈ 15): `p(k) = p0 + v*k` (clamp to map; reflect if patrol logic suggests it — read from rules).
> - For a candidate move/path, compute arrival tick at each node/edge and check whether the runner would be inside `radius + safety_margin` of the predicted police at that tick.
> - `edge_cost = current_weight + risk_penalty * hit_probability * (carried_value + stun_cost)`, where `stun_cost = 3 ticks * avg_income_per_tick`.
> - Use this cost in Dijkstra (time-dependent approximation: arrival time = tick + dist so far).
> - If every route is dangerous: choose between `HOLD` (let hazard pass) and detour by comparing expected loss; never walk straight into predicted capture.
> - Make `safety_margin`, `H`, `risk_penalty` configurable.
> Measure in the practice arena: capture count and score before/after.

**Done when:** captures drop ≥ 50 % vs Phase 3 on 200 seeds without lowering mean score.

---

## Phase 6 — Economics: pickup vs. bank, TTL, decay
**Prompt:**
> Replace the Phase 3 heuristics:
> - **Drop utility** `U = (v_arrive − risk_cost) * exp(-lambda * tau(drop→nearest_safe)) / (tau(runner→drop) + tau(drop→safe) + 1)`.
> - Feasibility: skip if `tau_arrive ≥ ttl_remaining`, or if it can't be banked before the end.
> - **Bank-now test**: compare `bank_value_now` vs. `expected_value_after_next_pickup` (including decay of carried inventory over the detour and the risk of capture while carrying). Bank when banking wins, when capacity is full, or when a police predicted to cross the planned route.
> - Opportunistic banking: if a safehouse is within a small detour of the current path, bank.
> - Tune `bank_threshold` dynamically from λ: higher λ → bank earlier.
> Measure in the practice arena, report improvement.

**Done when:** mean score improves ≥ 15 % over Phase 5, and "loot decayed while carried" metric drops.

---

## Phase 7 — Multi-runner coordination + endgame planner
**Prompt:**
> - Build a runner×drop utility matrix and assign with greedy-by-best-utility with reservations (use Hungarian only if matrix ≤ 12×30 and it fits in budget). Allow reassignment each tick if a much better option appears (hysteresis `CONFIG['switch_gain']` to avoid thrashing).
> - Spread runners across zones so they don't compete or block each other; spread safehouse usage.
> - **Endgame (last ~40 ticks)**: for each runner compute `latest_departure = ticks_left − dist_to_safehouse − margin`; forbid new pickups that break feasibility; at the final ticks, prioritize any DEPOSIT possible. Guarantee: no runner ends the match holding loot that could have been banked.
> - Add a "panic mode": if a runner will be captured next tick anyway, prefer actions that preserve value (e.g., deposit if at safehouse).

**Done when:** deadline-loot-lost ≈ 0 across 200 seeds; no duplicate-target events logged.

---

## Phase 8 — Parameter tuning + robustness sweep
**Prompt:**
> - Write `tune.py`: random search (using the arena/harness) (or simple evolutionary strategy) over `CONFIG` (bank_threshold, safety_margin, risk_penalty, H, switch_gain, endgame_margin). Evaluate each candidate on all arena maps/seeds (plus `sim_extra.py` perturbations if available). Hold out some maps for validation so we don't overfit. Pick configs by **mean − 0.5·std** (robustness, not luck).
> - Run stress tests: 0 drops, all edges blocked, 1 runner, 10 runners, huge graph (1000 nodes), police on top of safehouse. Bot must never crash or exceed 0.35 s.
> - Freeze the best config into `bot.py`.

**Done when:** tuned bot beats Phase 7 by a clear margin on held-out seeds; stress suite 100 % green.

---

## Phase 9 — Final checks + submission
**Prompt:**
> - `git pull` the official repo to catch late fixes; re-run the full arena evaluation and the sample states.
> - Confirm: no prints to stdout other than JSON; no external imports; file size small; runs on Python 3.8+.
> - Remove debug-heavy logging (keep stderr minimal).
> - Write `README.md` (1 page): problem, approach (graph + risk model + economics + endgame), results table (baseline vs final), how to run. This is portfolio material for your MBZUAI application.
> - Produce the exact submission artifact following `submission/` instructions (naming, packaging, validation script if provided).

**Human checklist before clicking Submit:**
- [ ] Ran the final file in the official practice arena with zero errors/timeouts.
- [ ] Passed any official submission validator in `submission/` or `tools/`.
- [ ] Submitted before **31 Oct 2026, 11:59 PM IST** (aim for 24 h earlier).
- [ ] Saved a copy of the submitted file + README on GitHub.

---

## Appendix A — Kickoff prompt (paste this FIRST, right after PRD.md)
> You are the implementer on a hackathon project. I will name one phase at a time from `implementation.md`. Rules: do only that phase; keep stdout clean (JSON only); never crash; follow the library/language rules in `submission/`; put every schema-specific key in the Adapter; keep tunables in CONFIG; after each phase print (1) what you built, (2) tests run + results, (3) assumptions you made, (4) what you need from me. Ask me at most ONE clarifying question per phase, only if truly blocked; otherwise choose a safe default and note it. Start with Phase 0: the repo is already cloned in this workspace (https://github.com/unknown-tech-ui/Subway_Escape); read it fully and write SPEC_NOTES.md before any code.

## Appendix B — If the real rules differ from our assumptions
Update `SIM_CONFIG`, rerun the sweep (Phase 8), and keep heuristics robust: prefer margins and fallbacks over fragile constants.

## Appendix C — Debug prompts
- "Replay `debug.log` tick N and explain why runner R chose action A with the scores for each candidate."
- "Find the 5 worst arena maps/seeds and explain what went wrong in each."
- "Profile the slowest tick and make it 2× faster without changing behavior."
