# SPEC_NOTES.md — Comprehensive Specifications & Reverse-Engineered Rules
**Competition:** AI × Maths Hackathon · OptimatX Club · IIT Patna (Celesta)  
**Challenge:** Subway Escape – The Ultimate Chase  
**Source Repository:** https://github.com/unknown-tech-ui/Subway_Escape  
**Analysis Date:** 2026-10-28  

---

## 1. Exact stdin State JSON Schema

The engine feeds your bot a single, unformatted JSON line per tick via `stdin`. The match runs for exactly **300 ticks** (tick `0` through `299`).

```json
{
  "tick": 12,
  "graph_nodes": [
    { "id": 1, "x": 52.4, "y": 310.9, "type": "safehouse" },
    { "id": 6, "x": 188.0, "y": 97.2, "type": "money_spot" },
    { "id": 20, "x": 240.5, "y": 401.7, "type": "junction" }
  ],
  "graph_edges": [
    { "from": 1, "to": 20, "base_weight": 93.4, "current_weight": 96.1 },
    { "from": 20, "to": 6, "base_weight": 55.0, "current_weight": -1.0 }
  ],
  "my_runners": [
    {
      "id": 1,
      "current_node": 20,
      "x": 240.5,
      "y": 401.7,
      "carrying_loot": 270.5,
      "max_capacity": 500.0,
      "status": "ACTIVE",
      "stun_ticks_remaining": 0
    }
  ],
  "active_money_drops": [
    {
      "drop_id": 1012,
      "node_id": 6,
      "target_safehouse_node": 1,
      "current_value": 412.8,
      "leak_lambda": 0.011,
      "ttl_remaining": 47
    }
  ],
  "police_officers": [
    {
      "id": 1,
      "x": 200.2,
      "y": 130.0,
      "vx": 2.1,
      "vy": -0.8,
      "radius": 15.0
    }
  ]
}
```

### Detailed Field Breakdown

| Path | Type | Nullable | Description & Edge Cases |
| :--- | :--- | :--- | :--- |
| `tick` | `int` | No | Current tick index, $0 \le \text{tick} < 300$. |
| `graph_nodes[]` | `list[object]` | No | Static network node list (persists across ticks). |
| `graph_nodes[].id` | `int` | No | Unique node identifier. |
| `graph_nodes[].x` | `float` | No | X-coordinate on map ($[0, 500]$ typical). |
| `graph_nodes[].y` | `float` | No | Y-coordinate on map ($[0, 500]$ typical). |
| `graph_nodes[].type` | `str` | No | Node type: `"safehouse"`, `"money_spot"`, or `"junction"`. |
| `graph_edges[]` | `list[object]` | No | Undirected tracks. Each edge is listed once. |
| `graph_edges[].from` | `int` | No | Endpoint node $u$. |
| `graph_edges[].to` | `int` | No | Endpoint node $v$. Bidirectional traversal permitted. |
| `graph_edges[].base_weight` | `float` | No | Static Euclidean track distance. |
| `graph_edges[].current_weight` | `float` | No | Dynamic weight. **`-1.0` means blocked** ($\infty$). |
| `my_runners[]` | `list[object]` | No | List of your bot's runners. |
| `my_runners[].id` | `int` | No | Unique identifier for your runner. |
| `my_runners[].current_node`| `int` | No | Current node ID runner occupies. |
| `my_runners[].x` | `float` | No | Exact X coordinate of runner (matches current node). |
| `my_runners[].y` | `float` | No | Exact Y coordinate of runner (matches current node). |
| `my_runners[].carrying_loot`| `float`| No | Current unbanked loot in backpack. |
| `my_runners[].max_capacity` | `float`| No | Maximum carrying capacity (typically 500.0). |
| `my_runners[].status` | `str` | No | `"ACTIVE"` or `"STUNNED"`. |
| `my_runners[].stun_ticks_remaining` | `int` | No | Remaining stun duration ($0$ when active, $3$ upon capture). |
| `active_money_drops[]` | `list[object]` | No | Active drops on map (can be empty `[]`). |
| `active_money_drops[].drop_id` | `int` | No | Unique ID for the drop. |
| `active_money_drops[].node_id` | `int` | No | Node ID where the drop is located (`money_spot`). |
| `active_money_drops[].target_safehouse_node` | `int` | No | Recommended/designated safehouse for deposit. |
| `active_money_drops[].current_value` | `float` | No | Worth right now: $M(t) = M_0 \cdot e^{-\lambda t}$. |
| `active_money_drops[].leak_lambda` | `float` | No | Drop-specific decay coefficient $\lambda \in [0.004, 0.02]$. |
| `active_money_drops[].ttl_remaining` | `int` | No | Ticks until drop vanishes ($0 \implies$ despawned). |
| `police_officers[]` | `list[object]` | No | Active police units patrolling the subway. |
| `police_officers[].id` | `int` | No | Police officer ID. |
| `police_officers[].x` | `float` | No | Current continuous X position. |
| `police_officers[].y` | `float` | No | Current continuous Y position. |
| `police_officers[].vx` | `float` | No | Velocity vector X component ($\Delta x / \text{tick}$). |
| `police_officers[].vy` | `float` | No | Velocity vector Y component ($\Delta y / \text{tick}$). |
| `police_officers[].radius` | `float`| No | Capture danger radius ($15.0$ standard). |

