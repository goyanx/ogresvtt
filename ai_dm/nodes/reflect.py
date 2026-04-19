"""
Reflect & Retry node.
When validation fails, sends the errors back to the LLM with the original
plan and asks it to produce corrected tool calls.
"""
import logging
from ai_dm.state import DMState
from ai_dm.tools import TOOL_DEFINITIONS

logger = logging.getLogger(__name__)


REFLECT_PROMPT = """Your previous tool calls had the following errors:
{errors}

Original game state for reference:
{game_state}

Please correct the tool calls and try again. Only output valid tool calls.
"""


async def reflect(state: DMState, llm_call) -> DMState:
    logger.warning(
        "reflect retry=%s validation_errors=%s",
        state.get("retry_count", 0) + 1,
        len(state.get("validation_errors", [])),
    )
    errors_text = "\n".join(f"- {e}" for e in state["validation_errors"])
    prompt = REFLECT_PROMPT.format(errors=errors_text, game_state=state["game_state"])
    messages = [{"role": "user", "content": prompt}]
    response = await llm_call(messages, tools=TOOL_DEFINITIONS)
    message = response["choices"][0]["message"]
    tool_calls = message.get("tool_calls") or []
    logger.info("reflect produced tool_calls=%s", len(tool_calls))
    return {**state, "tool_calls": tool_calls, "retry_count": state["retry_count"] + 1}
