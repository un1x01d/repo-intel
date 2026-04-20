from __future__ import annotations

import json

from repo_intel.ai.schemas import AIContextPack


def build_ask_prompt(context: AIContextPack) -> str:
    return (
        "You are repo-intel's evidence-backed Q&A layer. Answer the user's question using only the bounded context. "
        "If the context is insufficient, say so clearly. Do not infer unsupported implementation details. "
        "Cite evidence_ids from the context.\n\n"
        f"Context JSON:\n{json.dumps(context.model_dump(mode='json'), sort_keys=True)}"
    )
