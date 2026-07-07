"""The uniform tool contract and its registry.

A :class:`Tool` bundles four things:

* ``name`` -- a stable identifier the agent uses to select it.
* ``description`` -- what it computes and when to reach for it. This is the
  text the model reads to decide the *next* query, so it should read like a
  hint to an analyst, not an implementation note.
* ``Input`` -- a pydantic model that both validates arguments and produces
  the JSON schema exposed to the model for function calling.
* ``run`` -- executes the analysis against a :class:`~touchline.data.Match`
  and returns a :class:`ToolResult`.

Because every analysis satisfies the same contract, the investigation loop
stays fixed as the toolkit grows: adding a metric is adding a ``Tool``, not
editing the loop.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Type

from pydantic import BaseModel

from touchline.data import Match


@dataclass
class ToolResult:
    """The structured output of one tool run.

    Every claim in a Touchline report must trace back to one of these, so a
    result carries both a short ``summary`` (for the agent to read and for
    the report to quote) and the full structured ``data`` behind it (so the
    claim can be audited against the numbers).

    Attributes
    ----------
    tool:
        Name of the tool that produced the result.
    inputs:
        The validated inputs the tool ran with.
    summary:
        A one-line, human-readable synopsis of the finding.
    data:
        The full structured payload backing the summary.
    """

    tool: str
    inputs: Dict[str, Any]
    summary: str
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool": self.tool,
            "inputs": self.inputs,
            "summary": self.summary,
            "data": self.data,
        }


class Tool(ABC):
    """Base class for every Touchline analysis.

    Subclasses set ``name``, ``description``, and an ``Input`` pydantic model,
    then implement :meth:`_run`. The public :meth:`run` validates raw keyword
    arguments through ``Input`` before dispatching, so a tool body always
    receives well-formed, typed inputs.
    """

    #: Stable identifier used to select the tool.
    name: str = ""
    #: Analyst-facing description of what the tool computes and when to use it.
    description: str = ""
    #: pydantic model describing (and validating) the tool's arguments.
    Input: Type[BaseModel] = BaseModel

    def input_schema(self) -> Dict[str, Any]:
        """JSON schema for this tool's inputs."""
        return self.Input.model_json_schema()

    def spec(self) -> Dict[str, Any]:
        """Function-calling spec: what gets handed to the model.

        Matches the Anthropic tool format (``name``/``description``/
        ``input_schema``), which is what the default Claude backbone expects.
        """
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema(),
        }

    def run(self, match: Match, **inputs: Any) -> ToolResult:
        """Validate ``inputs`` and execute the analysis on ``match``."""
        validated = self.Input(**inputs)
        return self._run(match, validated)

    @abstractmethod
    def _run(self, match: Match, inputs: BaseModel) -> ToolResult:
        """Execute the analysis. ``inputs`` is a validated ``Input`` instance."""
        raise NotImplementedError

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"<Tool {self.name!r}>"


class ToolRegistry:
    """An introspectable collection of tools -- the agent's action space.

    The loop asks the registry for :meth:`specs` to tell the model what it
    can do, then looks up the chosen tool by name with :meth:`get`. Nothing
    about a specific analysis leaks into the loop.
    """

    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        """Add a tool. Raises on a missing or duplicate name."""
        if not tool.name:
            raise ValueError(f"tool {tool!r} has no name")
        if tool.name in self._tools:
            raise ValueError(f"tool {tool.name!r} is already registered")
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"unknown tool {name!r}; known: {sorted(self._tools)}")
        return self._tools[name]

    def names(self) -> List[str]:
        return sorted(self._tools)

    def specs(self) -> List[Dict[str, Any]]:
        """Function-calling specs for every registered tool."""
        return [self._tools[name].spec() for name in self.names()]

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def __iter__(self) -> Iterator[Tool]:
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)


#: The default registry the built-in tools attach to.
REGISTRY = ToolRegistry()


def register(tool: Tool) -> Tool:
    """Register ``tool`` on the default :data:`REGISTRY` and return it."""
    return REGISTRY.register(tool)
