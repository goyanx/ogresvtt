from typing import Any, TypedDict


class DMState(TypedDict):
    scenario: str
    game_state: str
    history: list[dict]
    plan: str
    tool_calls: list[dict]
    validation_errors: list[str]
    retry_count: int
    narration: str
