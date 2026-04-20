from __future__ import annotations

import json
from typing import Any, Protocol

from repo_intel.core.config import Settings


class VertexUnavailableError(RuntimeError):
    """Raised when Vertex is not configured or cannot be reached."""


class VertexClient(Protocol):
    """Small interface that isolates the app from Vertex SDK churn."""

    def generate_json(self, *, prompt: str, response_schema: dict[str, Any]) -> dict[str, Any]: ...


class GoogleGenAIVertexClient:
    """Vertex Gemini client using ADC and the Google Gen AI SDK."""

    def __init__(self, settings: Settings) -> None:
        if not settings.vertex_project_id:
            raise VertexUnavailableError("REPO_INTEL_VERTEX_PROJECT_ID is required when AI is enabled")
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise VertexUnavailableError("google-genai is not installed") from exc

        self._types = types
        self._model = settings.vertex_model
        self._client = genai.Client(
            vertexai=True,
            project=settings.vertex_project_id,
            location=settings.vertex_location,
        )

    def generate_json(self, *, prompt: str, response_schema: dict[str, Any]) -> dict[str, Any]:
        config = self._types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=response_schema,
            temperature=0.2,
        )
        response = self._client.models.generate_content(model=self._model, contents=prompt, config=config)
        try:
            return json.loads(response.text or "{}")
        except json.JSONDecodeError as exc:
            raise VertexUnavailableError("Vertex returned invalid JSON") from exc


class DisabledVertexClient:
    """Client used when AI is disabled in local/dev environments."""

    def generate_json(self, *, prompt: str, response_schema: dict[str, Any]) -> dict[str, Any]:
        _ = prompt, response_schema
        raise VertexUnavailableError("AI reasoning is disabled")
