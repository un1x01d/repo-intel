from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ParsedSymbol:
    name: str
    kind: str
    line_start: int
    line_end: int | None
    exported: bool


_DECLARATION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("function", re.compile(r"^\s*(export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(")),
    ("class", re.compile(r"^\s*(export\s+)?class\s+([A-Za-z_$][\w$]*)\b")),
    ("interface", re.compile(r"^\s*(export\s+)?interface\s+([A-Za-z_$][\w$]*)\b")),
    ("type", re.compile(r"^\s*(export\s+)?type\s+([A-Za-z_$][\w$]*)\b")),
    ("enum", re.compile(r"^\s*(export\s+)?enum\s+([A-Za-z_$][\w$]*)\b")),
    ("const", re.compile(r"^\s*(export\s+)?const\s+([A-Za-z_$][\w$]*)\s*=")),
]


def parse_symbols(source: str) -> list[ParsedSymbol]:
    symbols: list[ParsedSymbol] = []
    for line_number, line in enumerate(source.splitlines(), start=1):
        for kind, pattern in _DECLARATION_PATTERNS:
            match = pattern.search(line)
            if match:
                symbols.append(
                    ParsedSymbol(
                        name=match.group(2),
                        kind=kind,
                        line_start=line_number,
                        line_end=_line_end(source, line_number),
                        exported=bool(match.group(1)),
                    )
                )
                break
    return symbols


def _line_end(source: str, line_start: int) -> int | None:
    lines = source.splitlines()
    balance = 0
    seen_block = False
    for index in range(line_start - 1, len(lines)):
        line = lines[index]
        balance += line.count("{") - line.count("}")
        seen_block = seen_block or "{" in line
        if seen_block and balance <= 0:
            return index + 1
        if not seen_block and line.rstrip().endswith(";"):
            return index + 1
    return None
