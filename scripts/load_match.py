#!/usr/bin/env python3
"""Fetch (then cache) a match and print a one-line summary.

Usage::

    python scripts/load_match.py                # 2022 World Cup Final
    python scripts/load_match.py 3869685        # explicit match id
    python scripts/load_match.py --refresh      # force a re-fetch

Run it twice: the first run fetches from StatsBomb, the second is served
entirely from the local cache (and works with the network unplugged).
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# Make ``touchline`` importable when run straight from the repo.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from touchline.data import StatsBombLoader, WC_2022_FINAL  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "match_id",
        nargs="?",
        type=int,
        default=WC_2022_FINAL,
        help="StatsBomb match id (default: 2022 World Cup Final).",
    )
    parser.add_argument("--cache-dir", default="data_cache")
    parser.add_argument("--refresh", action="store_true", help="Force a re-fetch.")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    loader = StatsBombLoader(cache_dir=args.cache_dir)
    events_path = f"events/{args.match_id}.json"
    was_cached = loader.is_cached(events_path) and not args.refresh

    start = time.perf_counter()
    match = loader.load_match(args.match_id, refresh=args.refresh)
    elapsed = time.perf_counter() - start

    source = "cache" if was_cached else "network"
    print(
        f"\n{match}\n"
        f"  source : {source}\n"
        f"  load   : {elapsed * 1000:.0f} ms\n"
        f"  cached : {loader.cache_dir / events_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
