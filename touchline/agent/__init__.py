"""The agent side of Touchline: the machinery that drives the investigation.

This package holds the pieces that sit between a model's decisions and the
analysis toolkit. The first of them is the :class:`~touchline.agent.executor.ToolExecutor`,
which runs a named tool with validated arguments and always returns a
structured result -- a clean success or an informative error, never a crash.
The investigation loop (a later commit) is built on top of it.
"""

from touchline.agent.executor import (
    ToolExecutor,
    ExecutionResult,
    ExecutionError,
    ErrorKind,
)

__all__ = [
    "ToolExecutor",
    "ExecutionResult",
    "ExecutionError",
    "ErrorKind",
]
