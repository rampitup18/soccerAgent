"""xG timeline: cumulative expected goals per team over the course of a match.

Expected goals (xG) estimates the probability a given shot becomes a goal.
Summed over a match it measures the *quality* of chances a team created,
independent of whether they were finished. Plotted cumulatively over time it
reads as a momentum curve: steep steps are big chances, long flat stretches
are spells without threat, and the gap between the two curves is the story of
who was on top and when.

StatsBomb ship an xG value on every shot event (``shot.statsbomb_xg``), so the
timeline computes directly from the shot stream with no modelling of our own.

**The penalty shootout is not part of this curve.** A shootout is a separate
contest -- its momentum is a new game, not a continuation of the run of play --
so folding it into the same cumulative line would imply a continuity that does
not exist. It is also meaningless in xG terms: StatsBomb assign a flat ~0.78 to
every shootout penalty regardless of who took it or what happened, so a
shootout "xG" only measures how many kicks were taken. The timeline therefore
covers run-of-play (and in-game penalties) only, and the shootout is reported
*separately*, on its own terms: the running score, which is the momentum that
actually matters once it starts.

This is Touchline's first tool: a whole-match narrative metric that is trivial
to verify by hand (each team's final cumulative value is just the sum of its
run-of-play shot xGs).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from touchline.data import Match
from touchline.tools.base import Tool, ToolResult, register

# StatsBomb records the penalty shootout as period 5. It is a separate contest,
# never part of the run-of-play xG timeline.
_SHOOTOUT_PERIOD = 5


class XGTimelineInput(BaseModel):
    """Inputs for the xG timeline."""

    bin_minutes: int = Field(
        default=1,
        ge=1,
        description="Granularity of the timeline grid, in minutes. 1 gives a "
        "per-minute series.",
    )


class XGTimelineTool(Tool):
    name = "xg_timeline"
    description = (
        "Compute each team's cumulative expected goals (xG) over the course of "
        "the match as a per-minute series, covering run of play and in-game "
        "penalties (the penalty shootout is excluded and reported separately). "
        "Use this to see momentum swings, identify which team created the "
        "better chances and when, and quantify how the balance of play shifted "
        "across phases. Returns both teams' cumulative xG curves, per-team "
        "totals and shot counts, the individual shots (minute, player, xG, "
        "whether it was a goal), and -- if the match went to penalties -- a "
        "separate shootout summary with its own running score."
    )
    Input = XGTimelineInput

    def _run(self, match: Match, inputs: XGTimelineInput) -> ToolResult:  # type: ignore[override]
        shots = self._collect_shots(match)

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

        # The shootout, if any, is its own separate contest.
        shootout = self._collect_shootout(match)

        summary = self._summarize(teams, totals, counts, last_minute, shootout)

        data: Dict[str, Any] = {
            "teams": teams,
            "minutes": minutes,
            "cumulative_xg": cumulative,
            "total_xg": totals,
            "shot_count": counts,
            "bin_minutes": inputs.bin_minutes,
            "shots": shots,
            # Kept deliberately separate from the run-of-play timeline above.
            "shootout": shootout,
        }
        return ToolResult(
            tool=self.name,
            inputs=inputs.model_dump(),
            summary=summary,
            data=data,
        )

    @staticmethod
    def _collect_shots(match: Match) -> List[Dict[str, Any]]:
        """Extract the run-of-play shot events, sorted chronologically.

        Excludes the penalty shootout (period 5); in-game penalties are kept,
        as they are genuine run-of-play chances.
        """
        shots: List[Dict[str, Any]] = []
        for e in match.events:
            if e.get("type", {}).get("name") != "Shot":
                continue
            if e.get("period") == _SHOOTOUT_PERIOD:
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
    def _collect_shootout(match: Match) -> Optional[Dict[str, Any]]:
        """Summarize the penalty shootout as its own contest, or ``None``.

        A shootout's momentum is the running score, not xG: every kick carries
        the same flat placeholder xG, so a cumulative-xG view of it is
        meaningless. We report the ordered kicks with a running goal tally,
        the final score, and the winner -- a self-contained "new game".
        """
        kicks_raw = [
            e
            for e in match.events
            if e.get("type", {}).get("name") == "Shot"
            and e.get("period") == _SHOOTOUT_PERIOD
        ]
        if not kicks_raw:
            return None

        kicks_raw.sort(key=lambda e: (e.get("minute", 0), e.get("second", 0), e.get("index", 0)))

        # Kicking order = order teams first appear in the sequence.
        order: List[str] = []
        for e in kicks_raw:
            name = e.get("team", {}).get("name", "?")
            if name not in order:
                order.append(name)

        score: Dict[str, int] = {t: 0 for t in order}
        kicks: List[Dict[str, Any]] = []
        for i, e in enumerate(kicks_raw, start=1):
            team = e.get("team", {}).get("name", "?")
            outcome = e.get("shot", {}).get("outcome", {}).get("name")
            scored = outcome == "Goal"
            if scored:
                score[team] += 1
            kicks.append(
                {
                    "index": i,
                    "team": team,
                    "player": e.get("player", {}).get("name"),
                    "outcome": outcome,
                    "scored": scored,
                    # Running score after this kick -- the shootout's own momentum.
                    "score": dict(score),
                }
            )

        # A shootout does not end level; guard anyway.
        winner: Optional[str] = None
        best = max(score.values())
        leaders = [t for t, v in score.items() if v == best]
        if len(leaders) == 1:
            winner = leaders[0]

        return {
            "present": True,
            "order": order,
            "kicks": kicks,
            "score": score,
            "winner": winner,
            "note": (
                "Penalty shootout: a separate contest, excluded from the "
                "run-of-play xG timeline. Its momentum is the running score, "
                "not xG (shootout xG is a flat placeholder)."
            ),
        }

    @staticmethod
    def _summarize(
        teams: List[str],
        totals: Dict[str, float],
        counts: Dict[str, int],
        last_minute: int,
        shootout: Optional[Dict[str, Any]],
    ) -> str:
        parts = [f"{t} {totals[t]:.2f} xG ({counts[t]} shots)" for t in teams]
        line = (
            "Cumulative run-of-play xG through minute "
            f"{last_minute}: " + " vs ".join(parts) + "."
        )
        if shootout is not None:
            score = shootout["score"]
            score_str = "-".join(str(score[t]) for t in shootout["order"])
            winner = shootout["winner"]
            tag = f", {winner} won" if winner else ""
            line += (
                " Shootout (separate): "
                + " ".join(f"{t} {score[t]}" for t in shootout["order"])
                + f" ({score_str}{tag})."
            )
        return line


# Register on the default REGISTRY at import time.
register(XGTimelineTool())
