from __future__ import annotations

import json

from repo_intel.ai.schemas import AIContextPack


def build_summary_prompt(context: AIContextPack) -> str:
    return (
        "You are repo-intel's reasoning layer. Deterministic facts are the source of truth. "
        "Write one conservative repository summary using only supplied context. "
        "Do not invent architecture, dependencies, or behavior. Cite evidence_ids from the context.\n\n"
        f"Context JSON:\n{json.dumps(context.model_dump(mode='json'), sort_keys=True)}"
    )
