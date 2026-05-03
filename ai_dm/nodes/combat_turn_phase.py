"""
Combat turn-phase gate.

Enforces a minimal, deterministic ordering for combat tool calls produced by
the combat planner before they reach narration guard/dispatch.
"""
from __future__ import annotations

import json
from typing import Any

from ai_dm.state import DMState


def _parse_args(tc: dict[str, Any]) -> dict[str, Any]:
    raw = tc.get("function", {}).get("arguments", "{}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def enforce_combat_turn_phase(state: DMState) -> DMState:
    if not state.get("combat_mode"):
        return state

    errors = list(state.get("validation_errors", []))
    tool_calls = state.get("tool_calls", []) or []
    if not tool_calls:
        errors.append("combat: no tool calls produced for turn")
        return {**state, "validation_errors": errors}

    names = [tc.get("function", {}).get("name", "") for tc in tool_calls]
    idx = {name: i for i, name in enumerate(names)}

    has_narrate = "narrate" in idx
    has_advance = "advance_turn" in idx
    has_hp_change = "update_hp" in idx or "apply_damage" in idx
    has_attack_math = "resolve_attack_vs_ac" in idx or "resolve_damage" in idx
    has_roll = "roll_dice" in idx

    if not has_narrate:
        errors.append("combat: missing narrate tool call")
    if not has_advance:
        errors.append("combat: missing advance_turn; end each resolved combatant turn by advancing initiative")
    if names.count("advance_turn") > 1:
        errors.append("combat: advance_turn must be called exactly once per resolved turn")
    if has_hp_change and not has_attack_math:
        errors.append("combat: HP change used without attack/damage resolution")
    if "resolve_attack_vs_ac" in idx and not has_roll:
        errors.append("combat: resolve_attack_vs_ac should be preceded by roll_dice")

    # Ordering constraints (when present together)
    if "resolve_attack_vs_ac" in idx and "resolve_damage" in idx:
        if idx["resolve_damage"] < idx["resolve_attack_vs_ac"]:
            errors.append("combat: resolve_damage must occur after resolve_attack_vs_ac")
    if "resolve_damage" in idx and "update_hp" in idx:
        if idx["update_hp"] < idx["resolve_damage"]:
            errors.append("combat: update_hp must occur after resolve_damage")
    if "resolve_damage" in idx and "apply_damage" in idx:
        if idx["apply_damage"] < idx["resolve_damage"]:
            errors.append("combat: apply_damage must occur after resolve_damage")
    if has_advance and has_narrate and idx["advance_turn"] < idx["narrate"]:
        errors.append("combat: advance_turn should occur after narrate")
    if has_advance and idx["advance_turn"] != (len(names) - 1):
        errors.append("combat: advance_turn must be the final tool call after turn resolution")

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
