"""
LangGraph StateGraph for the AI Dungeon Master.

Flow:
  assess_situation
       ↓ route by game state
  plan_actions OR plan_combat_actions  (calls LLM with tools)
       ↓
  guard_narration (no LLM call — narration quality/safety checks)
       ↓
  validate      (no LLM call — argument/game-state checks)
       ↓ errors?
    yes → reflect_retry → guard_narration → validate (up to MAX_RETRIES times)
    no  → END

The graph returns the final tool_calls list to the FastAPI handler,
which serialises them back to the ClojureScript client.
"""
import functools
import json
import logging
import os
import re
from typing import TypedDict
from langgraph.graph import StateGraph, END

from ai_dm.state import DMState
from ai_dm.nodes.assess import assess
from ai_dm.nodes.guard_narration import guard_narration
from ai_dm.nodes.plan import plan
from ai_dm.nodes.plan_combat import plan_combat
from ai_dm.nodes.combat_turn_phase import enforce_combat_turn_phase
from ai_dm.nodes.validate import validate
from ai_dm.nodes.reflect import reflect


def _env_int(name: str, default: int, minimum: int = 0, maximum: int = 10) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


MAX_RETRIES = _env_int("AI_DM_MAX_RETRIES", default=2, minimum=0, maximum=10)
ENABLE_COMBAT_AGENT = os.getenv("AI_DM_ENABLE_COMBAT_AGENT", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

_ROUND_RE = re.compile(r"ROUND:\s*(\d+)")
_CURRENT_TURN_RE = re.compile(r"CURRENT TURN ID:\s*(\d+)")

logger = logging.getLogger(__name__)


class ImagePromptState(TypedDict, total=False):
    source_prompt: str
    style_hint: str
    model_family: str
    positive_prompt: str
    negative_prompt: str


def _extract_json_object(text: str) -> dict:
    raw = (text or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        pass

    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


async def _transform_image_prompt(state: ImagePromptState, llm_call):
    source_prompt = (state.get("source_prompt") or "").strip()
    style_hint = (state.get("style_hint") or "").strip()
    model_family = (state.get("model_family") or "flux").strip().lower()

    system = (
        "You convert tabletop DM narration into an image-generation prompt for ComfyUI models. "
        "Respond as JSON only with keys: positive_prompt, negative_prompt. "
        "Keep positive_prompt concise but vivid (1-3 sentences), cinematic, and visually grounded. "
        "For FLUX, prefer natural language scene detail and avoid comma spam. "
        "negative_prompt should contain short quality/safety negatives (no gore, no text watermark, no logo)."
    )
    user = (
        f"Model family: {model_family}\n"
        f"Style hint: {style_hint or '(none)'}\n"
        f"Source narration:\n{source_prompt}\n\n"
        'Return JSON: {"positive_prompt":"...","negative_prompt":"..."}'
    )
    resp = await llm_call(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        [],
    )
    content = (
        (resp.get("choices") or [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    payload = _extract_json_object(content)
    positive = (payload.get("positive_prompt") or source_prompt).strip()
    negative = (payload.get("negative_prompt") or "").strip()
    return {"positive_prompt": positive, "negative_prompt": negative}


def _sanitize_image_prompt(state: ImagePromptState):
    positive = (state.get("positive_prompt") or "").strip()
    negative = (state.get("negative_prompt") or "").strip()
    if not positive:
        positive = (state.get("source_prompt") or "fantasy tabletop scene").strip()
    # Keep payload compact for Comfy nodes.
    if len(positive) > 700:
        positive = positive[:700].rsplit(" ", 1)[0]
    if len(negative) > 350:
        negative = negative[:350].rsplit(" ", 1)[0]
    return {"positive_prompt": positive, "negative_prompt": negative}


def _initiative_context(game_state: str) -> tuple[int, int | None, int]:
    text = game_state or ""
    if "INITIATIVE TRACKER:" not in text:
        return (0, None, 0)
    _, body = text.split("INITIATIVE TRACKER:", 1)
    entries = re.findall(r"^\s*-\s*id:\s*(\d+)", body, flags=re.MULTILINE)
    turn_match = _CURRENT_TURN_RE.search(body)
    round_match = _ROUND_RE.search(body)
    turn_id = int(turn_match.group(1)) if turn_match else None
    rounds = int(round_match.group(1)) if round_match else 0
    return (len(entries), turn_id, rounds)


def _is_combat_state(game_state: str) -> bool:
    entries, turn_id, _rounds = _initiative_context(game_state)
    # Combat-planner path requires an active initiative turn to resolve.
    return entries > 0 and turn_id is not None

def _should_retry(state: DMState) -> str:
    if state["validation_errors"] and state["retry_count"] < MAX_RETRIES:
        return "reflect_retry"
    return END


def _route_planner(state: DMState) -> str:
    if not ENABLE_COMBAT_AGENT:
        logger.info("dm_route planner=plan_actions reason=combat_agent_disabled")
        return "plan_actions"
    game_state = state.get("game_state", "")
    entries, turn_id, rounds = _initiative_context(game_state)
    if _is_combat_state(game_state):
        logger.info(
            "dm_route planner=plan_combat_actions reason=active_initiative entries=%s turn_id=%s rounds=%s",
            entries,
            turn_id,
            rounds,
        )
        return "plan_combat_actions"
    logger.info(
        "dm_route planner=plan_actions reason=no_active_initiative entries=%s turn_id=%s rounds=%s",
        entries,
        turn_id,
        rounds,
    )
    return "plan_actions"


def _route_post_reflect(state: DMState) -> str:
    if state.get("combat_mode"):
        return "combat_turn_phase"
    return "guard_narration"


def build_graph(llm_call):
    """
    llm_call: async callable(messages, tools) → OpenAI-compatible response dict.
    Inject the backend-specific function so the graph stays backend-agnostic.
    """
    bound_assess  = functools.partial(assess, llm_call=llm_call)
    bound_plan    = functools.partial(plan,   llm_call=llm_call)
    bound_plan_combat = functools.partial(plan_combat, llm_call=llm_call)
    bound_reflect = functools.partial(reflect, llm_call=llm_call)

    g = StateGraph(DMState)
    g.add_node("assess_situation", bound_assess)
    g.add_node("plan_actions",     bound_plan)
    g.add_node("plan_combat_actions", bound_plan_combat)
    g.add_node("combat_turn_phase", enforce_combat_turn_phase)
    g.add_node("guard_narration",  guard_narration)
    g.add_node("validate",         validate)
    g.add_node("reflect_retry",    bound_reflect)

    g.set_entry_point("assess_situation")
    g.add_conditional_edges("assess_situation", _route_planner)
    g.add_edge("plan_actions",     "guard_narration")
    g.add_edge("plan_combat_actions", "combat_turn_phase")
    g.add_edge("combat_turn_phase", "guard_narration")
    g.add_edge("guard_narration",  "validate")
    g.add_conditional_edges("validate", _should_retry)
    g.add_conditional_edges("reflect_retry", _route_post_reflect)

    return g.compile()


def build_image_prompt_graph(llm_call):
    """
    LangGraph prompt transformer for ComfyUI image workflows.
    Converts DM narration/source text into model-friendly positive/negative prompts.
    """
    bound_transform = functools.partial(_transform_image_prompt, llm_call=llm_call)

    g = StateGraph(ImagePromptState)
    g.add_node("transform_prompt", bound_transform)
    g.add_node("sanitize_prompt", _sanitize_image_prompt)
    g.set_entry_point("transform_prompt")
    g.add_edge("transform_prompt", "sanitize_prompt")
    g.add_edge("sanitize_prompt", END)
    return g.compile()
