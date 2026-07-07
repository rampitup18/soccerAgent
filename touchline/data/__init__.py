"""Data access layer for Touchline.

Exposes the StatsBomb open-data loader and a few well-known identifiers so
callers can grab a match without memorizing competition/season ids.
"""

from touchline.data.loader import (
    StatsBombLoader,
    Match,
    OPEN_DATA_BASE,
    WORLD_CUP_2022,
    WC_2022_FINAL,
)

__all__ = [
    "StatsBombLoader",
    "Match",
    "OPEN_DATA_BASE",
    "WORLD_CUP_2022",
    "WC_2022_FINAL",
]
