from __future__ import annotations

from enum import StrEnum


class ScanStatus(StrEnum):
    QUEUED = "queued"
    CLONING = "cloning"
    FINGERPRINTING = "fingerprinting"
    INVENTORYING = "inventorying"
    EXTRACTING_STRUCTURE = "extracting_structure"
    EXTRACTING_INTEGRATIONS = "extracting_integrations"
    EXTRACTING_GIT = "extracting_git"
    EXTRACTING_SECURITY = "extracting_security"
    EXTRACTING_PERFORMANCE = "extracting_performance"
    NORMALIZING = "normalizing"
    REASONING = "reasoning"
    COMPLETED = "completed"
    FAILED = "failed"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
