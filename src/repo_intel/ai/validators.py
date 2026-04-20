from __future__ import annotations

from typing import TypeVar
from uuid import UUID

from pydantic import BaseModel, ValidationError

from repo_intel.ai.schemas import GroundedInsight

T = TypeVar("T", bound=BaseModel)


class AIValidationError(ValueError):
    """Raised when a model response is structurally invalid or unsupported by evidence."""


def validate_model_output(model: type[T], payload: dict[str, object], allowed_evidence_ids: set[UUID]) -> T:
    try:
        parsed = model.model_validate(payload)
    except ValidationError as exc:
        raise AIValidationError(str(exc)) from exc
    for insight in _iter_insights(parsed):
        missing = set(insight.evidence_ids) - allowed_evidence_ids
        if missing:
            raise AIValidationError(f"AI response cited evidence IDs outside the context pack: {sorted(str(item) for item in missing)}")
    return parsed


def _iter_insights(model: BaseModel) -> list[GroundedInsight]:
    values = []
    for value in model.__dict__.values():
        if isinstance(value, GroundedInsight):
            values.append(value)
        elif isinstance(value, list):
            values.extend(item for item in value if isinstance(item, GroundedInsight))
    return values
