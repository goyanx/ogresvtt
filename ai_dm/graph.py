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
import os
import re
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

_INIT_BLOCK_RE = re.compile(
    r"INITIATIVE TRACKER:\n(?P<body>.*?)(?:\n[A-Z][A-Z _]+:|\Z)",
    re.DOTALL,
)
_COMBAT_HINT_RE = re.compile(
    r"\b(combat|initiative|attack|attacks|spell|spells|reaction|reactions|damage|ac)\b",
    re.IGNORECASE,
)


def _is_combat_state(game_state: str) -> bool:
    text = game_state or ""
    if "INITIATIVE TRACKER:" not in text:
        return False
    m = _INIT_BLOCK_RE.search(text)
    if not m:
        return False
    body = m.group("body")
    entries = re.findall(r"^\s*-\s*id:\s*\d+", body, flags=re.MULTILINE)
    if len(entries) >= 2:
        return True
    round_m = re.search(r"ROUND:\s*(\d+)", body)
    if round_m and int(round_m.group(1)) > 0:
        return True
    return False

def _should_retry(state: DMState) -> str:
    if state["validation_errors"] and state["retry_count"] < MAX_RETRIES:
        return "reflect_retry"
    return END


def _route_planner(state: DMState) -> str:
    if not ENABLE_COMBAT_AGENT:
        return "plan_actions"
    if _is_combat_state(state.get("game_state", "")):
        return "plan_combat_actions"
    plan_text = state.get("plan", "") or ""
    if _COMBAT_HINT_RE.search(plan_text):
        return "plan_combat_actions"
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
