from typing import Any, TypedDict


class DMState(TypedDict):
    system_prompt: str
    scenario: str
    game_state: str
    history: list[dict]
    plan: str
    tool_calls: list[dict]
    validation_errors: list[str]
    retry_count: int
    narration: str
    combat_mode: bool
    response_mode: str
    response_mode_reason: str
    latest_player_message: str
    character_context: str
