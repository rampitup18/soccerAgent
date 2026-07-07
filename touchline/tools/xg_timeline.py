"""xG timeline: cumulative expected goals per team over the course of a match.

Expected goals (xG) estimates the probability a given shot becomes a goal.
Summed over a match it measures the *quality* of chances a team created,
independent of whether they were finished. Plotted cumulatively over time it
reads as a momentum curve: steep steps are big chances, long flat stretches
are spells without threat, and the gap between the two curves is the story of
who was on top and when.

StatsBomb ship an xG value on every shot event (``shot.statsbomb_xg``), so the
timeline computes directly from the shot stream with no modelling of our own.
The penalty shootout (period 5) is excluded by default: those are not
run-of-play chances and would swamp the narrative.

This is Touchline's first tool: a whole-match narrative metric that is trivial
to verify by hand (each team's final cumulative value is just the sum of its
shot xGs).
"""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field

from touchline.data import Match
from touchline.tools.base import Tool, ToolResult, register

# StatsBomb records the penalty shootout as period 5.
_SHOOTOUT_PERIOD = 5


class XGTimelineInput(BaseModel):
    """Inputs for the xG timeline."""

    bin_minutes: int = Field(
        default=1,
        ge=1,
        description="Granularity of the timeline grid, in minutes. 1 gives a "
        "per-minute series.",
    )
    include_shootout: bool = Field(
        default=False,
        description="Include penalty-shootout shots (period 5). Off by "
        "default: a shootout is not run-of-play xG.",
    )


class XGTimelineTool(Tool):
    name = "xg_timeline"
    description = (
        "Compute each team's cumulative expected goals (xG) over the course of "
        "the match as a per-minute series. Use this to see momentum swings, "
        "identify which team created the better chances and when, and quantify "
        "how the balance of play shifted across phases. Returns both teams' "
        "cumulative xG curves, per-team totals and shot counts, and the "
        "individual shots (minute, player, xG, whether it was a goal)."
    )
    Input = XGTimelineInput

    def _run(self, match: Match, inputs: XGTimelineInput) -> ToolResult:  # type: ignore[override]
        shots = self._collect_shots(match, include_shootout=inputs.include_shootout)

        # Preserve a stable team order: teams from the lineups first (so a team
        # that never shot still appears), then any others seen in the shots.
        teams: List[str] = list(match.teams)
        for s in shots:
            if s["team"] not in teams:
                teams.append(s["team"])

        last_minute = max((s["minute"] for s in shots), default=0)
        step = inputs.bin_minutes
        # Grid of minute marks: 0, step, 2*step, ... up to and including the
        # last minute a shot occurred.
        minutes = list(range(0, last_minute + 1, step))
        if minutes[-1] != last_minute:
            minutes.append(last_minute)

        cumulative: Dict[str, List[float]] = {t: [] for t in teams}
        totals: Dict[str, float] = {t: 0.0 for t in teams}
        counts: Dict[str, int] = {t: 0 for t in teams}

        # Running cumulative xG per team, sampled onto the minute grid. A shot
        # counts toward minute m once the grid passes m.
        running: Dict[str, float] = {t: 0.0 for t in teams}
        shot_idx = 0
        for grid_minute in minutes:
            while shot_idx < len(shots) and shots[shot_idx]["minute"] <= grid_minute:
                s = shots[shot_idx]
                running[s["team"]] += s["xg"]
                counts[s["team"]] += 1
                shot_idx += 1
            for t in teams:
                cumulative[t].append(round(running[t], 4))

        for t in teams:
            totals[t] = round(running[t], 4)

        summary = self._summarize(teams, totals, counts, last_minute, inputs)

        data: Dict[str, Any] = {
            "teams": teams,
            "minutes": minutes,
            "cumulative_xg": cumulative,
            "total_xg": totals,
            "shot_count": counts,
            "include_shootout": inputs.include_shootout,
            "bin_minutes": inputs.bin_minutes,
            "shots": shots,
        }
        return ToolResult(
            tool=self.name,
            inputs=inputs.model_dump(),
            summary=summary,
            data=data,
        )

    @staticmethod
    def _collect_shots(match: Match, include_shootout: bool) -> List[Dict[str, Any]]:
        """Extract the shot events we care about, sorted chronologically."""
        shots: List[Dict[str, Any]] = []
        for e in match.events:
            if e.get("type", {}).get("name") != "Shot":
                continue
            if not include_shootout and e.get("period") == _SHOOTOUT_PERIOD:
                continue
            shot = e.get("shot", {})
            xg = shot.get("statsbomb_xg")
            if xg is None:
                continue
            shots.append(
                {
                    "minute": e.get("minute", 0),
                    "second": e.get("second", 0),
                    "period": e.get("period"),
                    "team": e.get("team", {}).get("name", "?"),
                    "player": e.get("player", {}).get("name"),
                    "xg": float(xg),
                    "outcome": shot.get("outcome", {}).get("name"),
                    "is_goal": shot.get("outcome", {}).get("name") == "Goal",
                }
            )
        # Chronological order: absolute minute then second.
        shots.sort(key=lambda s: (s["minute"], s["second"]))
        return shots

    @staticmethod
    def _summarize(
        teams: List[str],
        totals: Dict[str, float],
        counts: Dict[str, int],
        last_minute: int,
        inputs: XGTimelineInput,
    ) -> str:
        parts = [
            f"{t} {totals[t]:.2f} xG ({counts[t]} shots)" for t in teams
        ]
        note = "" if inputs.include_shootout else ", shootout excluded"
        return (
            "Cumulative xG through minute "
            f"{last_minute}: " + " vs ".join(parts) + note + "."
        )


# Register on the default REGISTRY at import time.
register(XGTimelineTool())
