"""
Narration Guard node.

Ensures narration-like content does not leak tool-call JSON, app/system
diagnostics, or planning scaffolding into user-visible DM narration.
"""
from __future__ import annotations

import json
import re

from ai_dm.state import DMState


_META_NARRATION_RE = re.compile(
    r"(?is)(```|\"name\"\s*:|\"arguments\"\s*:|tool_calls?|"
    r"\[ai dm error\]|\bjson\b|^\s*step\s*\d+[:\-])"
)


def _looks_like_meta_or_tooling(text: str) -> bool:
    if not text:
        return False
    if _META_NARRATION_RE.search(text):
        return True
    # Reject blocky JSON-like payloads even without explicit keywords.
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return True
    return False


def guard_narration(state: DMState) -> DMState:
    errors = list(state.get("validation_errors", []))
    tool_calls = state.get("tool_calls", []) or []

    for tc in tool_calls:
        fn = tc.get("function", {})
        if fn.get("name") != "narrate":
            continue
        raw = fn.get("arguments", "{}")
        try:
            args = json.loads(raw)
        except json.JSONDecodeError:
            errors.append("narrate: invalid JSON arguments")
            continue

        text = (args.get("text") or "").strip()
        if not text:
            errors.append("narrate: text must not be empty")
            continue
        if len(text) > 600:
            errors.append("narrate: text too long; keep narration concise")
            continue
        if _looks_like_meta_or_tooling(text):
            errors.append("narrate: narration contains tool/app/system metadata; provide in-world prose only")

    narration = state.get("narration", "")
    if _looks_like_meta_or_tooling(narration):
        narration = ""

    return {**state, "validation_errors": errors, "narration": narration}

