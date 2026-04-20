from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ParsedIntegration:
    integration_type: str
    provider: str
    symbol_name: str | None
    evidence_text: str
    line_start: int


_PROVIDERS: dict[str, tuple[str, str]] = {
    "axios": ("http_api", "axios"),
    "node-fetch": ("http_api", "node-fetch"),
    "got": ("http_api", "got"),
    "superagent": ("http_api", "superagent"),
    "pg": ("database", "postgresql"),
    "mysql": ("database", "mysql"),
    "mysql2": ("database", "mysql"),
    "mongoose": ("database", "mongodb"),
    "mongodb": ("database", "mongodb"),
    "@prisma/client": ("database", "prisma"),
    "sequelize": ("database", "sequelize"),
    "redis": ("cache", "redis"),
    "ioredis": ("cache", "redis"),
    "amqplib": ("queue", "rabbitmq"),
    "bull": ("queue", "bull"),
    "bullmq": ("queue", "bullmq"),
    "kafkajs": ("queue", "kafka"),
    "@google-cloud/pubsub": ("queue", "pubsub"),
    "@google-cloud/storage": ("storage", "gcs"),
    "aws-sdk": ("storage", "aws-sdk"),
    "@aws-sdk/client-s3": ("storage", "s3"),
    "jsonwebtoken": ("auth", "jsonwebtoken"),
    "passport": ("auth", "passport"),
    "firebase-admin": ("auth", "firebase-admin"),
    "auth0": ("auth", "auth0"),
    "express-oauth2-jwt-bearer": ("auth", "auth0"),
}

_IMPORT_RE = re.compile(r"""^\s*import\s+(?P<symbol>[\w${}\s,*]+?)?\s*(?:from\s+)?["'](?P<module>[^"']+)["']""")
_REQUIRE_RE = re.compile(r"""^\s*(?:const|let|var)?\s*(?P<symbol>[\w${}\s,*]+)?\s*=?\s*require\(["'](?P<module>[^"']+)["']\)""")
_FETCH_RE = re.compile(r"""\bfetch\s*\(""")
_POOL_RE = re.compile(r"""\bnew\s+(Pool|Client)\s*\(""")
_SQS_RE = re.compile(r"""\bSQS\b|SendMessageCommand|ReceiveMessageCommand""")


def parse_integrations(source: str) -> list[ParsedIntegration]:
    integrations: list[ParsedIntegration] = []
    for line_number, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue

        module = _module_from_import(stripped)
        if module in _PROVIDERS:
            integration_type, provider = _PROVIDERS[module]
            integrations.append(
                ParsedIntegration(
                    integration_type=integration_type,
                    provider=provider,
                    symbol_name=_symbol_from_import(stripped),
                    evidence_text=_trim_evidence(stripped),
                    line_start=line_number,
                )
            )

        if _FETCH_RE.search(stripped):
            integrations.append(ParsedIntegration("http_api", "fetch", None, _trim_evidence(stripped), line_number))
        if _POOL_RE.search(stripped):
            integrations.append(ParsedIntegration("database", "postgresql", None, _trim_evidence(stripped), line_number))
        if _SQS_RE.search(stripped):
            integrations.append(ParsedIntegration("queue", "sqs", None, _trim_evidence(stripped), line_number))
    return _dedupe(integrations)


def _module_from_import(line: str) -> str | None:
    match = _IMPORT_RE.search(line) or _REQUIRE_RE.search(line)
    return match.group("module") if match else None


def _symbol_from_import(line: str) -> str | None:
    match = _IMPORT_RE.search(line) or _REQUIRE_RE.search(line)
    if not match:
        return None
    symbol = (match.group("symbol") or "").strip()
    return symbol or None


def _trim_evidence(line: str, limit: int = 240) -> str:
    return line[:limit]


def _dedupe(items: list[ParsedIntegration]) -> list[ParsedIntegration]:
    seen: set[tuple[str, str, int, str]] = set()
    deduped: list[ParsedIntegration] = []
    for item in items:
        key = (item.integration_type, item.provider, item.line_start, item.evidence_text)
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped
