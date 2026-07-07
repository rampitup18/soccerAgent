#!/usr/bin/env python3
"""Verify the xG-timeline tool against independently computed truth.

Checks, on the 2022 World Cup Final:

* the tool's per-team totals equal a straight sum of shot xGs (computed here
  from the raw events, not via the tool);
* every cumulative curve is monotonically non-decreasing (cumulative xG can
  never fall) and ends exactly at the team's total;
* the series is on a per-minute grid;
* the penalty shootout is excluded by default but appears when requested.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from touchline.data import StatsBombLoader, WC_2022_FINAL  # noqa: E402
from touchline.tools import REGISTRY  # noqa: E402


def hand_totals(events, include_shootout):
    """Ground truth: sum shot xG straight from the events."""
    totals = defaultdict(float)
    for e in events:
        if e.get("type", {}).get("name") != "Shot":
            continue
        if not include_shootout and e.get("period") == 5:
            continue
        xg = e.get("shot", {}).get("statsbomb_xg")
        if xg is not None:
            totals[e["team"]["name"]] += float(xg)
    return totals


def main() -> int:
    loader = StatsBombLoader(cache_dir="data_cache")
    match = loader.load_match(WC_2022_FINAL)
    tool = REGISTRY.get("xg_timeline")

    checks: list[tuple[bool, str]] = []

    def check(cond: bool, label: str) -> None:
        checks.append((bool(cond), label))

    # --- default run (shootout excluded) ---
    res = tool.run(match)
    data = res.data
    teams = data["teams"]
    truth = hand_totals(match.events, include_shootout=False)

    for t in teams:
        got = data["total_xg"][t]
        exp = round(truth.get(t, 0.0), 4)
        check(abs(got - exp) < 1e-6, f"total xG {t}: tool={got} vs truth={exp}")

    # cumulative ends at the total, and never decreases
    for t in teams:
        series = data["cumulative_xg"][t]
        monotone = all(b >= a - 1e-9 for a, b in zip(series, series[1:]))
        check(monotone, f"{t} cumulative is non-decreasing")
        check(
            abs(series[-1] - data["total_xg"][t]) < 1e-6,
            f"{t} cumulative ends at total ({series[-1]} == {data['total_xg'][t]})",
        )

    # per-minute grid: consecutive minutes differ by exactly 1
    minutes = data["minutes"]
    per_minute = all(b - a == 1 for a, b in zip(minutes, minutes[1:]))
    check(per_minute, f"grid is per-minute (0..{minutes[-1]})")
    check(minutes[0] == 0, "grid starts at minute 0")

    # shot counts equal number of shots folded in
    check(
        sum(data["shot_count"].values()) == len(data["shots"]),
        "shot_count total matches number of shots",
    )

    # --- shootout inclusion changes the totals ---
    res_so = tool.run(match, include_shootout=True)
    truth_so = hand_totals(match.events, include_shootout=True)
    for t in res_so.data["teams"]:
        got = res_so.data["total_xg"][t]
        exp = round(truth_so.get(t, 0.0), 4)
        check(abs(got - exp) < 1e-6, f"[+shootout] total xG {t}: {got} == {exp}")
    check(
        res_so.data["total_xg"] != data["total_xg"],
        "including the shootout changes the totals",
    )

    # --- report ---
    print(f"\n{match}")
    print(f"summary: {res.summary}\n")
    width = max(len(label) for _, label in checks)
    for ok, label in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label:<{width}}")

    failed = [label for ok, label in checks if not ok]
    print(f"\n{len(checks) - len(failed)}/{len(checks)} checks passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
