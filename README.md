# Touchline

An autonomous match-analyst agent. Touchline investigates a **finished** soccer
match and produces a grounded tactical report by forming and testing hypotheses
against event data — the way a human analyst does, rather than narrating vibes.

The core loop: load a match → compute tactical metrics → form a hypothesis about
the story of the game → go back to the data to confirm or reject it → iterate →
write a grounded report where **every claim traces to a tool result**.

## Status

Built up commit by commit. Current layer:

- **Commit 1 — Scaffold + data loader.** A StatsBomb open-data loader that pulls
  a match's events and lineups and caches them locally. After the first fetch,
  every load is served from cache and works fully offline.

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
scripts/
  load_match.py      # CLI: fetch/cache a match and print a summary
data_cache/          # local JSON cache (gitignored, safe to delete)
```
