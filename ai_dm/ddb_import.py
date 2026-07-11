"""
Import a D&D Beyond character into the campaign database.

Uses the public character-service JSON endpoint, which works for any
character whose privacy is set to Public on dndbeyond.com. No login,
cookies, or scraping involved — the player imports their own character.

Populates: camp_characters, camp_character_stats, camp_resources,
camp_inventory_items, camp_inventory_currency. Appearance and personality
traits are stored in camp_characters.notes so they also feed narration
and image-generation context.
"""
from __future__ import annotations

import json
import logging
import re

import httpx

from ai_dm.db import get_conn

logger = logging.getLogger("ai_dm")

CHARACTER_URL = "https://character-service.dndbeyond.com/character/v5/character/{id}"

USER_AGENT = "OgresVTT-AI-DM/1.0 (personal character import)"

ABILITY_IDS = {
    1: "strength",
    2: "dexterity",
    3: "constitution",
    4: "intelligence",
    5: "wisdom",
    6: "charisma",
}

ABILITY_COLUMNS = {
    "strength": "str_score",
    "dexterity": "dex_score",
    "constitution": "con_score",
    "intelligence": "int_score",
    "wisdom": "wis_score",
    "charisma": "cha_score",
}

ALIGNMENTS = {
    1: "Lawful Good", 2: "Neutral Good", 3: "Chaotic Good",
    4: "Lawful Neutral", 5: "True Neutral", 6: "Chaotic Neutral",
    7: "Lawful Evil", 8: "Neutral Evil", 9: "Chaotic Evil",
}


def extract_character_id(ref: str) -> int | None:
    """Accepts a raw numeric id or a dndbeyond.com character URL."""
    text = (ref or "").strip()
    if text.isdigit():
        return int(text)
    match = re.search(r"characters/(\d+)", text)
    return int(match.group(1)) if match else None


