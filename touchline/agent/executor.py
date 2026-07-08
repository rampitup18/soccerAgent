"""Run a named tool with validated arguments, and never crash doing it.

The executor is the single choke point through which every tool call passes.
It centralizes the cross-cutting concerns the investigation loop would
otherwise have to repeat for each tool:

* **lookup** -- resolve a tool name against the registry;
* **validation** -- coerce/check arguments against the tool's pydantic schema;
* **execution** -- run the tool against a match;
* **error handling** -- turn any failure into a structured, readable result;
* **logging + timing** -- record what ran and how long it took.

Crucially it returns errors as *data*, not exceptions. When a stochastic model
is choosing tool names and arguments it will sometimes get them wrong; an
:class:`ExecutionResult` carrying an informative :class:`ExecutionError` is
feedback the model can read and recover from on the next turn. A traceback is
not.

The executor is deliberately in-process. The agent only ever *selects* a tool
and its arguments -- it never executes arbitrary generated code -- so there is
nothing to sandbox. Subprocess isolation would be cost without benefit.
"""

from __future__ import annotations

import logging
import time
import traceback
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import ValidationError

from touchline.data import Match
from touchline.tools.base import ToolRegistry, ToolResult

logger = logging.getLogger("touchline.agent.executor")


class ErrorKind(str, Enum):
    """The categories of failure the executor distinguishes.

    The kind tells the agent *how* to recover: pick a different tool, fix the
    arguments, or treat the analysis as unavailable.
    """

    UNKNOWN_TOOL = "unknown_tool"
    INVALID_ARGUMENTS = "invalid_arguments"
    NO_MATCH = "no_match"
    EXECUTION_ERROR = "execution_error"


@dataclass
class ExecutionError:
    """A structured, model-readable description of why a call failed."""

    kind: ErrorKind
    message: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind.value,
            "message": self.message,
            "details": self.details,
        }


@dataclass
class ExecutionResult:
    """The outcome of one tool call: either a result or an error, never both.

    This is what the investigation loop feeds back to the model. It is always
    well-formed regardless of what happened inside the tool.
    """

    ok: bool
    tool: str
    arguments: Dict[str, Any]
    result: Optional[ToolResult] = None
    error: Optional[ExecutionError] = None
    duration_ms: float = 0.0

    @property
    def summary(self) -> str:
        """A one-line synopsis, whether the call succeeded or failed."""
        if self.ok and self.result is not None:
            return self.result.summary
        if self.error is not None:
            return f"[{self.error.kind.value}] {self.error.message}"
        return "empty result"

    def to_dict(self) -> Dict[str, Any]:
        """JSON-serializable form suitable for feeding back to the model."""
        payload: Dict[str, Any] = {
            "ok": self.ok,
            "tool": self.tool,
            "arguments": self.arguments,
            "duration_ms": round(self.duration_ms, 2),
        }
        if self.ok and self.result is not None:
            payload["result"] = self.result.to_dict()
        if self.error is not None:
            payload["error"] = self.error.to_dict()
        return payload


class ToolExecutor:
    """Runs tools from a registry, returning structured results.

    Parameters
    ----------
    registry:
        The pool of tools this executor can run.
    match:
        A default match to run tools against. May be omitted here and supplied
        per call instead.
    """

    def __init__(self, registry: ToolRegistry, match: Optional[Match] = None) -> None:
        self.registry = registry
        self.match = match

    def execute(
        self,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
        match: Optional[Match] = None,
    ) -> ExecutionResult:
        """Run ``tool_name`` with ``arguments`` and return a structured result.

        Never raises for an ordinary bad call: an unknown tool, malformed
        arguments, a missing match, or an exception inside the tool all come
        back as an :class:`ExecutionResult` with ``ok=False`` and a populated
        :class:`ExecutionError`.
        """
        arguments = dict(arguments or {})
        start = time.perf_counter()

        def fail(kind: ErrorKind, message: str, **details: Any) -> ExecutionResult:
            logger.info("tool %r failed: %s (%s)", tool_name, message, kind.value)
            return ExecutionResult(
                ok=False,
                tool=tool_name,
                arguments=arguments,
                error=ExecutionError(kind=kind, message=message, details=details),
                duration_ms=(time.perf_counter() - start) * 1000,
            )

        # 1. Arguments must be a mapping of names to values.
        if not isinstance(arguments, dict):
            return fail(
                ErrorKind.INVALID_ARGUMENTS,
                f"arguments must be an object, got {type(arguments).__name__}",
            )

        # 2. Resolve the tool.
        try:
            tool = self.registry.get(tool_name)
        except KeyError:
            return fail(
                ErrorKind.UNKNOWN_TOOL,
                f"no tool named {tool_name!r}",
                known_tools=self.registry.names(),
            )

        # 3. There must be a match to run against.
        run_match = match if match is not None else self.match
        if run_match is None:
            return fail(
                ErrorKind.NO_MATCH,
                "no match bound to the executor or provided to execute()",
            )

        # 4. Validate arguments against the tool's schema.
        try:
            validated = tool.Input(**arguments)
        except ValidationError as err:
            return fail(
                ErrorKind.INVALID_ARGUMENTS,
                f"invalid arguments for {tool_name!r}: "
                + "; ".join(_format_validation_errors(err)),
                errors=_validation_error_details(err),
                schema=tool.input_schema(),
            )
        except TypeError as err:
            # e.g. arguments contains a non-keyword-compatible structure.
            return fail(
                ErrorKind.INVALID_ARGUMENTS,
                f"could not bind arguments for {tool_name!r}: {err}",
                schema=tool.input_schema(),
            )

        # 5. Run the tool. Any failure inside the analysis is caught and
        #    reported rather than propagated.
        try:
            result = tool._run(run_match, validated)
        except Exception as err:  # noqa: BLE001 - deliberately catch-all
            logger.exception("tool %r raised during execution", tool_name)
            return fail(
                ErrorKind.EXECUTION_ERROR,
                f"{type(err).__name__}: {err}",
                exception_type=type(err).__name__,
                traceback=traceback.format_exc(limit=5),
            )

        duration_ms = (time.perf_counter() - start) * 1000
        logger.info("tool %r ok in %.1f ms: %s", tool_name, duration_ms, result.summary)
        return ExecutionResult(
            ok=True,
            tool=tool_name,
            arguments=validated.model_dump(),
            result=result,
            duration_ms=duration_ms,
        )


def _format_validation_errors(err: ValidationError) -> list[str]:
    """Compact, human-readable one-liners for each validation problem."""
    out = []
    for e in err.errors():
        loc = ".".join(str(p) for p in e.get("loc", ())) or "(root)"
        out.append(f"{loc}: {e.get('msg', 'invalid')}")
    return out


def _validation_error_details(err: ValidationError) -> list[Dict[str, Any]]:
    """Structured per-field validation detail the model can act on."""
    details = []
    for e in err.errors():
        details.append(
            {
                "field": ".".join(str(p) for p in e.get("loc", ())),
                "message": e.get("msg"),
                "type": e.get("type"),
            }
        )
    return details
