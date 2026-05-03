from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, conint


class RollDiceArgs(BaseModel):
    expression: str = Field(min_length=1)
    advantage: bool = False
    disadvantage: bool = False


class ResolveAttackVsAcArgs(BaseModel):
    attack_total: int
    target_ac: int
    natural_roll: int | None = Field(default=None, ge=1, le=20)
    crit_threshold: int = Field(default=20, ge=2, le=20)
    auto_miss_on_1: bool = True
    auto_crit_on_threshold: bool = True


class ResolveDamageArgs(BaseModel):
    base_damage: conint(ge=0)
    flat_modifier: int = 0
    damage_type: str | None = None
    save_outcome: Literal["none", "success", "failure"] = "none"
    save_effect: Literal["none", "half", "negates"] = "none"
    target_vulnerabilities: list[str] = Field(default_factory=list)
    target_resistances: list[str] = Field(default_factory=list)
    target_immunities: list[str] = Field(default_factory=list)
    target_traits_json: str | None = None
    minimum_damage: conint(ge=0) | None = None


class RollInitiativeArgs(BaseModel):
    token_ids: list[int] = Field(min_length=1)


class UpdateHpArgs(BaseModel):
    token_id: int
    hp: int


class ApplyDamageArgs(BaseModel):
    token_id: int
    amount: conint(ge=0)
    mode: Literal["damage", "healing"] = "damage"
