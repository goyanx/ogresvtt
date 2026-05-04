from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, conint


class NarrateArgs(BaseModel):
    text: str = Field(min_length=1, max_length=600)


class MoveTokenArgs(BaseModel):
    token_id: int
    x: conint(ge=0)
    y: conint(ge=0)


class SpawnTokenArgs(BaseModel):
    label: str = Field(min_length=1)
    x: conint(ge=0)
    y: conint(ge=0)
    size: int | None = None


class RemoveTokenArgs(BaseModel):
    token_id: int


class MovePlayerTokenArgs(BaseModel):
    token_id: int
    direction: Literal[
        "north",
        "south",
        "east",
        "west",
        "northeast",
        "northwest",
        "southeast",
        "southwest",
    ]
    squares: conint(ge=1) | None = 1


class AdvanceTurnArgs(BaseModel):
    pass


class FunctionCallPayload(BaseModel):
    name: str
    arguments: str = "{}"


class ToolCallPayload(BaseModel):
    function: FunctionCallPayload


class CombatTurnToolCalls(BaseModel):
    tool_calls: list[ToolCallPayload] = Field(min_length=1)


ALLOWED_COMBAT_ACTION_TOOLS = {
    "narrate",
    "move_token",
    "spawn_token",
    "remove_token",
    "update_hp",
    "apply_damage",
    "move_player_token",
    "advance_turn",
}


ACTION_ARG_MODELS = {
    "narrate": NarrateArgs,
    "move_token": MoveTokenArgs,
    "spawn_token": SpawnTokenArgs,
    "remove_token": RemoveTokenArgs,
    "move_player_token": MovePlayerTokenArgs,
    "advance_turn": AdvanceTurnArgs,
}


def _fmt_validation_error(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors()
    )


def validate_combat_action_calls(
    action_calls: list[dict], *, requires_hp_application: bool
) -> list[str]:
    errors: list[str] = []
    try:
        envelope = CombatTurnToolCalls.model_validate({"tool_calls": action_calls})
    except ValidationError as exc:
        errors.append(f"combat: invalid tool call envelope ({_fmt_validation_error(exc)})")
        return errors

    names = [tc.function.name for tc in envelope.tool_calls]
    if names.count("narrate") != 1:
        errors.append("combat: exactly one narrate call is required")
    if names.count("advance_turn") != 1:
        errors.append("combat: advance_turn must be called exactly once per resolved turn")
    if names and names[-1] != "advance_turn":
        errors.append("combat: advance_turn must be the final tool call after turn resolution")
    if "advance_turn" in names and "narrate" in names:
        if names.index("advance_turn") < names.index("narrate"):
            errors.append("combat: advance_turn should occur after narrate")

    if requires_hp_application:
        has_hp_apply = any(name in {"apply_damage", "update_hp"} for name in names)
        if not has_hp_apply:
            errors.append(
                "combat: resolve_damage produced positive damage but no HP update tool was called; "
                "add apply_damage (preferred) or update_hp before advance_turn"
            )

    for tc in envelope.tool_calls:
        fn_name = tc.function.name
        if fn_name not in ALLOWED_COMBAT_ACTION_TOOLS:
            errors.append(f"combat: unsupported action tool in combat turn: {fn_name}")
            continue

        raw = tc.function.arguments or "{}"
        try:
            args = json.loads(raw)
        except json.JSONDecodeError:
            errors.append(f"{fn_name}: invalid JSON arguments")
            continue

        if not isinstance(args, dict):
            errors.append(f"{fn_name}: arguments must decode to a JSON object")
            continue

        model = ACTION_ARG_MODELS.get(fn_name)
        if model is None:
            continue
        try:
            model.model_validate(args)
        except ValidationError as exc:
            errors.append(f"{fn_name}: schema validation failed ({_fmt_validation_error(exc)})")

    return errors
