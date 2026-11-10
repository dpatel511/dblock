"""Tool-version compatibility: does the installed tool accept this database release?"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass

_OPS = {
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
}


class SpecError(Exception):
    pass


def parse_version(text: str) -> tuple[int, ...]:
    match = re.fullmatch(r"\s*v?(\d+(?:\.\d+)*)\s*", text)
    if not match:
        raise SpecError(f"not a numeric version: '{text}'")
    parts = [int(p) for p in match.group(1).split(".")]
    while len(parts) > 1 and parts[-1] == 0:  # 2.7 == 2.7.0
        parts.pop()
    return tuple(parts)


def satisfies(version: str, spec: str) -> bool:
    """satisfies('2.5.0', '>=2.4.1,<=2.6.1') -> True. An empty spec accepts anything."""
    v = parse_version(version)
    for clause in filter(None, (c.strip() for c in spec.split(","))):
        match = re.fullmatch(r"(>=|<=|==|!=|>|<)\s*(.+)", clause)
        if not match:
            raise SpecError(f"bad version clause '{clause}' in '{spec}'")
        op, bound = match.groups()
        if not _OPS[op](v, parse_version(bound)):
            return False
    return True


@dataclass
class CompatResult:
    status: str  # "ok", "incompatible", "tool-not-found", "unknown-version", "no-rule"
    tool_version: str = ""
    detail: str = ""


def check(command: tuple[str, ...], regex: str, spec: str) -> CompatResult:
    if not spec:
        return CompatResult("no-rule", detail="recipe states no tool-version rule")
    if not command:
        return CompatResult("no-rule", detail="recipe has no version command")
    if shutil.which(command[0]) is None:
        return CompatResult("tool-not-found", detail=f"'{command[0]}' is not on PATH")
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CompatResult("unknown-version", detail=str(exc))
    match = re.search(regex, proc.stdout + "\n" + proc.stderr)
    if not match:
        return CompatResult("unknown-version", detail=f"no version found in output of {' '.join(command)}")
    version = match.group(1)
    ok = satisfies(version, spec)
    return CompatResult("ok" if ok else "incompatible", version, f"needs {spec}")
