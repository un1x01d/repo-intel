from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ParsedRoute:
    framework: str
    method: str
    path: str
    handler_name: str | None
    line_start: int


_ROUTE_RE = re.compile(
    r"""\b(?P<object>app|router|fastify)\.(?P<method>get|post|put|patch|delete)\(\s*["'](?P<path>[^"']+)["']\s*,\s*(?P<handler>[^,)]+)?""",
    re.IGNORECASE,
)


def parse_routes(source: str) -> list[ParsedRoute]:
    routes: list[ParsedRoute] = []
    for line_number, line in enumerate(source.splitlines(), start=1):
        for match in _ROUTE_RE.finditer(line):
            framework = "fastify" if match.group("object").lower() == "fastify" else "express"
            routes.append(
                ParsedRoute(
                    framework=framework,
                    method=match.group("method").upper(),
                    path=match.group("path"),
                    handler_name=_clean_handler(match.group("handler")),
                    line_start=line_number,
                )
            )
    return routes


def _clean_handler(handler: str | None) -> str | None:
    if handler is None:
        return None
    value = handler.strip()
    if value.startswith(("async ", "function", "(", "{")):
        return None
    return value or None