async def fetch_character(character_id: int) -> dict:
    """Fetches the character JSON. Raises httpx.HTTPStatusError on failure
    (403/404 usually means the character is not set to Public)."""
    url = CHARACTER_URL.format(id=character_id)
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(url, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        payload = resp.json()
    return payload.get("data") or {}


def _all_modifiers(data: dict) -> list[dict]:
    mods = data.get("modifiers") or {}
    out: list[dict] = []
    for group in mods.values():
        if isinstance(group, list):
            out.extend(m for m in group if isinstance(m, dict))
    return out


def _ability_scores(data: dict) -> dict[str, int]:
    base = {ABILITY_IDS[s["id"]]: s.get("value") or 10
            for s in data.get("stats") or [] if s.get("id") in ABILITY_IDS}
    bonus = {ABILITY_IDS[s["id"]]: s.get("value") or 0
             for s in data.get("bonusStats") or [] if s.get("id") in ABILITY_IDS}
    override = {ABILITY_IDS[s["id"]]: s.get("value")
                for s in data.get("overrideStats") or [] if s.get("id") in ABILITY_IDS}

    modifier_bonus = {name: 0 for name in ABILITY_IDS.values()}
    for mod in _all_modifiers(data):
        if mod.get("type") != "bonus":
            continue
        sub = mod.get("subType") or ""
        if sub.endswith("-score"):
            ability = sub[: -len("-score")]
            if ability in modifier_bonus and isinstance(mod.get("value"), int):
                modifier_bonus[ability] += mod["value"]

    scores: dict[str, int] = {}
    for name in ABILITY_IDS.values():
        if override.get(name):
            scores[name] = override[name]
        else:
            scores[name] = (base.get(name) or 10) + (bonus.get(name) or 0) + modifier_bonus[name]
    return scores


def _mod(score: int) -> int:
    return (score - 10) // 2


def _has_proficiency(data: dict, skill: str) -> bool:
    return any(
        mod.get("type") == "proficiency" and mod.get("subType") == skill
        for mod in _all_modifiers(data)
    )


def map_character(data: dict, is_player: bool = True) -> dict:
    """Maps DDB character JSON to rows for the camp_* tables. Best-effort:
    anything ambiguous is left NULL rather than guessed."""
    ddb_id = data.get("id")
    classes = data.get("classes") or []
    level = sum(c.get("level") or 0 for c in classes) or None
    class_names = " / ".join(
        (c.get("definition") or {}).get("name") or "?" for c in classes
    ) or None
    subclass = None
    if classes:
        sub_def = classes[0].get("subclassDefinition") or {}
        subclass = sub_def.get("name")

    scores = _ability_scores(data)
    con_mod = _mod(scores.get("constitution", 10))
    wis_mod = _mod(scores.get("wisdom", 10))

    override_hp = data.get("overrideHitPoints")
    base_hp = data.get("baseHitPoints") or 0
    bonus_hp = data.get("bonusHitPoints") or 0
    hp_max = override_hp if override_hp else base_hp + bonus_hp + (level or 0) * con_mod
    hp_current = max(0, hp_max - (data.get("removedHitPoints") or 0))

    prof_bonus = 2 + ((level or 1) - 1) // 4
    passive_perception = 10 + wis_mod + (
        prof_bonus if _has_proficiency(data, "perception") else 0
    )

    race = (data.get("race") or {}).get("fullName")
    speeds = ((data.get("race") or {}).get("weightSpeeds") or {}).get("normal") or {}
    walk = speeds.get("walk")

    background = ((data.get("background") or {}).get("definition") or {}).get("name")

    slots = {}
    for slot in data.get("spellSlots") or []:
        lvl, available = slot.get("level"), slot.get("available")
        if lvl and available:
            slots[str(lvl)] = available

    inventory = []
    for item in data.get("inventory") or []:
        name = (item.get("definition") or {}).get("name")
        if not name:
            continue
        inventory.append({
            "item_name": name,
            "quantity": item.get("quantity") or 1,
            "equipped_slot": "equipped" if item.get("equipped") else None,
        })

    currencies = data.get("currencies") or {}

    traits = data.get("traits") or {}
    decorations = data.get("decorations") or {}
    avatar = decorations.get("avatarUrl") or data.get("avatarUrl") or ""
    note_lines = [f"Imported from D&D Beyond (character id {ddb_id})."]
    if avatar:
        note_lines.append(f"Avatar: {avatar}")
    for key, label in (("appearance", "Appearance"),
                       ("personalityTraits", "Personality"),
                       ("ideals", "Ideals"),
                       ("bonds", "Bonds"),
                       ("flaws", "Flaws")):
        value = (traits.get(key) or "").strip()
        if value:
            note_lines.append(f"{label}: {value}")

    return {
        "external_id": f"ddb:{ddb_id}",
        "name": data.get("name") or f"DDB character {ddb_id}",
        "is_player": 1 if is_player else 0,
        "race": race,
        "class_name": class_names,
        "subclass": subclass,
        "background": background,
        "level": level,
        "alignment": ALIGNMENTS.get(data.get("alignmentId")),
        "notes": "\n".join(note_lines),
        "avatar_url": avatar,
        "stats": {
            "proficiency_bonus": prof_bonus,
            **{ABILITY_COLUMNS[name]: score for name, score in scores.items()},
            "passive_perception": passive_perception,
            "speeds_json": json.dumps({"walk": walk}) if walk else None,
        },
        "resources": {
            "hp_current": hp_current,
            "hp_max": hp_max,
            "hp_temp": data.get("temporaryHitPoints") or 0,
            "spell_slots_json": json.dumps(slots) if slots else None,
        },
        "inventory": inventory,
        "currency": {k: currencies.get(k) or 0 for k in ("cp", "sp", "ep", "gp", "pp")},
    }


def upsert_character(mapped: dict) -> dict:
    """Writes the mapped character into the campaign DB, replacing stats,
    resources, inventory, and currency. Returns an import summary."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM camp_characters WHERE external_id=?",
            (mapped["external_id"],),
        ).fetchone()
        if row is None:
            # Same name imported manually earlier — adopt that row.
            row = conn.execute(
                "SELECT id FROM camp_characters WHERE lower(name)=lower(?) LIMIT 1",
                (mapped["name"],),
            ).fetchone()

        fields = ("external_id", "name", "is_player", "race", "class_name",
                  "subclass", "background", "level", "alignment", "notes")
        values = [mapped[f] for f in fields]
        if row:
            cid = row["id"]
            assignments = ", ".join(f"{f}=?" for f in fields)
            conn.execute(
                f"UPDATE camp_characters SET {assignments} WHERE id=?",
                (*values, cid),
            )
            created = False
        else:
            cursor = conn.execute(
                f"INSERT INTO camp_characters ({', '.join(fields)}) "
                f"VALUES ({', '.join('?' for _ in fields)})",
                values,
            )
            cid = cursor.lastrowid
            created = True

        stats = mapped["stats"]
        stat_fields = ("proficiency_bonus", "str_score", "dex_score", "con_score",
                       "int_score", "wis_score", "cha_score",
                       "passive_perception", "speeds_json")
        conn.execute(
            "INSERT OR REPLACE INTO camp_character_stats "
            f"(character_id, {', '.join(stat_fields)}) "
            f"VALUES (?, {', '.join('?' for _ in stat_fields)})",
            (cid, *[stats.get(f) for f in stat_fields]),
        )

        res = mapped["resources"]
        conn.execute(
            "INSERT OR REPLACE INTO camp_resources "
            "(character_id, hp_current, hp_max, hp_temp, spell_slots_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (cid, res["hp_current"], res["hp_max"], res["hp_temp"],
             res["spell_slots_json"]),
        )

        conn.execute("DELETE FROM camp_inventory_items WHERE character_id=?", (cid,))
        for item in mapped["inventory"]:
            conn.execute(
                "INSERT INTO camp_inventory_items "
                "(character_id, item_name, quantity, equipped_slot) "
                "VALUES (?, ?, ?, ?)",
                (cid, item["item_name"], item["quantity"], item["equipped_slot"]),
            )

        cur = mapped["currency"]
        conn.execute(
            "INSERT OR REPLACE INTO camp_inventory_currency "
            "(character_id, cp, sp, ep, gp, pp) VALUES (?, ?, ?, ?, ?, ?)",
            (cid, cur["cp"], cur["sp"], cur["ep"], cur["gp"], cur["pp"]),
        )
        conn.commit()

    logger.info(
        "ddb import %s character_id=%s name=%r items=%s",
        "created" if created else "updated", cid, mapped["name"],
        len(mapped["inventory"]),
    )
    return {
        "created": created,
        "character_id": cid,
        "name": mapped["name"],
        "class_name": mapped["class_name"],
        "level": mapped["level"],
        "hp": f"{mapped['resources']['hp_current']}/{mapped['resources']['hp_max']}",
        "inventory_items": len(mapped["inventory"]),
        "avatar_url": mapped["avatar_url"],
    }
