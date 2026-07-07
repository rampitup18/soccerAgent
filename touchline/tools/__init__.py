"""Touchline's analysis toolkit.

Every analysis Touchline can run is a :class:`~touchline.tools.base.Tool`:
a name, a description, a pydantic input schema, and a ``run`` method that
returns a :class:`~touchline.tools.base.ToolResult`. Tools register into a
:class:`~touchline.tools.base.ToolRegistry`, which is the agent's action
space -- the loop selects a tool by description and never needs to know
which specific analysis it is invoking.

Importing this package registers the built-in tools on the default
``REGISTRY``.
"""

from touchline.tools.base import Tool, ToolResult, ToolRegistry, REGISTRY

# Importing the modules registers their tools on the default REGISTRY.
from touchline.tools import xg_timeline  # noqa: F401

__all__ = ["Tool", "ToolResult", "ToolRegistry", "REGISTRY"]
