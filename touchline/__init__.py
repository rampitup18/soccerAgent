"""Touchline: an autonomous match-analyst agent.

Touchline investigates a finished soccer match and produces a grounded
tactical report by forming and testing hypotheses against event data.

This package is built up commit by commit. The first layer is the data
plumbing (:mod:`touchline.data`), which pulls a match's events and lineups
from StatsBomb open data and caches them locally so every later run is fast
and fully offline.
"""

__version__ = "0.1.0"
