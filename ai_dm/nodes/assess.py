"""
Assess Situation node.
Reads game state and produces a concise situational summary the planner uses.
No tool calls here — pure reasoning.
"""
import logging
import time
from ai_dm.state import DMState

logger = logging.getLogger(__name__)


ASSESS_PROMPT = """You are an AI Dungeon Master assistant.
Review the game state below and write a brief (3-5 sentence) internal assessment:
- What is happening on the board right now?
- Which NPCs/monsters are present and what should they do?
- Are players in danger? Should combat start or continue?
- What would make this turn dramatic and fun?

Do NOT narrate to players yet. This is internal planning only.

SCENARIO:
{scenario}

GAME STATE:
{game_state}
"""


async def assess(state: DMState, llm_call) -> DMState:
    logger.info("assess start game_state_chars=%s", len(state.get("game_state", "")))
    prompt = ASSESS_PROMPT.format(
        scenario=state["scenario"] or "(none)",
        game_state=state["game_state"] or "(empty scene)",
    )
    messages = [{"role": "user", "content": prompt}]
    t0 = time.perf_counter()
    response = await llm_call(messages, tools=[])
    duration_ms = (time.perf_counter() - t0) * 1000
    assessment = response["choices"][0]["message"]["content"] or ""
    logger.info("assess complete duration_ms=%.0f assessment_chars=%s", duration_ms, len(assessment))
    return {**state, "plan": assessment}
