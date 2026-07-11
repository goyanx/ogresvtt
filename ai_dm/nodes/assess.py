"""
Assess Situation node.
Reads game state and produces a concise situational summary the planner uses.
No tool calls here — pure reasoning.
"""
from ai_dm.state import DMState
from ai_dm.intent import classify_response_mode, latest_player_message


ASSESS_PROMPT = """You are an AI Dungeon Master assistant.
Review the game state below and write a brief (3-5 sentence) internal assessment:
- What is happening on the board right now?
- Which NPCs/monsters are present and what should they do?
- Are players in danger? Should combat start or continue?
- What would make this turn dramatic and fun?
- If response mode is "dm", prioritize answering the player's out-of-character request directly and accurately.
- If response mode is "npc", prioritize immersive in-world delivery.

Do NOT narrate to players yet. This is internal planning only.\nWrite your assessment in English only.

LATEST PLAYER MESSAGE:
{latest_player_message}

RESPONSE MODE:
{response_mode} ({response_mode_reason})

CHARACTER SHEETS (authoritative stats from the campaign database):
{character_context}

SCENARIO:
{scenario}

SYSTEM INSTRUCTIONS (authoritative):
{system_prompt}

GAME STATE:
{game_state}
"""


async def assess(state: DMState, llm_call) -> DMState:
    player_msg = latest_player_message(state.get("history", []))
    response_mode, response_mode_reason = classify_response_mode(player_msg)
    prompt = ASSESS_PROMPT.format(
        latest_player_message=player_msg or "(none)",
        response_mode=response_mode,
        response_mode_reason=response_mode_reason,
        character_context=state.get("character_context") or "(none on file)",
        scenario=state["scenario"] or "(none)",
        system_prompt=state.get("system_prompt") or "(none)",
        game_state=state["game_state"] or "(empty scene)",
    )
    messages = [{"role": "user", "content": prompt}]
    response = await llm_call(messages, tools=[])
    assessment = response["choices"][0]["message"]["content"] or ""
    return {
        **state,
        "plan": assessment,
        "response_mode": response_mode,
        "response_mode_reason": response_mode_reason,
        "latest_player_message": player_msg,
    }

