# Touchline

An autonomous match-analyst agent. Touchline investigates a **finished** soccer
match and produces a grounded tactical report by forming and testing hypotheses
against event data — the way a human analyst does, rather than narrating vibes.

The core loop: load a match → compute tactical metrics → form a hypothesis about
the story of the game → go back to the data to confirm or reject it → iterate →
write a grounded report where **every claim traces to a tool result**.

## Status

Built up commit by commit. Current layers:

- **Commit 1 — Scaffold + data loader.** A StatsBomb open-data loader that pulls
  a match's events and lineups and caches them locally. After the first fetch,
  every load is served from cache and works fully offline.
- **Commit 2 — Tool interface + first tool.** A uniform `Tool` contract (name,
  description, pydantic input schema, `run`) with an introspectable registry —
  the agent's action space. First tool: an **xG timeline** giving each team's
  per-minute cumulative expected-goals curve.
- **Commit 3 — Tool executor.** A thin in-process executor that looks up a
  named tool, validates its arguments, runs it, and always returns a structured
  `ExecutionResult` — a clean result or an informative, model-readable error
  (unknown tool, invalid arguments, no match, execution error). Never crashes,
  so a stochastic agent can read the error and recover.

## Data source

[StatsBomb open data](https://github.com/statsbomb/open-data): free, clean,
event-level JSON covering competitions including the 2022 World Cup. No scraping,
no API keys, no cost.

## Quickstart

```bash
# Load the 2022 World Cup Final (Argentina 3-3 France). First run fetches
# and caches; run it again to see it load from cache.
python scripts/load_match.py
python scripts/load_match.py            # second run -> source: cache
```

```python
from touchline.data import StatsBombLoader, WC_2022_FINAL

loader = StatsBombLoader(cache_dir="data_cache")
match = loader.load_match(WC_2022_FINAL)   # cached after first call
print(match)                               # Match(match_id=..., teams='...', events=...)
print(match.events[0])                     # raw StatsBomb event dict
```

The loader depends only on the Python standard library, so the data plumbing is
never the reason a run fails to start. Analysis and visualization dependencies
are listed in `requirements.txt` for later commits.

## Layout

```
touchline/
  data/
    loader.py        # StatsBomb fetch-and-cache loader + Match container
  tools/
    base.py          # Tool contract, ToolResult, ToolRegistry
    xg_timeline.py   # first tool: per-minute cumulative xG per team
  agent/
    executor.py      # runs a named tool with validated args -> ExecutionResult
scripts/
  load_match.py         # CLI: fetch/cache a match and print a summary
  check_xg_timeline.py  # verify the xG tool against hand-computed totals
  check_executor.py     # verify the executor never crashes on bad calls
data_cache/          # local JSON cache (gitignored, safe to delete)
```

## Tools

Each analysis is a `Tool`: a `name`, an analyst-facing `description`, a pydantic
`Input` model (validation + JSON schema for function calling), and a `run` that
returns a `ToolResult` (a one-line `summary` plus the full structured `data`
behind it, so every claim can be audited). Tools register into a `ToolRegistry`,
which hands the model function-calling specs and looks tools up by name — the
investigation loop never needs to know which specific tool it is calling.

```python
from touchline.data import StatsBombLoader, WC_2022_FINAL
from touchline.tools import REGISTRY

match = StatsBombLoader().load_match(WC_2022_FINAL)
result = REGISTRY.get("xg_timeline").run(match)
print(result.summary)               # Cumulative xG through minute 122: ...
result.data["cumulative_xg"]         # {team: [per-minute cumulative xG, ...]}
```
