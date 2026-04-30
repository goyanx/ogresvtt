"""
LangGraph StateGraph for the AI Dungeon Master.

Flow:
  assess_situation
       ↓
  plan_actions  (calls LLM with tools)
       ↓
  validate      (no LLM call — pure logic)
       ↓ errors?
    yes → reflect_retry → validate (up to MAX_RETRIES times)
    no  → END

The graph returns the final tool_calls list to the FastAPI handler,
which serialises them back to the ClojureScript client.
"""
import functools
import os
from langgraph.graph import StateGraph, END

from ai_dm.state import DMState
from ai_dm.nodes.assess import assess
from ai_dm.nodes.plan import plan
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


def _should_retry(state: DMState) -> str:
    if state["validation_errors"] and state["retry_count"] < MAX_RETRIES:
        return "reflect_retry"
    return END


def build_graph(llm_call):
    """
    llm_call: async callable(messages, tools) → OpenAI-compatible response dict.
    Inject the backend-specific function so the graph stays backend-agnostic.
    """
    bound_assess  = functools.partial(assess, llm_call=llm_call)
    bound_plan    = functools.partial(plan,   llm_call=llm_call)
    bound_reflect = functools.partial(reflect, llm_call=llm_call)

    g = StateGraph(DMState)
    g.add_node("assess_situation", bound_assess)
    g.add_node("plan_actions",     bound_plan)
    g.add_node("validate",         validate)
    g.add_node("reflect_retry",    bound_reflect)

    g.set_entry_point("assess_situation")
    g.add_edge("assess_situation", "plan_actions")
    g.add_edge("plan_actions",     "validate")
    g.add_conditional_edges("validate", _should_retry)
    g.add_edge("reflect_retry",    "validate")

    return g.compile()
