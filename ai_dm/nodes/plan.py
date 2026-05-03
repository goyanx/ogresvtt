"""
Plan Actions node.
Takes the situational assessment and produces a structured action plan.

Implements a query-feedback loop so the LLM can call sidecar query tools and
receive real data back before committing to actions.

Loop (max MAX_QUERY_ROUNDS iterations):
  1. Call LLM with all tools
  2. If response contains only query tools → execute them, append tool results, repeat
  3. If response contains action tools (or no tools) → done, return action tool calls
"""
import json
import os
import re
from ai_dm.state import DMState
from ai_dm.tools import TOOL_DEFINITIONS, QUERY_TOOLS
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

PLAN_PROMPT = """You are an AI Dungeon Master.
Based on the assessment below, call the appropriate tools to run this turn.
All output must be English only, including narration text and any freeform tool arguments.

When needed, use sidecar query tools before acting:
- list_tokens: confirm board IDs and positions.
- retrieve_rules / get_monster_stats: rules and monster RAG grounding.
- get_character_sheet / get_rulings: maintain continuity.
- roll_dice / resolve_attack_vs_ac / resolve_damage: deterministic combat math.
- record_combat_event / save_ruling: persist key outcomes.
- upsert_map_config / list_map_configs: map metadata and render settings.\n- upsert_token_position / evaluate_triggers: location-driven narrative events.\n- show_map: switch/render selected map in the client app.

After gathering enough context, call 'narrate' once plus any movement/combat/spawn tools needed.

Narration guardrail (player-facing):
- Never reveal DM-only map metadata, hidden trigger notes, AREA REGION CONTEXT text, BLOCKED LINE OF SIGHT summaries, or region-map codes like N3/N6.
- Do not mention internal IDs/keys/labels from the game state. Convert secret/internal context into sensory, in-world description only.

ASSESSMENT:
{plan}

SYSTEM INSTRUCTIONS (authoritative):
{system_prompt}

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


async def plan(state: DMState, llm_call) -> DMState:
    prompt = PLAN_PROMPT.format(
        plan=state["plan"],
        system_prompt=state.get("system_prompt") or "(none)",
        game_state=state["game_state"],
    )
    messages = list(state["history"]) + [{"role": "user", "content": prompt}]
    roll_markers: list[set[str]] = []
    action_calls: list[dict] = []
    content = ""

    for _ in range(MAX_QUERY_ROUNDS):
        response = await llm_call(messages, tools=TOOL_DEFINITIONS)
        message = response["choices"][0]["message"]
        tool_calls = message.get("tool_calls") or []
        content = message.get("content") or ""

        query_calls = [tc for tc in tool_calls if tc["function"]["name"] in QUERY_TOOLS]
        action_calls = [tc for tc in tool_calls if tc["function"]["name"] not in QUERY_TOOLS]

        if not query_calls:
            # No more queries — return action tool calls to be validated and dispatched
            errors = list(state.get("validation_errors", []))
            narration_text = _extract_narrate_text(action_calls)
            ok, missing = _narration_discloses_rolls(narration_text, roll_markers)
            if roll_markers and not ok:
                errors.append(
                    "narrate: include visible roll result number(s) for this turn "
                    f"(missing: {', '.join(missing)})"
                )
            return {
                **state,
                "tool_calls": action_calls,
                "narration": content,
                "combat_mode": False,
                "validation_errors": errors,
            }

        # Execute query tools locally and feed results back to the LLM
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
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.get("id", fn_name),
                    "content": result,
                }
            )
        # Loop — LLM now has query results and can refine actions.

    # Exhausted query rounds — return whatever action calls we have
    errors = list(state.get("validation_errors", []))
    narration_text = _extract_narrate_text(action_calls)
    ok, missing = _narration_discloses_rolls(narration_text, roll_markers)
    if roll_markers and not ok:
        errors.append(
            "narrate: include visible roll result number(s) for this turn "
            f"(missing: {', '.join(missing)})"
        )
    return {
        **state,
        "tool_calls": action_calls,
        "narration": content,
        "combat_mode": False,
        "validation_errors": errors,
    }

