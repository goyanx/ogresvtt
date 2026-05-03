"""
Combat Planner node.

Specialized planner path for active encounters. This functions as a dedicated
combat agent prompt and planning loop, separate from the generic planner.
"""
from __future__ import annotations

import json
import os
import re

from ai_dm.state import DMState
from ai_dm.tools import QUERY_TOOLS, TOOL_DEFINITIONS
from ai_dm.query_executor import execute_query_tool


def _env_int(name: str, default: int, minimum: int = 1, maximum: int = 20) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


MAX_QUERY_ROUNDS = _env_int("AI_DM_MAX_QUERY_ROUNDS", default=4, minimum=1, maximum=20)


COMBAT_PLAN_PROMPT = """You are the combat-resolution planner for an AI Dungeon Master.
Produce legal, deterministic combat actions for the current turn.

Follow this sequence when relevant:
1) If initiative is not established, call roll_initiative for all combatants.
2) Resolve one active participant turn at a time.
3) For attacks, use roll_dice then resolve_attack_vs_ac.
4) For damage, use resolve_damage (respect vulnerabilities/resistances/immunities).
5) Consider spells, reactions, and special abilities using get_character_sheet, get_monster_stats, and retrieve_rules.
6) Apply HP updates only after damage is resolved; prefer apply_damage for delta updates.

Rules:
- Use sidecar query tools first when information is uncertain.
- Use deterministic tool calls; do not do hidden arithmetic in prose.
- Call narrate once with concise in-world narration.
- If any PC/NPC roll occurs this turn, narrate the actual rolled number(s).
- If resolve_damage returns positive damage, you must apply it to a target via apply_damage (preferred) or update_hp before advance_turn.
- Narration is player-facing: never reveal hidden map/region metadata, trigger notes, AREA REGION CONTEXT text, BLOCKED LINE OF SIGHT summaries, or region-map keys like N3/N6.
- Never include internal IDs/keys/labels from game-state internals in narration.
- All output must be English only.

ASSESSMENT:
{plan}

GAME STATE:
{game_state}
"""


def _extract_narrate_text(action_calls: list[dict]) -> str:
    for tc in action_calls:
        fn = tc.get("function", {})
        if fn.get("name") != "narrate":
            continue
        try:
            args = json.loads(fn.get("arguments", "{}"))
        except json.JSONDecodeError:
            return ""
        return (args.get("text") or "").strip()
    return ""


def _roll_markers_from_result(result: str) -> set[str]:
    try:
        data = json.loads(result)
    except json.JSONDecodeError:
        return set()
    markers: set[str] = set()
    total = data.get("total")
    natural = data.get("natural_roll")
    if isinstance(total, int):
        markers.add(str(total))
    if isinstance(natural, int):
        markers.add(str(natural))
    return markers


def _narration_discloses_rolls(narration_text: str, roll_markers: list[set[str]]) -> tuple[bool, list[str]]:
    text = narration_text or ""
    missing: list[str] = []
    for markers in roll_markers:
        if not markers:
            continue
        if not any(re.search(rf"\b{re.escape(marker)}\b", text) for marker in markers):
            missing.append("/".join(sorted(markers)))
    return (len(missing) == 0, missing)


async def plan_combat(state: DMState, llm_call) -> DMState:
    prompt = COMBAT_PLAN_PROMPT.format(plan=state["plan"], game_state=state["game_state"])
    messages = list(state["history"]) + [{"role": "user", "content": prompt}]

    action_calls = []
    content = ""
    roll_markers: list[set[str]] = []
    requires_hp_application = False

    for _ in range(MAX_QUERY_ROUNDS):
        response = await llm_call(messages, tools=TOOL_DEFINITIONS)
        message = response["choices"][0]["message"]
        tool_calls = message.get("tool_calls") or []
        content = message.get("content") or ""

        query_calls = [tc for tc in tool_calls if tc["function"]["name"] in QUERY_TOOLS]
        action_calls = [tc for tc in tool_calls if tc["function"]["name"] not in QUERY_TOOLS]

        if not query_calls:
            errors = list(state.get("validation_errors", []))
            narration_text = _extract_narrate_text(action_calls)
            ok, missing = _narration_discloses_rolls(narration_text, roll_markers)
            if roll_markers and not ok:
                errors.append(
                    "combat narrate: include visible roll result number(s) for this turn "
                    f"(missing: {', '.join(missing)})"
                )
            if requires_hp_application:
                has_hp_apply = any(
                    tc.get("function", {}).get("name") in {"apply_damage", "update_hp"}
                    for tc in action_calls
                )
                if not has_hp_apply:
                    errors.append(
                        "combat: resolve_damage produced positive damage but no HP update tool was called; "
                        "add apply_damage (preferred) or update_hp before advance_turn"
                    )
            return {
                **state,
                "tool_calls": action_calls,
                "narration": content,
                "combat_mode": True,
                "validation_errors": errors,
            }

        messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})
        for tc in query_calls:
            fn_name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"].get("arguments", "{}"))
            except json.JSONDecodeError:
                args = {}
            result = execute_query_tool(fn_name, args, state["game_state"])
            if fn_name == "roll_dice":
                markers = _roll_markers_from_result(result)
                if markers:
                    roll_markers.append(markers)
            if fn_name == "resolve_damage":
                try:
                    damage_result = json.loads(result)
                except json.JSONDecodeError:
                    damage_result = {}
                final_damage = damage_result.get("final_damage")
                if isinstance(final_damage, int) and final_damage > 0:
                    requires_hp_application = True
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.get("id", fn_name),
                    "content": result,
                }
            )

    errors = list(state.get("validation_errors", []))
    narration_text = _extract_narrate_text(action_calls)
    ok, missing = _narration_discloses_rolls(narration_text, roll_markers)
    if roll_markers and not ok:
        errors.append(
            "combat narrate: include visible roll result number(s) for this turn "
            f"(missing: {', '.join(missing)})"
        )
    if requires_hp_application:
        has_hp_apply = any(
            tc.get("function", {}).get("name") in {"apply_damage", "update_hp"}
            for tc in action_calls
        )
        if not has_hp_apply:
            errors.append(
                "combat: resolve_damage produced positive damage but no HP update tool was called; "
                "add apply_damage (preferred) or update_hp before advance_turn"
            )
    return {
        **state,
        "tool_calls": action_calls,
        "narration": content,
        "combat_mode": True,
        "validation_errors": errors,
    }
