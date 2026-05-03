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
from pydantic import ValidationError

from ai_dm.state import DMState
from ai_dm.schemas_tool_args import (
    ApplyDamageArgs,
    ResolveAttackVsAcArgs,
    ResolveDamageArgs,
    RollDiceArgs,
    RollInitiativeArgs,
    UpdateHpArgs,
)

# These tools must never target a player-flagged token
PLAYER_PROTECTED = {"move_token", "remove_token"}

VALID_DIRECTIONS = {
    "north", "south", "east", "west",
    "northeast", "northwest", "southeast", "southwest",
}
MAX_RETRIES = 2
SCHEMA_VALIDATORS = {
    "roll_dice": RollDiceArgs,
    "resolve_attack_vs_ac": ResolveAttackVsAcArgs,
    "resolve_damage": ResolveDamageArgs,
    "roll_initiative": RollInitiativeArgs,
    "update_hp": UpdateHpArgs,
    "apply_damage": ApplyDamageArgs,
}


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
    errors = list(state.get("validation_errors", []))
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

        model = SCHEMA_VALIDATORS.get(name)
        if model is not None:
            try:
                model.model_validate(args)
            except ValidationError as exc:
                msg = "; ".join(
                    f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors()
                )
                errors.append(f"{name}: schema validation failed ({msg})")
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

        if name == "move_player_token":
            direction = args.get("direction")
            if direction not in VALID_DIRECTIONS:
                errors.append(f"move_player_token: invalid direction {direction!r}")
            tid = args.get("token_id")
            if tid is not None and tid not in known_ids:
                errors.append(f"move_player_token: token_id {tid} does not exist on board")

    return {**state, "validation_errors": errors}
