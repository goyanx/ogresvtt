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

_DM_SECRET_TERM_RE = re.compile(
    r"(?is)\b(area region context|map geometry|blocked line of sight|"
    r"trigger area|trigger-area|trigger[_\s-]?area|region[_\s-]?map|region key)\b"
)
_DM_REGION_CODE_RE = re.compile(r"\b[A-Z]{1,3}\d{1,3}\b")
_REGION_LABEL_RE = re.compile(r'in region "([^"]+)"', re.IGNORECASE)


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


def _extract_dm_region_labels(game_state: str) -> set[str]:
    if not game_state:
        return set()
    labels = {m.group(1).strip() for m in _REGION_LABEL_RE.finditer(game_state) if m.group(1).strip()}
    # Region-map style labels (e.g. N3, A12) should never be narrated to players.
    return {label for label in labels if _DM_REGION_CODE_RE.fullmatch(label)}


def _contains_dm_only_secrets(text: str, game_state: str) -> bool:
    if not text:
        return False
    if _DM_SECRET_TERM_RE.search(text):
        return True

    # Block explicit region-map identifiers such as N3/N6.
    dm_labels = _extract_dm_region_labels(game_state)
    lower_text = text.lower()
    for label in dm_labels:
        if re.search(rf"\b{re.escape(label.lower())}\b", lower_text):
            return True

    # Fallback: generic coded map labels can still leak hidden DM annotation.
    if _DM_REGION_CODE_RE.search(text):
        return True
    return False


def guard_narration(state: DMState) -> DMState:
    errors = list(state.get("validation_errors", []))
    tool_calls = state.get("tool_calls", []) or []
    game_state = state.get("game_state", "")

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
            continue
        if _contains_dm_only_secrets(text, game_state):
            errors.append(
                "narrate: narration leaks DM-only map/region secrets (e.g. hidden region keys or trigger notes); "
                "rewrite using only player-observable details"
            )

    narration = state.get("narration", "")
    if _looks_like_meta_or_tooling(narration) or _contains_dm_only_secrets(narration, game_state):
        narration = ""

    return {**state, "validation_errors": errors, "narration": narration}
