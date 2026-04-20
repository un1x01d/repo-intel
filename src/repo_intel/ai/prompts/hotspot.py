from __future__ import annotations

import json

from repo_intel.ai.schemas import AIContextPack


def build_hotspot_prompt(context: AIContextPack) -> str:
    return (
        "You are repo-intel's reasoning layer. Produce up to five hotspot insights. "
        "Only use supplied deterministic findings, evidence, git metrics, and graph summaries. "
        "Phrase outputs as risk signals, not proven defects. Cite evidence_ids from the context.\n\n"
        f"Context JSON:\n{json.dumps(context.model_dump(mode='json'), sort_keys=True)}"
    )
