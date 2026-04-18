"""
Plan Actions node.
Takes the situational assessment and produces a structured action plan
(which tools to call and in what order) before execution.
"""
from ai_dm.state import DMState
from ai_dm.tools import TOOL_DEFINITIONS


PLAN_PROMPT = """You are an AI Dungeon Master.
Based on the assessment below, call the appropriate tools to run this turn.
Call 'narrate' once plus any movement/combat/spawn tools needed.

ASSESSMENT:
{plan}

GAME STATE:
{game_state}
"""


async def plan(state: DMState, llm_call) -> DMState:
    prompt = PLAN_PROMPT.format(plan=state["plan"], game_state=state["game_state"])
    messages = list(state["history"]) + [{"role": "user", "content": prompt}]
    response = await llm_call(messages, tools=TOOL_DEFINITIONS)
    message = response["choices"][0]["message"]
    tool_calls = message.get("tool_calls") or []
    narration = message.get("content") or ""
    return {**state, "tool_calls": tool_calls, "narration": narration}
