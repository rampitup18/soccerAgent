#!/usr/bin/env python3
"""Verify the executor turns every kind of bad call into feedback, not a crash.

Exercises, on the 2022 World Cup Final:

* a valid call -> ok result;
* an unknown tool name -> UNKNOWN_TOOL error listing the known tools;
* invalid arguments (schema violation and wrong type) -> INVALID_ARGUMENTS
  with per-field detail;
* a missing match -> NO_MATCH;
* a tool that raises internally -> EXECUTION_ERROR with the exception detail.

The whole point: none of these raise out of ``execute`` -- each returns a
well-formed ExecutionResult.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic import BaseModel  # noqa: E402

from touchline.agent import ToolExecutor, ErrorKind  # noqa: E402
from touchline.data import StatsBombLoader, WC_2022_FINAL  # noqa: E402
from touchline.tools import REGISTRY  # noqa: E402
from touchline.tools.base import Tool, ToolRegistry, ToolResult  # noqa: E402


class _BoomInput(BaseModel):
    pass


class _BoomTool(Tool):
    name = "boom"
    description = "A tool that always raises, to test execution-error handling."
    Input = _BoomInput

    def _run(self, match, inputs):  # type: ignore[override]
        raise RuntimeError("intentional explosion")


def main() -> int:
    loader = StatsBombLoader(cache_dir="data_cache")
    match = loader.load_match(WC_2022_FINAL)

    # A registry that includes the real tools plus the exploding one.
    registry = ToolRegistry()
    for tool in REGISTRY:
        registry.register(tool)
    registry.register(_BoomTool())

    executor = ToolExecutor(registry, match=match)
    checks: list[tuple[bool, str]] = []

    def check(cond: bool, label: str) -> None:
        checks.append((bool(cond), label))

    # 1. Valid call succeeds.
    r = executor.execute("xg_timeline", {"bin_minutes": 5})
    check(r.ok and r.result is not None, "valid call returns ok result")
    check(r.error is None, "valid call has no error")
    check(r.duration_ms >= 0, "valid call is timed")

    # 2. Unknown tool.
    r = executor.execute("not_a_tool", {})
    check(not r.ok and r.error.kind is ErrorKind.UNKNOWN_TOOL, "unknown tool -> UNKNOWN_TOOL")
    check("xg_timeline" in r.error.details.get("known_tools", []), "unknown tool lists known tools")

    # 3a. Invalid arguments: schema violation (bin_minutes must be >= 1).
    r = executor.execute("xg_timeline", {"bin_minutes": 0})
    check(not r.ok and r.error.kind is ErrorKind.INVALID_ARGUMENTS, "ge violation -> INVALID_ARGUMENTS")
    check(bool(r.error.details.get("errors")), "validation error carries per-field detail")

    # 3b. Invalid arguments: wrong type.
    r = executor.execute("xg_timeline", {"bin_minutes": "lots"})
    check(not r.ok and r.error.kind is ErrorKind.INVALID_ARGUMENTS, "wrong type -> INVALID_ARGUMENTS")

    # 4. Missing match.
    r = executor.execute("xg_timeline", {}, match=None)  # falls back to bound match
    check(r.ok, "omitted match falls back to bound match")
    unbound = ToolExecutor(registry)  # no bound match at all
    r = unbound.execute("xg_timeline", {})
    check(not r.ok and r.error.kind is ErrorKind.NO_MATCH, "no match anywhere -> NO_MATCH")

    # 5. Tool raises internally.
    r = executor.execute("boom", {})
    check(not r.ok and r.error.kind is ErrorKind.EXECUTION_ERROR, "internal raise -> EXECUTION_ERROR")
    check("intentional explosion" in r.error.message, "execution error surfaces the message")
    check(r.error.details.get("exception_type") == "RuntimeError", "execution error records exception type")

    # 6. Every result is JSON-serializable.
    import json
    for name, args in [("xg_timeline", {}), ("nope", {}), ("boom", {})]:
        out = executor.execute(name, args)
        json.dumps(out.to_dict())  # raises if not serializable
    check(True, "every ExecutionResult is JSON-serializable")

    # --- report ---
    print(f"\n{match}\n")
    width = max(len(label) for _, label in checks)
    for ok, label in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label:<{width}}")

    failed = [label for ok, label in checks if not ok]
    print(f"\n{len(checks) - len(failed)}/{len(checks)} checks passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
