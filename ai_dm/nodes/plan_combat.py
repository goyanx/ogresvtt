"""
Combat Planner node.

Specialized planner path for active encounters. This functions as a dedicated
combat agent prompt and planning loop, separate from the generic planner.
"""
from __future__ import annotations

import json
import os

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
- Narration is player-facing: never reveal hidden map/region metadata, trigger notes, AREA REGION CONTEXT text, BLOCKED LINE OF SIGHT summaries, or region-map keys like N3/N6.
- Never include internal IDs/keys/labels from game-state internals in narration.
- If a turn is fully resolved, advance_turn.
- All output must be English only.

ASSESSMENT:
{plan}

GAME STATE:
{game_state}
"""


async def plan_combat(state: DMState, llm_call) -> DMState:
    prompt = COMBAT_PLAN_PROMPT.format(plan=state["plan"], game_state=state["game_state"])
    messages = list(state["history"]) + [{"role": "user", "content": prompt}]

    action_calls = []
    content = ""

    for _ in range(MAX_QUERY_ROUNDS):
        response = await llm_call(messages, tools=TOOL_DEFINITIONS)
        message = response["choices"][0]["message"]
        tool_calls = message.get("tool_calls") or []
        content = message.get("content") or ""

        query_calls = [tc for tc in tool_calls if tc["function"]["name"] in QUERY_TOOLS]
        action_calls = [tc for tc in tool_calls if tc["function"]["name"] not in QUERY_TOOLS]

        if not query_calls:
            return {
                **state,
                "tool_calls": action_calls,
                "narration": content,
                "combat_mode": True,
            }

        messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})
        for tc in query_calls:
            fn_name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"].get("arguments", "{}"))
            except json.JSONDecodeError:
                args = {}
            result = execute_query_tool(fn_name, args, state["game_state"])
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.get("id", fn_name),
                    "content": result,
                }
            )

    return {
        **state,
        "tool_calls": action_calls,
        "narration": content,
        "combat_mode": True,
    }
