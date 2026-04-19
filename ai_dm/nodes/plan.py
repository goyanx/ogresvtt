"""
Plan Actions node.
Takes the situational assessment and produces a structured action plan.

Implements a query-feedback loop so the LLM can call list_tokens (and any
future query tools) and receive real data back before committing to actions.

Loop (max MAX_QUERY_ROUNDS iterations):
  1. Call LLM with all tools
  2. If response contains only query tools → execute them, append tool results, repeat
  3. If response contains action tools (or no tools) → done, return action tool calls
"""
import json
import logging
from ai_dm.state import DMState
from ai_dm.tools import TOOL_DEFINITIONS, QUERY_TOOLS
from ai_dm.query_executor import execute_query_tool

logger = logging.getLogger(__name__)

MAX_QUERY_ROUNDS = 3

PLAN_PROMPT = """You are an AI Dungeon Master.
Based on the assessment below, call the appropriate tools to run this turn.
You may first call list_tokens to confirm who is on the board.
Then call 'narrate' once plus any movement/combat/spawn tools needed.

ASSESSMENT:
{plan}

GAME STATE:
{game_state}
"""


async def plan(state: DMState, llm_call) -> DMState:
    prompt = PLAN_PROMPT.format(plan=state["plan"], game_state=state["game_state"])
    messages = list(state["history"]) + [{"role": "user", "content": prompt}]
    logger.info("plan start history_count=%s", len(state.get("history", [])))

    action_calls = []
    content = ""
    for round_idx in range(MAX_QUERY_ROUNDS):
        logger.info("plan round=%s", round_idx + 1)
        response = await llm_call(messages, tools=TOOL_DEFINITIONS)
        message = response["choices"][0]["message"]
        tool_calls = message.get("tool_calls") or []
        content = message.get("content") or ""

        query_calls  = [tc for tc in tool_calls if tc["function"]["name"] in QUERY_TOOLS]
        action_calls = [tc for tc in tool_calls if tc["function"]["name"] not in QUERY_TOOLS]
        logger.info(
            "plan tool_calls total=%s query=%s action=%s",
            len(tool_calls),
            len(query_calls),
            len(action_calls),
        )

        if not query_calls:
            # No more queries — return action tool calls to be validated and dispatched
            logger.info("plan complete without further queries")
            return {**state, "tool_calls": action_calls, "narration": content}

        # Execute query tools locally and feed results back to the LLM
        messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})
        for tc in query_calls:
            fn_name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"].get("arguments", "{}"))
            except json.JSONDecodeError:
                logger.warning("plan query args parse failed tool=%s", fn_name)
                args = {}
            result = execute_query_tool(fn_name, args, state["game_state"])
            logger.info("plan query executed tool=%s result_chars=%s", fn_name, len(result or ""))
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", fn_name),
                "content": result,
            })
        # Loop — LLM now has the query results and can plan actions

    # Exhausted query rounds — return whatever action calls we have
    logger.warning("plan exhausted query rounds; returning current action calls")
    return {**state, "tool_calls": action_calls, "narration": content}