---

## 2. Exact stdout Action Schema & Validation Rules

Your bot must print **exactly one JSON line** per tick to `stdout` and flush immediately.

### Action JSON Format
```json
{
  "runner_actions": [
    {
      "runner_id": 1,
      "action": "TRAVERSE",
      "target_node": 20
    }
  ]
}
```

### Action Types & Parameter Requirements

| Action | Parameters Required | Precondition for Validity | Consequence if Precondition Failed |
| :--- | :--- | :--- | :--- |
| `TRAVERSE` | `target_node`: `int` | An edge $\{u, \text{target\_node}\}$ exists and `current_weight >= 0` (`!= -1.0`). | Action ignored (`BadActs` incremented); runner remains at $u$. |
| `HOLD` | None | None (always legal). | Runner remains at current node. |
| `COLLECT` | None | Runner must occupy a node containing an active drop, and `carrying_loot < max_capacity`. | Action ignored (`BadActs` incremented); tick wasted. |
| `DEPOSIT` | None | Runner must occupy a node of `type == "safehouse"` and have `carrying_loot > 0`. | Action ignored (`BadActs` incremented); tick wasted. |

### Strict Conversation Rules
1. **Never print anything except the JSON string to `stdout`**: Any debug output on `stdout` corrupts JSON deserialization in the judging engine. All diagnostics must be printed to `sys.stderr`.
2. **Always flush**: `sys.stdout.flush()` is mandatory every single tick.
3. **One action per runner**: The list must contain exactly one action for every runner in `my_runners`.
4. **Time limit**: 1.0 second per tick (startup grace 2.0s on tick 0).
5. **DQ Rule**: 3 consecutive ticks without a valid, on-time response triggers immediate process termination and disqualification (score = 0).

---

## 3. Verified Game Rules & Behavioral Dynamics

From analyzing `practice_arena.py` and the problem documentation:

1. **Graph Traversal Timing**:
   - `TRAVERSE` takes the runner to the adjacent target node within **1 tick** if legal.
   - Runners exist on discrete nodes (`runner.node, runner.x, runner.y`).
2. **Dynamic Edge-Weight Inflation Equation**:
   - For every edge segment connecting node $A$ and node $B$, the engine computes the closest distance $d_{\min}$ to all police officers:
     $$\text{If } d_{\min} \le R_{\text{police}} (15.0) \implies \text{weight} = \infty \quad (\text{sent as } -1.0)$$
     $$\text{If } d_{\min} > R_{\text{police}} \implies \text{closeness} = \max\left(0, 1.0 - \frac{d_{\min} - 15.0}{45.0}\right)$$
     $$\text{current\_weight} = \text{base\_weight} + 60.0 \cdot \text{closeness}^2$$
3. **Police Kinematics & Capture Sequence**:
   - Officers move with speed $s \in [1.5, 3.5]$ towards waypoints $(goal_x, goal_y)$.
   - Per-tick execution sequence:
     1. Police positions update: $x \leftarrow x + v_x, y \leftarrow y + v_y$.
     2. Edge weights recalculate based on new police positions.
     3. Runner stun counters decrement.
     4. Bot actions are read and applied (`TRAVERSE`, `COLLECT`, `DEPOSIT`, `HOLD`).
     5. **Police capture check occurs AFTER runner actions are applied.**
     6. If $\text{hypot}(x_{\text{runner}} - x_{\text{cop}}, y_{\text{runner}} - y_{\text{cop}}) \le R_{\text{police}}$:
        - Runner is stunned for 3 ticks (`status: "STUNNED"`, `stun_ticks_remaining: 3`).
        - `carrying_loot` is instantly set to `0.0`.
        - Deposited safehouse capital remains intact.
     7. Active drops decay and TTL decrements by 1.
     8. Probabilistic drop respawn ($P = 0.6$).
4. **Collection Mechanics**:
   - `taken = min(RUNNER_CAPACITY - runner.loot, drop.current_value)`.
   - The drop is removed from the active map immediately.
   - If two competing bots attempt to collect the same drop on the same tick, only one succeeds; the second receives a `BadActs` fault.
5. **Deposit Mechanics**:
   - When on a `safehouse` with `carrying_loot > 0`, sending `DEPOSIT` transfers 100% of carried loot to the banked score.
   - Carried loot resets to `0.0`.
6. **Decay Model**:
   - $M(t) = M_0 \cdot e^{-\lambda t}$.
   - Each drop has its own `leak_lambda` ($\lambda \in [0.004, 0.02]$).
   - Once $TTL \le 0$, the drop expires and disappears.
