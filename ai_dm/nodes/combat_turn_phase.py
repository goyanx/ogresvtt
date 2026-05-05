"""
Combat turn-phase gate.

Enforces a minimal, deterministic ordering for combat tool calls produced by
the combat planner before they reach narration guard/dispatch.
"""
from __future__ import annotations

import json
import re
from typing import Any

from ai_dm.state import DMState


def _parse_args(tc: dict[str, Any]) -> dict[str, Any]:
    raw = tc.get("function", {}).get("arguments", "{}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _extract_current_turn_id(game_state: str) -> int | None:
    text = game_state or ""
    m = re.search(r"CURRENT TURN ID:\s*(\d+)", text)
    if m:
        return int(m.group(1))
    m = re.search(r"id:\s*(\d+).*?current_turn:\s*true", text, flags=re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def _extract_token_positions(game_state: str) -> dict[int, tuple[float, float]]:
    text = game_state or ""
    # Serialized token lines look like:
    # "  - id: 12, label: \"...\", pos: (123.0, 456.0), ..."
    matches = re.findall(
        r"id:\s*(\d+).*?pos:\s*\(\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)",
        text,
        flags=re.IGNORECASE,
    )
    out: dict[int, tuple[float, float]] = {}
    for tid, x, y in matches:
        out[int(tid)] = (float(x), float(y))
    return out


def enforce_combat_turn_phase(state: DMState) -> DMState:
    if not state.get("combat_mode"):
        return state

    errors = list(state.get("validation_errors", []))
    game_state = state.get("game_state", "") or ""
    tool_calls = state.get("tool_calls", []) or []
    if not tool_calls:
        errors.append("combat: no tool calls produced for turn")
        return {**state, "validation_errors": errors}

    turn_id = _extract_current_turn_id(game_state)
    token_positions = _extract_token_positions(game_state)
    if turn_id is None:
        errors.append("combat: missing current initiative turn; cannot resolve active combatant")
    elif turn_id not in token_positions:
        errors.append(
            f"combat: active initiative token {turn_id} has no position; "
            "token-position checks cannot run"
        )

    names = [tc.get("function", {}).get("name", "") for tc in tool_calls]
    idx = {name: i for i, name in enumerate(names)}

    has_narrate = "narrate" in idx
    has_advance = "advance_turn" in idx
    has_leave = "leave_initiative" in idx
    has_hp_change = "update_hp" in idx or "apply_damage" in idx

    if not has_narrate:
        errors.append("combat: missing narrate tool call")
    if not has_advance and not has_leave:
        errors.append(
            "combat: missing turn terminator; end each resolved turn with advance_turn, "
            "or call leave_initiative if combat has ended"
        )
    if has_advance and has_leave:
        errors.append("combat: use either advance_turn or leave_initiative, not both")
    if names.count("advance_turn") > 1:
        errors.append("combat: advance_turn must be called exactly once per resolved turn")
    if names.count("leave_initiative") > 1:
        errors.append("combat: leave_initiative must be called at most once per turn")

    # Ordering constraints among action tools.
    if has_advance and has_narrate and idx["advance_turn"] < idx["narrate"]:
        errors.append("combat: advance_turn should occur after narrate")
    if has_leave and has_narrate and idx["leave_initiative"] < idx["narrate"]:
        errors.append("combat: leave_initiative should occur after narrate")
    if has_advance and idx["advance_turn"] != (len(names) - 1):
        errors.append("combat: advance_turn must be the final tool call after turn resolution")
    if has_leave and idx["leave_initiative"] != (len(names) - 1):
        errors.append("combat: leave_initiative must be the final tool call after turn resolution")

    # Validate HP mutation argument shapes.
    if has_hp_change:
        for tc in tool_calls:
            args = _parse_args(tc)
            tool_name = tc.get("function", {}).get("name")
            if tool_name == "update_hp":
                hp_val = args.get("hp")
                if not isinstance(hp_val, int):
                    errors.append("combat: update_hp.hp must be integer")
            elif tool_name == "apply_damage":
                amount = args.get("amount")
                mode = args.get("mode", "damage")
                if not isinstance(amount, int):
                    errors.append("combat: apply_damage.amount must be integer")
                elif amount < 0:
                    errors.append("combat: apply_damage.amount must be non-negative")
                if mode not in {"damage", "healing"}:
                    errors.append("combat: apply_damage.mode must be damage or healing")

    return {**state, "validation_errors": errors}
