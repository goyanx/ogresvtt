"""
Validate node.
Checks tool calls for obvious errors before sending to the client:
- token IDs referenced must exist in game state
- player tokens must not be moved/removed
- coordinates should be positive integers
Populates validation_errors; the graph retries via reflect node if non-empty.
"""
import json
import re
from ai_dm.state import DMState

PLAYER_PROTECTED = {"move_token", "remove_token"}
MAX_RETRIES = 2


def _extract_token_ids(game_state: str) -> set[int]:
    return {int(m) for m in re.findall(r"id:\s*(\d+)", game_state)}


def _extract_player_ids(game_state: str) -> set[int]:
    player_section = re.search(
        r"PLAYER TOKENS.*?(?=NPC/MONSTER TOKENS|INITIATIVE|$)", game_state, re.DOTALL
    )
    if not player_section:
        return set()
    return {int(m) for m in re.findall(r"id:\s*(\d+)", player_section.group())}


def validate(state: DMState) -> DMState:
    errors = []
    known_ids = _extract_token_ids(state["game_state"])
    player_ids = _extract_player_ids(state["game_state"])

    for tc in state["tool_calls"]:
        fn = tc.get("function", {})
        name = fn.get("name", "")
        try:
            args = json.loads(fn.get("arguments", "{}"))
        except json.JSONDecodeError:
            errors.append(f"{name}: invalid JSON arguments")
            continue

        tid = args.get("token_id")
        if tid is not None:
            if tid not in known_ids:
                errors.append(f"{name}: token_id {tid} does not exist on board")
            if name in PLAYER_PROTECTED and tid in player_ids:
                errors.append(f"{name}: token_id {tid} is a player token — cannot modify")

        if name in {"move_token", "spawn_token"}:
            for coord in ("x", "y"):
                val = args.get(coord)
                if val is None or not isinstance(val, int) or val < 0:
                    errors.append(f"{name}: {coord} must be a non-negative integer, got {val!r}")

    return {**state, "validation_errors": errors}