7. **Endgame Condition**:
   - Match ends at tick 300.
   - Unbanked loot carried by runners at tick 300 is worth **zero points**.

---

## 4. Official Submission Specifications

- **Directory to submit**: `submission/`
- **Metadata file**: `submission/team_info.json`:
  ```json
  {
    "team_name": "Antigravity Elite",
    "team_id": "<ASSIGNED_BY_ORGANIZERS>",
    "members": [
      { "name": "Member 1", "email": "member1@example.com" }
    ],
    "language": "python",
    "entry_file": "my_bot.py",
    "build_command": "",
    "run_command": "python my_bot.py"
  }
  ```
- **Source file**: `submission/my_bot.py`
- **Allowed libraries**: Python 3 standard library only (`heapq`, `json`, `math`, `sys`, `time`, `dataclasses`, `typing`, etc.). No external dependencies (`numpy`, `scipy` are forbidden unless stated).
- **Validation**:
  ```bash
  python tools/check_bot.py --team-info submission/team_info.json
  ```
- **Deadline**: 31 Oct 2026, 11:59 PM IST.

---

## 5. How to Run the Practice Arena

From the root directory:

1. **Verify protocol compliance**:
   ```bash
   python tools/check_bot.py --bot "{python} sample_bot/python/basic_bot.py"
   ```
2. **Run single match**:
   ```bash
   python practice_arena/run_practice.py --bot "{python} sample_bot/python/basic_bot.py"
   ```
3. **Compare bots over N random maps**:
   ```bash
   python practice_arena/run_practice.py --bot "{python} submission/my_bot.py" --bot "{python} sample_bot/python/basic_bot.py" --runs 10 --seed 1
   ```
4. **Replay specific seed with detailed event trace**:
   ```bash
   python practice_arena/run_practice.py --bot "{python} submission/my_bot.py" --seed 42 --ticks 50 --verbose
   ```

---

## 6. Baseline Performance (`sample_bot/python/basic_bot.py`)

Benchmark results across 10 distinct random seeds (Seeds 1–10):

| Metric | Sample Bot Baseline | Antigravity Target |
| :--- | :--- | :--- |
| **Score (Banked $)** | **19,817** | **> 35,000 (+75%)** |
| **Collected Drops** | 59.1 | > 65 |
| **Successful Deposits** | 41.4 | Optimized (higher $/deposit) |
| **Caught by Police** | 0.0 (solo) / 0.2 (competing) | **0.0 strictly** |
| **Loot Lost to Capture** | $0 | **$0** |
| **Invalid Actions (`BadActs`)** | 0.0 (solo) / 8.6 (competing) | **0.0 strictly** |
| **Missed Ticks (`Misses`)** | 0.0 | **0.0 strictly** |
| **Average Latency (`AvgMs`)** | 1.2 ms | < 5.0 ms |
| **Peak Latency (`MaxMs`)** | 145 ms | < 150 ms (Budget: 350 ms) |

### Sample Bot Flaws to Exploit
1. **Zero Police Awareness**: Only checks if track weight is `INF`; never projects officer positions or computes spatial hazard intersections.
2. **Naive Valuation**: Evaluates drops by `current_value / (cost + 1.0)`, ignoring $\lambda$ decay during transit and remaining $TTL$.
3. **Suboptimal Banking Threshold**: Always banks at hardcoded $80\%$ backpack capacity, frequently carrying large amounts near police or wasting ticks banking negligible loot.
4. **No Endgame Drainage**: Carries loot until tick 300 without planning a guaranteed return before match termination.
5. **No Anti-Collision**: In multi-bot games, it clashes directly on drops, incurring high `BadActs` penalties.

---

## 7. Ambiguities & Defensive Strategy

1. **Carried Loot Decay in Official Engine**:
   - In `practice_arena.py`, `carrying_loot` does not decay while inside the backpack.
   - In the official IIT Patna PDF: *"Cash waiting at spawn points or carried in a runner's inventory decays every tick according to the exponential leak formula"*.
   - **Strategy**: Our deposit optimization algorithm models exponential decay on carried loot $L \cdot (1 - e^{-\lambda \Delta t})$. If the official engine decays carried inventory, our bot already optimizes for it; if it doesn't, the policy remains robust and leans slightly conservative toward banking early.
2. **Designated Safehouse (`target_safehouse_node`)**:
   - In `practice_arena.py`, depositing is allowed at *any* safehouse.
   - In the schema, each drop carries a `target_safehouse_node`.
   - **Strategy**: We compute shortest paths to both the designated safehouse and the nearest safehouse, maintaining a configurable routing preference.
3. **Multi-Runner Support**:
   - Practice arena runs 1 runner per team, but schema defines `my_runners` as a list.
   - **Strategy**: Fully vector-matched bipartite assignment table handling $N \ge 1$ runners without race conditions or target collisions.
