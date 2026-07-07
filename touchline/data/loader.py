"""StatsBomb open-data loader with a local, offline-first cache.

StatsBomb publish event-level data for a set of competitions (including the
men's and women's World Cups) as plain JSON in a public GitHub repository.
This module fetches the pieces Touchline needs -- a match's ``events`` and
``lineups`` -- and caches them on disk. After the first fetch every load is
served from cache, so investigation runs are fast and work with no network.

The loader deliberately depends only on the Python standard library. The
data plumbing should never be the reason a run fails to start.

Layout on disk (under ``cache_dir``)::

    competitions.json
    matches/<competition_id>/<season_id>.json
    events/<match_id>.json
    lineups/<match_id>.json

The paths mirror the StatsBomb ``open-data/data`` tree so the cache is easy
to reason about and safe to delete at any time.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("touchline.data")

# Base URL for the raw JSON files in the StatsBomb open-data repository.
OPEN_DATA_BASE = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"

# Well-known identifiers so callers don't have to look them up.
# FIFA World Cup 2022 (men's) in the open dataset.
WORLD_CUP_2022: Dict[str, int] = {"competition_id": 43, "season_id": 106}

# Argentina 3-3 France (Argentina won on penalties) -- the 2022 WC Final.
WC_2022_FINAL: int = 3869685


@dataclass
class Match:
    """A loaded match: its raw event stream and both starting lineups.

    Attributes are the parsed JSON exactly as StatsBomb publish it. Higher
    layers (metrics, tools) build structured views on top of these; the
    loader's only job is to make sure they are present and cached.
    """

    match_id: int
    events: List[Dict[str, Any]]
    lineups: List[Dict[str, Any]]

    @property
    def teams(self) -> List[str]:
        """Team names appearing in the lineups, in listed order."""
        return [team.get("team_name", "?") for team in self.lineups]

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        teams = " vs ".join(self.teams) if self.lineups else "?"
        return (
            f"Match(match_id={self.match_id}, teams='{teams}', "
            f"events={len(self.events)})"
        )


class StatsBombLoader:
    """Fetch-and-cache access to StatsBomb open data.

    Parameters
    ----------
    cache_dir:
        Directory the JSON cache lives in. Created on first write.
    base_url:
        Root of the open-data tree. Overridable for tests or mirrors.
    timeout:
        Per-request network timeout in seconds.
    retries:
        Number of network attempts before giving up on a fetch.
    """

    def __init__(
        self,
        cache_dir: str = "data_cache",
        base_url: str = OPEN_DATA_BASE,
        timeout: float = 30.0,
        retries: int = 3,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = max(1, retries)

    # -- public API ------------------------------------------------------

    def competitions(self, refresh: bool = False) -> List[Dict[str, Any]]:
        """All competitions/seasons available in the open dataset."""
        return self._get("competitions.json", "competitions.json", refresh)

    def matches(
        self, competition_id: int, season_id: int, refresh: bool = False
    ) -> List[Dict[str, Any]]:
        """Match metadata for one competition-season."""
        rel = f"matches/{competition_id}/{season_id}.json"
        return self._get(rel, rel, refresh)

    def events(self, match_id: int, refresh: bool = False) -> List[Dict[str, Any]]:
        """The full event stream for a match."""
        rel = f"events/{match_id}.json"
        return self._get(rel, rel, refresh)

    def lineups(self, match_id: int, refresh: bool = False) -> List[Dict[str, Any]]:
        """Both teams' lineups (players, positions, shirt numbers) for a match."""
        rel = f"lineups/{match_id}.json"
        return self._get(rel, rel, refresh)

    def load_match(self, match_id: int, refresh: bool = False) -> Match:
        """Load a match's events and lineups as a single :class:`Match`.

        This is the primary entry point for the rest of Touchline. The first
        call for a given match hits the network; every call after that is
        served from the on-disk cache.
        """
        logger.info("Loading match %s", match_id)
        events = self.events(match_id, refresh=refresh)
        lineups = self.lineups(match_id, refresh=refresh)
        match = Match(match_id=match_id, events=events, lineups=lineups)
        logger.info(
            "Loaded %s: %d events across %s",
            match_id,
            len(events),
            " vs ".join(match.teams) or "unknown teams",
        )
        return match

    def find_match(
        self,
        competition_id: int,
        season_id: int,
        home_team: Optional[str] = None,
        away_team: Optional[str] = None,
        stage: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Find one match's metadata by team names and/or stage.

        Team names are matched case-insensitively and order-independently, so
        ``home_team="argentina", away_team="france"`` finds the fixture
        regardless of which side StatsBomb records as home.
        """
        wanted = {t.lower() for t in (home_team, away_team) if t}
        for m in self.matches(competition_id, season_id):
            sides = {
                m["home_team"]["home_team_name"].lower(),
                m["away_team"]["away_team_name"].lower(),
            }
            if wanted and not wanted.issubset(sides):
                continue
            if stage and m.get("competition_stage", {}).get("name", "").lower() != stage.lower():
                continue
            return m
        return None

    def is_cached(self, rel_path: str) -> bool:
        """Whether a given open-data path is already on disk."""
        return (self.cache_dir / rel_path).exists()

    # -- internals -------------------------------------------------------

    def _get(self, rel_path: str, cache_key: str, refresh: bool = False) -> Any:
        """Return parsed JSON for ``rel_path``, using the cache when possible."""
        cache_path = self.cache_dir / cache_key
        if cache_path.exists() and not refresh:
            logger.debug("cache hit: %s", cache_key)
            return self._read_cache(cache_path)

        logger.info("fetching %s", rel_path)
        payload = self._fetch(f"{self.base_url}/{rel_path}")
        self._write_cache(cache_path, payload)
        return json.loads(payload)

    def _fetch(self, url: str) -> bytes:
        """Download a URL with a small retry/backoff loop."""
        last_err: Optional[Exception] = None
        for attempt in range(1, self.retries + 1):
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": "touchline/0.1 (statsbomb-loader)"}
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return resp.read()
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as err:
                last_err = err
                if isinstance(err, urllib.error.HTTPError) and err.code == 404:
                    # A 404 is a real answer, not a transient failure.
                    raise FileNotFoundError(f"not found in open data: {url}") from err
                logger.warning("fetch attempt %d/%d failed: %s", attempt, self.retries, err)
                if attempt < self.retries:
                    time.sleep(0.5 * attempt)
        raise RuntimeError(f"failed to fetch {url}: {last_err}")

    @staticmethod
    def _read_cache(path: Path) -> Any:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    @staticmethod
    def _write_cache(path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write atomically so an interrupted fetch can't leave a half file
        # that later reads as a cache hit.
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(payload)
        tmp.replace(path)
