"""
Builds a compact character-sheet block injected into every DM turn.

The DM previously saw stats only when it chose to call get_character_sheet.
This module makes the campaign DB authoritative on every turn: party members
(is_player=1) are always included, and NPCs are included when a board token
label matches their name. The result is a short plain-text section the
assess/plan/plan_combat prompts embed directly.
"""
from __future__ import annotations

import json
import logging
import re

from ai_dm.db import get_conn

logger = logging.getLogger("ai_dm")

MAX_CHARS = 3500
MAX_CHARACTERS = 12

ABILITIES = (
    ("str_score", "STR"),
    ("dex_score", "DEX"),
    ("con_score", "CON"),
    ("int_score", "INT"),
    ("wis_score", "WIS"),
    ("cha_score", "CHA"),
)


def _mod(score) -> str:
    try:
        m = (int(score) - 10) // 2
    except (TypeError, ValueError):
        return "?"
    return f"+{m}" if m >= 0 else str(m)


def _norm(name: str) -> str:
    # Lowercase, drop trailing initiative suffixes like "Goblin 2".
    base = re.sub(r"\s+\d+$", "", (name or "").strip().lower())
    return re.sub(r"\s+", " ", base)


def _token_labels(game_state: str) -> set[str]:
    return {
        _norm(m)
        for m in re.findall(r'label:\s*"([^"]*)"', game_state or "")
        if m.strip()
    }


def _name_matches(char_name: str, labels: set[str]) -> bool:
    cname = _norm(char_name)
    if not cname:
        return False
    if cname in labels:
        return True
    # "Thorin" matches "Thorin Oakenshield" and vice versa.
    return any(
        label.startswith(cname + " ") or cname.startswith(label + " ")
        for label in labels
    )


def _fmt_json_compact(raw, limit: int = 90) -> str:
    if not raw:
        return ""
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return ""
    text = json.dumps(data, separators=(",", ":"))
    if text in ("{}", "[]", "null"):
        return ""
    return text[:limit]


def _format_character(conn, row) -> str:
    cid = row["id"]
    stats = conn.execute(
        "SELECT * FROM camp_character_stats WHERE character_id=?", (cid,)
    ).fetchone()
    res = conn.execute(
        "SELECT * FROM camp_resources WHERE character_id=?", (cid,)
    ).fetchone()
    conditions = conn.execute(
        "SELECT condition_name FROM camp_conditions WHERE character_id=?", (cid,)
    ).fetchall()
    items = conn.execute(
        "SELECT item_name, quantity FROM camp_inventory_items "
        "WHERE character_id=? ORDER BY equipped_slot IS NULL, item_name LIMIT 10",
        (cid,),
    ).fetchall()

    kind = "PC" if row["is_player"] else "NPC"
    klass = " ".join(
        str(x) for x in (row["class_name"], row["level"]) if x is not None
    )
    headline = ", ".join(x for x in (kind, klass or None, row["race"]) if x)
    lines = [f"- {row['name']} ({headline})"]

    if stats:
        scores = " ".join(
            f"{label} {stats[col]}({_mod(stats[col])})"
            for col, label in ABILITIES
            if stats[col] is not None
        )
        if scores:
            lines.append(f"  {scores}")
        extras = []
        if stats["proficiency_bonus"] is not None:
            extras.append(f"PB +{stats['proficiency_bonus']}")
        if stats["passive_perception"] is not None:
            extras.append(f"passive Perception {stats['passive_perception']}")
        speeds = _fmt_json_compact(stats["speeds_json"], 60)
        if speeds:
            extras.append(f"speed {speeds}")
        saves = _fmt_json_compact(stats["saves_json"], 90)
        if saves:
            extras.append(f"saves {saves}")
        if extras:
            lines.append("  " + " | ".join(extras))

    if res:
        hp_bits = []
        if res["hp_current"] is not None or res["hp_max"] is not None:
            hp_bits.append(f"HP {res['hp_current']}/{res['hp_max']}")
        if res["hp_temp"]:
            hp_bits.append(f"temp {res['hp_temp']}")
        slots = _fmt_json_compact(res["spell_slots_json"], 80)
        if slots:
            hp_bits.append(f"slots {slots}")
        if res["exhaustion_level"]:
            hp_bits.append(f"exhaustion {res['exhaustion_level']}")
        if hp_bits:
            lines.append("  " + " | ".join(hp_bits))

    if conditions:
        lines.append("  conditions: " + ", ".join(c["condition_name"] for c in conditions))

    if items:
        gear = ", ".join(
            f"{i['item_name']}" + (f" x{i['quantity']}" if i["quantity"] > 1 else "")
            for i in items
        )
        lines.append(f"  gear: {gear}")

    return "\n".join(lines)


def build_character_context(game_state: str) -> str:
    """Returns the character-sheet block for this turn, or "" when the
    campaign DB has nothing relevant. Never raises."""
    try:
        labels = _token_labels(game_state)
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM camp_characters ORDER BY is_player DESC, name"
            ).fetchall()
            selected = [
                row for row in rows
                if row["is_player"] or _name_matches(row["name"], labels)
            ][:MAX_CHARACTERS]
            if not selected:
                return ""
            blocks = [_format_character(conn, row) for row in selected]
        text = "\n".join(blocks)
        if len(text) > MAX_CHARS:
            text = text[:MAX_CHARS].rsplit("\n", 1)[0]
        return text
    except Exception:
        logger.exception("build_character_context failed")
        return ""
