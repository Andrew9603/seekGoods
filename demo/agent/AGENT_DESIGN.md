# Freight Dispatch Agent Design

This agent is rule-first and tool-driven. It uses the simulator API as its only runtime source of truth and keeps the LLM on a narrow, optional preference-understanding path.

## Architecture

- Perception: `get_driver_status`, `query_cargo`, and `query_decision_history` collect current driver state, nearby online cargo, and recent action history.
- Memory: `history_analyzer`, online `region_stats`, and the preference cache summarize what has already happened without reading raw benchmark data files.
- Planning: `preference_planner`, `rest_planner`, and `reposition_planner` handle mandatory stops, monthly off-days, rest windows, and low-value repositioning.
- Tool Use: `SimulationApiPort` is the boundary for simulator tools, cargo queries, history queries, and optional model calls.
- Decision: `cargo_filter`, `scoring`, and `action_validator` turn candidates into a validated action.
- Reflection: `agent_debug` logs and `tools/run_strategy_variants.py` compare profiles after full local runs.
- LLM: `LLMHelper` is a low-frequency preference interpreter. It does not see cargo lists and never chooses orders.

## Why Not Use The LLM At Every Step

Order selection is a numeric optimization problem with tight time, distance, rest, and validation constraints. Calling an LLM for every order would spend tokens, add latency, and make the result less stable.

The LLM is only useful for natural-language preference interpretation. The rule parser runs first. When enabled by profile, the LLM receives only the driver preference text and a JSON schema request. The output is merged into the same structure used by the rule parser. If the call times out, fails, or returns invalid JSON, the rule result is used.

## Compliance

- The agent does not read `cargo_dataset.jsonl` or `drivers.json` at runtime.
- The strategy does not branch on hard-coded `driver_id`.
- API keys are not stored in code, config, logs, or experiment outputs.
- Every returned action passes through `action_validator`.
- Safety and mandatory-rest constraints are not part of preference tradeoff.
- Preference tradeoff is limited to income-script preference penalties. Validation errors are never accepted as tradeoff.

## Profiles And Experiments

`config/strategy_profiles.json` defines the leaderboard profiles:

- `strict_compliance`: conservative, preference-first, no active preference tradeoff.
- `balanced`: current high-score baseline with a 1.3 penalty safety multiplier.
- `profit_aggressive`: lower thresholds and larger queries for local income maximization.
- `hidden_robust`: conservative unknown-preference handling with the optional LLM parser enabled.
- `online_robust`: preference-firewall-first profile for hidden online drivers. It accepts lower local income in exchange for stricter handling of unknown hard constraints, time windows, regions, required stops, and distance limits.

## Preference Firewall

`preference_firewall.py` runs before order scoring. It blocks hard violations such as banned cargo categories, forbidden regions, required-stop deadline conflicts, rest-window overlaps, distance limits, and conservative-mode risks. Soft violations may enter scoring with a penalty. In `online_robust`, unknown high-risk preference text triggers conservative mode instead of income tradeoff.

Run all variants with:

```powershell
python demo\agent\tools\run_strategy_variants.py
```

The script writes `demo/results/experiments/summary.csv` and `best_profile.txt`.

## Query ROI

The agent logs `query_k`, returned cargo count, scan cost minutes, selected action, selected score, and expected net profit. Analyze the latest run with:

```powershell
python demo\agent\tools\analyze_query_roi.py
```

The script writes `demo/results/experiments/query_roi.csv` and a suggested `query_k` anchor.
