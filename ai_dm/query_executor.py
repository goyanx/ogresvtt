"""
Executes query tools locally inside the sidecar.
Includes:
- Board-state queries from serialized game_state
- SQLite-backed RAG / campaign memory operations
"""
from __future__ import annotations

import json
import math
import random
import re
from typing import Any

from ai_dm.db import get_conn


def _safe_int(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(round(value))
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return int(s)
        except ValueError:
            try:
                return int(round(float(s)))
            except ValueError:
                return None
    return None


def _safe_float(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _bool_to_int(value):
    if value is None:
        return None
    return 1 if bool(value) else 0


def _parse_json_text(value: Any, default: Any):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return default


def _normalize_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = re.split(r"[,\n;]+", value)
        return [p.strip().lower() for p in parts if p.strip()]
    if isinstance(value, list):
        out = []
        for item in value:
            if isinstance(item, str) and item.strip():
                out.append(item.strip().lower())
        return out
    return []


def _parse_dice_expression(expression: str) -> list[dict]:
    clean = (expression or "").strip().lower().replace(" ", "")
    if not clean:
        raise ValueError("expression is required")
    if clean[0] not in "+-":
        clean = "+" + clean
    tokens = re.findall(r"[+-](?:\d*d\d+|\d+)", clean)
    if not tokens or "".join(tokens) != clean:
        raise ValueError(f"invalid dice expression: {expression!r}")

    terms = []
    for tok in tokens:
        sign = -1 if tok[0] == "-" else 1
        body = tok[1:]
        if "d" in body:
            count_s, sides_s = body.split("d", 1)
            count = int(count_s) if count_s else 1
            sides = int(sides_s)
            if count <= 0 or count > 200:
                raise ValueError(f"invalid dice count: {count}")
            if sides <= 1 or sides > 1000:
                raise ValueError(f"invalid dice sides: {sides}")
            terms.append({"kind": "dice", "sign": sign, "count": count, "sides": sides})
        else:
            value = int(body)
            terms.append({"kind": "flat", "sign": sign, "value": value})
    return terms


def _roll_dice_expression(args: dict) -> dict:
    expression = args.get("expression")
    if not isinstance(expression, str) or not expression.strip():
        return {"error": "expression is required"}
    try:
        terms = _parse_dice_expression(expression)
    except ValueError as exc:
        return {"error": str(exc)}

    advantage = bool(args.get("advantage"))
    disadvantage = bool(args.get("disadvantage"))
    if advantage and disadvantage:
        advantage = False
        disadvantage = False

    dice_terms = [t for t in terms if t["kind"] == "dice"]
    can_adv = (
        len(dice_terms) == 1
        and dice_terms[0]["count"] == 1
        and dice_terms[0]["sides"] == 20
    )

    breakdown = []
    total = 0
    natural_roll = None

    for term in terms:
        if term["kind"] == "flat":
            signed = term["sign"] * term["value"]
            total += signed
            breakdown.append(
                {
                    "type": "flat",
                    "value": term["value"],
                    "sign": term["sign"],
                    "contribution": signed,
                }
            )
            continue

        if can_adv and (advantage or disadvantage):
            r1 = random.randint(1, 20)
            r2 = random.randint(1, 20)
            picked = max(r1, r2) if advantage else min(r1, r2)
            natural_roll = picked if term["sign"] > 0 else None
            subtotal = term["sign"] * picked
            total += subtotal
            breakdown.append(
                {
                    "type": "dice",
                    "count": 1,
                    "sides": 20,
                    "rolls": [r1, r2],
                    "pick": picked,
                    "mode": "advantage" if advantage else "disadvantage",
                    "sign": term["sign"],
                    "contribution": subtotal,
                }
            )
            continue

        rolls = [random.randint(1, term["sides"]) for _ in range(term["count"])]
        if term["sides"] == 20 and term["count"] == 1 and term["sign"] > 0:
            natural_roll = rolls[0]
        subtotal_raw = sum(rolls)
        subtotal = term["sign"] * subtotal_raw
        total += subtotal
        breakdown.append(
            {
                "type": "dice",
                "count": term["count"],
                "sides": term["sides"],
                "rolls": rolls,
                "sign": term["sign"],
                "contribution": subtotal,
            }
        )

    return {
        "expression": expression,
        "total": total,
        "natural_roll": natural_roll,
        "used_advantage": can_adv and advantage,
        "used_disadvantage": can_adv and disadvantage,
        "breakdown": breakdown,
    }


def _resolve_attack_vs_ac(args: dict) -> dict:
    attack_total = _safe_int(args.get("attack_total"))
    target_ac = _safe_int(args.get("target_ac"))
    natural_roll = _safe_int(args.get("natural_roll"))
    crit_threshold = _safe_int(args.get("crit_threshold")) or 20
    auto_miss_on_1 = True if args.get("auto_miss_on_1") is None else bool(args.get("auto_miss_on_1"))
    auto_crit_on_threshold = (
        True if args.get("auto_crit_on_threshold") is None else bool(args.get("auto_crit_on_threshold"))
    )

    if attack_total is None or target_ac is None:
        return {"error": "attack_total and target_ac are required integers"}

    hit = attack_total >= target_ac
    critical = False
    reason = "attack_total_vs_ac"

    if natural_roll is not None:
        if auto_miss_on_1 and natural_roll == 1:
            hit = False
            critical = False
            reason = "natural_1_auto_miss"
        elif auto_crit_on_threshold and natural_roll >= crit_threshold:
            hit = True
            critical = True
            reason = f"natural_{natural_roll}_critical"

    return {
        "attack_total": attack_total,
        "target_ac": target_ac,
        "natural_roll": natural_roll,
        "hit": hit,
        "critical": critical,
        "margin": attack_total - target_ac,
        "reason": reason,
    }


def _resolve_damage(args: dict) -> dict:
    base_damage = _safe_int(args.get("base_damage"))
    flat_modifier = _safe_int(args.get("flat_modifier")) or 0
    damage_type = (args.get("damage_type") or "").strip().lower()
    save_outcome = (args.get("save_outcome") or "none").strip().lower()
    save_effect = (args.get("save_effect") or "none").strip().lower()
    minimum_damage = _safe_int(args.get("minimum_damage"))

    if base_damage is None:
        return {"error": "base_damage is required"}

    vulnerabilities = _normalize_str_list(args.get("target_vulnerabilities"))
    resistances = _normalize_str_list(args.get("target_resistances"))
    immunities = _normalize_str_list(args.get("target_immunities"))

    traits_raw = args.get("target_traits_json")
    traits = _parse_json_text(traits_raw, {}) if traits_raw else {}
    if isinstance(traits, dict):
        vulnerabilities = sorted(set(vulnerabilities + _normalize_str_list(traits.get("vulnerabilities"))))
        resistances = sorted(set(resistances + _normalize_str_list(traits.get("resistances"))))
        immunities = sorted(set(immunities + _normalize_str_list(traits.get("immunities"))))

    raw_damage = max(0, base_damage + flat_modifier)
    after_save = raw_damage

    if save_outcome == "success":
        if save_effect == "negates":
            after_save = 0
        elif save_effect == "half":
            after_save = after_save // 2

    trait_applied = "none"
    final_damage = after_save

    if damage_type and damage_type in immunities:
        final_damage = 0
        trait_applied = "immunity"
    elif damage_type and damage_type in resistances:
        final_damage = final_damage // 2
        trait_applied = "resistance"
    elif damage_type and damage_type in vulnerabilities:
        final_damage = final_damage * 2
        trait_applied = "vulnerability"

    if minimum_damage is not None and final_damage > 0:
        final_damage = max(final_damage, minimum_damage)

    return {
        "base_damage": base_damage,
        "flat_modifier": flat_modifier,
        "raw_damage": raw_damage,
        "save_outcome": save_outcome,
        "save_effect": save_effect,
        "after_save": after_save,
        "damage_type": damage_type or None,
        "traits": {
            "vulnerabilities": vulnerabilities,
            "resistances": resistances,
            "immunities": immunities,
        },
        "trait_applied": trait_applied,
        "final_damage": final_damage,
    }


def _parse_tokens(game_state: str) -> list[dict]:
    """Parse PLAYER TOKENS and NPC/MONSTER TOKENS from serialized game_state."""
    tokens = []

    player_block = re.search(
        r"PLAYER TOKENS.*?:\n(.*?)(?=\nNPC/MONSTER TOKENS|\nINITIATIVE|\Z)",
        game_state,
        re.DOTALL,
    )
    npc_block = re.search(
        r"NPC/MONSTER TOKENS.*?:\n(.*?)(?=\nINITIATIVE|\Z)",
        game_state,
        re.DOTALL,
    )
    initiative_block = re.search(
        r"INITIATIVE TRACKER:\n(.*?)(?=\nROUND:|\Z)",
        game_state,
        re.DOTALL,
    )

    def parse_block(text: str, token_type: str) -> list[dict]:
        results = []
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("- "):
                continue
            token: dict = {"type": token_type}

            m = re.search(r"id:\s*(\d+)", line)
            if m:
                token["id"] = int(m.group(1))

            m = re.search(r'label:\s*"([^"]*)"', line)
            if m:
                token["label"] = m.group(1)

            m = re.search(r"pos:\s*\(([^)]+)\)", line)
            if m:
                coords = m.group(1).split(",")
                if len(coords) == 2:
                    x = _safe_int(coords[0])
                    y = _safe_int(coords[1])
                    if x is not None and y is not None:
                        token["x"] = x
                        token["y"] = y

            m = re.search(r"size:\s*(\d+)ft", line)
            if m:
                token["size_ft"] = int(m.group(1))

            m = re.search(r"hp:\s*(\d+)", line)
            if m:
                token["hp"] = int(m.group(1))

            flags = re.search(r"flags:\s*\[([^\]]+)\]", line)
            if flags:
                token["flags"] = [f.strip() for f in flags.group(1).split(",")]

            if "id" in token:
                results.append(token)
        return results

    def parse_initiative_hp(text: str) -> dict[int, int]:
        hp_by_id: dict[int, int] = {}
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("- "):
                continue
            token_id_match = re.search(r"id:\s*(\d+)", line)
            hp_match = re.search(r"hp:\s*(\d+)", line)
            if token_id_match and hp_match:
                hp_by_id[int(token_id_match.group(1))] = int(hp_match.group(1))
        return hp_by_id

    if player_block:
        tokens.extend(parse_block(player_block.group(1), "player"))
    if npc_block:
        tokens.extend(parse_block(npc_block.group(1), "npc"))
    if initiative_block:
        hp_by_id = parse_initiative_hp(initiative_block.group(1))
        if hp_by_id:
            for token in tokens:
                token_id = token.get("id")
                if token_id in hp_by_id:
                    token["hp"] = hp_by_id[token_id]
    return tokens


def _row_dict(row) -> dict:
    return dict(row) if row is not None else {}


def _resolve_character_id(conn, name: str | None) -> int | None:
    if not name:
        return None
    row = conn.execute(
        "SELECT id FROM camp_characters WHERE lower(name) = lower(?) LIMIT 1", (name,)
    ).fetchone()
    return row["id"] if row else None


def _upsert_character(conn, args: dict) -> dict:
    name = (args.get("name") or "").strip()
    if not name:
        return {"error": "name is required"}

    external_id = args.get("external_id")
    is_player = 1 if args.get("is_player") else 0

    row = None
    if external_id:
        row = conn.execute(
            "SELECT id FROM camp_characters WHERE external_id = ? LIMIT 1", (external_id,)
        ).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT id FROM camp_characters WHERE lower(name) = lower(?) LIMIT 1", (name,)
        ).fetchone()

    fields = {
        "name": name,
        "external_id": external_id,
        "is_player": is_player,
        "race": args.get("race"),
        "class_name": args.get("class_name"),
        "subclass": args.get("subclass"),
        "background": args.get("background"),
        "level": args.get("level"),
        "alignment": args.get("alignment"),
    }

    if row:
        cid = row["id"]
        conn.execute(
            """
            UPDATE camp_characters
            SET name=?, external_id=coalesce(?, external_id), is_player=?, race=?, class_name=?,
                subclass=?, background=?, level=?, alignment=?
            WHERE id=?
            """,
            (
                fields["name"],
                fields["external_id"],
                fields["is_player"],
                fields["race"],
                fields["class_name"],
                fields["subclass"],
                fields["background"],
                fields["level"],
                fields["alignment"],
                cid,
            ),
        )
    else:
        cur = conn.execute(
            """
            INSERT INTO camp_characters
            (external_id, name, is_player, race, class_name, subclass, background, level, alignment)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fields["external_id"],
                fields["name"],
                fields["is_player"],
                fields["race"],
                fields["class_name"],
                fields["subclass"],
                fields["background"],
                fields["level"],
                fields["alignment"],
            ),
        )
        cid = cur.lastrowid

    return {
        "character_id": cid,
        "name": name,
        "is_player": bool(is_player),
        "status": "upserted",
    }


def _upsert_character_stats(conn, args: dict) -> dict:
    cid = _resolve_character_id(conn, args.get("name"))
    if cid is None:
        return {"error": f"character not found: {args.get('name')!r}"}

    conn.execute(
        """
        INSERT INTO camp_character_stats
        (character_id, proficiency_bonus, str_score, dex_score, con_score, int_score, wis_score, cha_score,
         passive_perception, passive_investigation, passive_insight, speeds_json, saves_json, skills_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(character_id) DO UPDATE SET
          proficiency_bonus=excluded.proficiency_bonus,
          str_score=excluded.str_score,
          dex_score=excluded.dex_score,
          con_score=excluded.con_score,
          int_score=excluded.int_score,
          wis_score=excluded.wis_score,
          cha_score=excluded.cha_score,
          passive_perception=excluded.passive_perception,
          passive_investigation=excluded.passive_investigation,
          passive_insight=excluded.passive_insight,
          speeds_json=excluded.speeds_json,
          saves_json=excluded.saves_json,
          skills_json=excluded.skills_json
        """,
        (
            cid,
            args.get("proficiency_bonus"),
            args.get("str_score"),
            args.get("dex_score"),
            args.get("con_score"),
            args.get("int_score"),
            args.get("wis_score"),
            args.get("cha_score"),
            args.get("passive_perception"),
            args.get("passive_investigation"),
            args.get("passive_insight"),
            args.get("speeds_json"),
            args.get("saves_json"),
            args.get("skills_json"),
        ),
    )
    return {"character_id": cid, "status": "stats_updated"}


def _upsert_character_resources(conn, args: dict) -> dict:
    cid = _resolve_character_id(conn, args.get("name"))
    if cid is None:
        return {"error": f"character not found: {args.get('name')!r}"}

    conn.execute(
        """
        INSERT INTO camp_resources
        (character_id, hp_current, hp_max, hp_temp, hit_dice_json, spell_slots_json, exhaustion_level,
         death_successes, death_failures)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(character_id) DO UPDATE SET
          hp_current=excluded.hp_current,
          hp_max=excluded.hp_max,
          hp_temp=excluded.hp_temp,
          hit_dice_json=excluded.hit_dice_json,
          spell_slots_json=excluded.spell_slots_json,
          exhaustion_level=excluded.exhaustion_level,
          death_successes=excluded.death_successes,
          death_failures=excluded.death_failures
        """,
        (
            cid,
            args.get("hp_current"),
            args.get("hp_max"),
            args.get("hp_temp"),
            args.get("hit_dice_json"),
            args.get("spell_slots_json"),
            args.get("exhaustion_level"),
            args.get("death_successes"),
            args.get("death_failures"),
        ),
    )
    return {"character_id": cid, "status": "resources_updated"}


def _get_character_sheet(conn, name: str) -> dict:
    row = conn.execute(
        "SELECT * FROM camp_characters WHERE lower(name)=lower(?) LIMIT 1", (name,)
    ).fetchone()
    if not row:
        return {"error": f"character not found: {name!r}"}

    cid = row["id"]
    stats = conn.execute(
        "SELECT * FROM camp_character_stats WHERE character_id=?", (cid,)
    ).fetchone()
    resources = conn.execute(
        "SELECT * FROM camp_resources WHERE character_id=?", (cid,)
    ).fetchone()
    inventory = conn.execute(
        "SELECT * FROM camp_inventory_items WHERE character_id=? ORDER BY item_name", (cid,)
    ).fetchall()
    personality = conn.execute(
        "SELECT * FROM npc_personality WHERE npc_character_id=?", (cid,)
    ).fetchone()
    opinions = conn.execute(
        "SELECT * FROM npc_opinions WHERE npc_character_id=? ORDER BY updated_at DESC LIMIT 20", (cid,)
    ).fetchall()
    relations = conn.execute(
        "SELECT * FROM npc_relationships WHERE npc_character_id=? ORDER BY id DESC LIMIT 20", (cid,)
    ).fetchall()

    return {
        "character": _row_dict(row),
        "stats": _row_dict(stats),
        "resources": _row_dict(resources),
        "inventory": [dict(r) for r in inventory],
        "npc_personality": _row_dict(personality),
        "npc_opinions": [dict(r) for r in opinions],
        "npc_relationships": [dict(r) for r in relations],
    }


def _add_inventory_item(conn, args: dict) -> dict:
    cid = _resolve_character_id(conn, args.get("name"))
    if cid is None:
        return {"error": f"character not found: {args.get('name')!r}"}

    item_name = (args.get("item_name") or "").strip()
    if not item_name:
        return {"error": "item_name is required"}
    qty = args.get("quantity")
    qty = 1 if qty is None else int(qty)

    row = conn.execute(
        "SELECT id, quantity FROM camp_inventory_items WHERE character_id=? AND lower(item_name)=lower(?) LIMIT 1",
        (cid, item_name),
    ).fetchone()

    if row:
        new_qty = row["quantity"] + qty
        conn.execute(
            """
            UPDATE camp_inventory_items
            SET quantity=?,
                equipped_slot=coalesce(?, equipped_slot),
                is_attuned=coalesce(?, is_attuned),
                properties_json=coalesce(?, properties_json),
                notes=coalesce(?, notes)
            WHERE id=?
            """,
            (
                new_qty,
                args.get("equipped_slot"),
                1 if args.get("is_attuned") else 0 if args.get("is_attuned") is not None else None,
                args.get("properties_json"),
                args.get("notes"),
                row["id"],
            ),
        )
        iid = row["id"]
    else:
        cur = conn.execute(
            """
            INSERT INTO camp_inventory_items
            (character_id, item_name, quantity, equipped_slot, is_attuned, properties_json, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cid,
                item_name,
                qty,
                args.get("equipped_slot"),
                1 if args.get("is_attuned") else 0,
                args.get("properties_json"),
                args.get("notes"),
            ),
        )
        iid = cur.lastrowid

    return {"character_id": cid, "inventory_item_id": iid, "status": "inventory_updated"}


def _set_npc_personality(conn, args: dict) -> dict:
    name = args.get("name")
    cid = _resolve_character_id(conn, name)
    if cid is None:
        up = _upsert_character(conn, {"name": name, "is_player": False})
        if "error" in up:
            return up
        cid = up["character_id"]

    conn.execute(
        """
        INSERT INTO npc_personality
        (npc_character_id, personality_traits_json, ideals_json, bonds_json, flaws_json, mannerisms_json)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(npc_character_id) DO UPDATE SET
          personality_traits_json=excluded.personality_traits_json,
          ideals_json=excluded.ideals_json,
          bonds_json=excluded.bonds_json,
          flaws_json=excluded.flaws_json,
          mannerisms_json=excluded.mannerisms_json
        """,
        (
            cid,
            args.get("personality_traits_json"),
            args.get("ideals_json"),
            args.get("bonds_json"),
            args.get("flaws_json"),
            args.get("mannerisms_json"),
        ),
    )
    return {"npc_character_id": cid, "status": "npc_personality_updated"}


def _set_npc_opinion(conn, args: dict) -> dict:
    npc_id = _resolve_character_id(conn, args.get("npc_name"))
    if npc_id is None:
        return {"error": f"npc not found: {args.get('npc_name')!r}"}

    conn.execute(
        """
        INSERT INTO npc_opinions
        (npc_character_id, target_type, target_ref, attitude, trust_score, fear_score, respect_score,
         affection_score, reason_text)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            npc_id,
            args.get("target_type"),
            args.get("target_ref"),
            args.get("attitude"),
            args.get("trust_score"),
            args.get("fear_score"),
            args.get("respect_score"),
            args.get("affection_score"),
            args.get("reason_text"),
        ),
    )
    return {"npc_character_id": npc_id, "status": "npc_opinion_recorded"}


def _set_npc_relationship(conn, args: dict) -> dict:
    npc_id = _resolve_character_id(conn, args.get("npc_name"))
    other_id = _resolve_character_id(conn, args.get("other_name"))
    if npc_id is None:
        return {"error": f"npc not found: {args.get('npc_name')!r}"}
    if other_id is None:
        return {"error": f"other character not found: {args.get('other_name')!r}"}

    conn.execute(
        """
        INSERT INTO npc_relationships
        (npc_character_id, other_character_id, relationship_type, strength_score, visibility, notes)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            npc_id,
            other_id,
            args.get("relationship_type"),
            args.get("strength_score"),
            args.get("visibility"),
            args.get("notes"),
        ),
    )
    return {"npc_character_id": npc_id, "other_character_id": other_id, "status": "npc_relationship_recorded"}


def _record_combat_event(conn, args: dict) -> dict:
    actor_id = _resolve_character_id(conn, args.get("actor_name"))
    target_id = _resolve_character_id(conn, args.get("target_name"))
    payload = args.get("payload_json")
    if isinstance(payload, (dict, list)):
        payload = json.dumps(payload)

    cur = conn.execute(
        """
        INSERT INTO comb_events
        (encounter_id, event_type, actor_character_id, target_character_id, payload_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            args.get("encounter_id"),
            args.get("event_type"),
            actor_id,
            target_id,
            payload,
        ),
    )
    return {"event_id": cur.lastrowid, "status": "combat_event_recorded"}


def _get_or_create_scene(conn, scene_external_id: str) -> int:
    row = conn.execute(
        "SELECT id FROM map_scenes WHERE external_scene_id=? LIMIT 1", (scene_external_id,)
    ).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO map_scenes (external_scene_id, name) VALUES (?, ?)",
        (scene_external_id, scene_external_id),
    )
    return cur.lastrowid


def _upsert_map_config(conn, args: dict) -> dict:
    ext = (args.get("scene_external_id") or "").strip()
    if not ext:
        return {"error": "scene_external_id is required"}

    scene_id = _get_or_create_scene(conn, ext)
    conn.execute(
        """
        UPDATE map_scenes
        SET name=coalesce(?, name),
            map_file_path=coalesce(?, map_file_path),
            map_file_name=coalesce(?, map_file_name),
            image_hash=coalesce(?, image_hash),
            width=coalesce(?, width),
            height=coalesce(?, height),
            grid_size=coalesce(?, grid_size),
            offset_x=coalesce(?, offset_x),
            offset_y=coalesce(?, offset_y),
            show_grid=coalesce(?, show_grid),
            dark_mode=coalesce(?, dark_mode),
            grid_align=coalesce(?, grid_align),
            show_object_outlines=coalesce(?, show_object_outlines),
            lighting=coalesce(?, lighting),
            config_json=coalesce(?, config_json),
            updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (
            args.get("name"),
            args.get("map_file_path"),
            args.get("map_file_name"),
            args.get("image_hash"),
            _safe_int(args.get("width")),
            _safe_int(args.get("height")),
            _safe_int(args.get("grid_size")),
            _safe_float(args.get("offset_x")),
            _safe_float(args.get("offset_y")),
            _bool_to_int(args.get("show_grid")),
            _bool_to_int(args.get("dark_mode")),
            _bool_to_int(args.get("grid_align")),
            _bool_to_int(args.get("show_object_outlines")),
            args.get("lighting"),
            args.get("config_json"),
            scene_id,
        ),
    )

    row = conn.execute("SELECT * FROM map_scenes WHERE id=?", (scene_id,)).fetchone()
    return {"status": "map_config_upserted", "scene": dict(row)}


def _list_map_configs(conn, args: dict) -> dict:
    limit = _safe_int(args.get("limit")) or 50
    limit = max(1, min(limit, 200))
    rows = conn.execute(
        "SELECT * FROM map_scenes ORDER BY updated_at DESC, id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return {"count": len(rows), "maps": [dict(r) for r in rows]}


def _upsert_token_position(conn, args: dict) -> dict:
    scene_id = _get_or_create_scene(conn, args["scene_external_id"])
    char_id = _resolve_character_id(conn, args.get("character_name"))
    token_id = str(args.get("token_id"))
    x = _safe_float(args.get("x"))
    y = _safe_float(args.get("y"))
    if x is None or y is None:
        return {"error": "x and y are required numeric values"}

    conn.execute(
        """
        INSERT INTO map_token_positions (scene_id, token_id, character_id, x, y)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(scene_id, token_id) DO UPDATE SET
          character_id=excluded.character_id,
          x=excluded.x,
          y=excluded.y,
          updated_at=CURRENT_TIMESTAMP
        """,
        (scene_id, token_id, char_id, x, y),
    )
    return {"scene_id": scene_id, "token_id": token_id, "x": x, "y": y, "status": "token_position_upserted"}


def _define_map_region(conn, args: dict) -> dict:
    scene_id = _get_or_create_scene(conn, args["scene_external_id"])
    region_key = args.get("region_key")
    region_name = args.get("region_name") or region_key
    geometry_json = args.get("geometry_json")
    tags_json = args.get("tags_json")

    row = conn.execute(
        "SELECT id FROM map_regions WHERE scene_id=? AND region_key=? LIMIT 1", (scene_id, region_key)
    ).fetchone()
    if row:
        rid = row["id"]
        conn.execute(
            """
            UPDATE map_regions
            SET region_name=?, geometry_json=?, tags_json=?
            WHERE id=?
            """,
            (region_name, geometry_json, tags_json, rid),
        )
    else:
        cur = conn.execute(
            """
            INSERT INTO map_regions (scene_id, region_key, region_name, geometry_json, tags_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (scene_id, region_key, region_name, geometry_json, tags_json),
        )
        rid = cur.lastrowid

    return {"scene_id": scene_id, "region_id": rid, "region_key": region_key, "status": "region_upserted"}


def _define_trigger(conn, args: dict) -> dict:
    key = args.get("trigger_key")
    row = conn.execute(
        "SELECT id FROM trg_definitions WHERE trigger_key=? LIMIT 1", (key,)
    ).fetchone()
    is_enabled = args.get("is_enabled")
    is_enabled = 1 if is_enabled is None else (1 if is_enabled else 0)

    if row:
        tid = row["id"]
        conn.execute(
            """
            UPDATE trg_definitions
            SET name=?, event_type=?, condition_json=?, action_json=?, is_enabled=?
            WHERE id=?
            """,
            (
                args.get("name"),
                args.get("event_type"),
                args.get("condition_json"),
                args.get("action_json"),
                is_enabled,
                tid,
            ),
        )
    else:
        cur = conn.execute(
            """
            INSERT INTO trg_definitions (trigger_key, name, event_type, condition_json, action_json, is_enabled)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                key,
                args.get("name"),
                args.get("event_type"),
                args.get("condition_json"),
                args.get("action_json"),
                is_enabled,
            ),
        )
        tid = cur.lastrowid

    return {"trigger_id": tid, "trigger_key": key, "status": "trigger_upserted"}


def _point_in_polygon(x: float, y: float, points: list[list[float]]) -> bool:
    inside = False
    n = len(points)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = points[i]
        xj, yj = points[j]
        intersects = ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi
        )
        if intersects:
            inside = not inside
        j = i
    return inside


def _point_in_geometry(x: float, y: float, geometry: dict) -> bool:
    kind = (geometry.get("type") or "").lower()
    if kind == "bbox":
        x1 = _safe_float(geometry.get("x1"))
        y1 = _safe_float(geometry.get("y1"))
        x2 = _safe_float(geometry.get("x2"))
        y2 = _safe_float(geometry.get("y2"))
        if None in {x1, y1, x2, y2}:
            return False
        return min(x1, x2) <= x <= max(x1, x2) and min(y1, y2) <= y <= max(y1, y2)
    if kind == "circle":
        cx = _safe_float(geometry.get("x"))
        cy = _safe_float(geometry.get("y"))
        r = _safe_float(geometry.get("r"))
        if None in {cx, cy, r}:
            return False
        return math.hypot(x - cx, y - cy) <= r
    if kind == "polygon":
        points = geometry.get("points") or []
        try:
            parsed = [[float(px), float(py)] for px, py in points]
        except Exception:
            return False
        return _point_in_polygon(x, y, parsed)
    return False


def _evaluate_triggers(conn, args: dict) -> dict:
    scene_external_id = args.get("scene_external_id")
    event_type = args.get("event_type")
    token_id = args.get("token_id")
    character_name = args.get("character_name")
    x = _safe_float(args.get("x"))
    y = _safe_float(args.get("y"))

    if not scene_external_id or not event_type:
        return {"error": "scene_external_id and event_type are required"}

    scene = conn.execute(
        "SELECT id FROM map_scenes WHERE external_scene_id=? LIMIT 1", (scene_external_id,)
    ).fetchone()
    if not scene:
        return {"fired": [], "count": 0, "note": "scene not found"}
    scene_id = scene["id"]

    if (x is None or y is None) and token_id is not None:
        pos = conn.execute(
            "SELECT x, y FROM map_token_positions WHERE scene_id=? AND token_id=? LIMIT 1",
            (scene_id, str(token_id)),
        ).fetchone()
        if pos:
            x, y = pos["x"], pos["y"]

    rows = conn.execute(
        """
        SELECT t.id AS trigger_id, t.trigger_key, t.name, t.condition_json, t.action_json
        FROM trg_definitions t
        WHERE t.is_enabled=1 AND lower(t.event_type)=lower(?)
        ORDER BY t.id
        """,
        (event_type,),
    ).fetchall()

    fired = []
    for row in rows:
        cond = _parse_json_text(row["condition_json"], {})
        if not isinstance(cond, dict):
            continue

        expected_token = cond.get("token_id")
        if expected_token is not None and str(expected_token) != str(token_id):
            continue

        expected_name = cond.get("character_name")
        if expected_name and character_name and expected_name.lower() != character_name.lower():
            continue

        region_key = cond.get("region_key")
        if region_key:
            if x is None or y is None:
                continue
            reg = conn.execute(
                "SELECT geometry_json FROM map_regions WHERE scene_id=? AND region_key=? LIMIT 1",
                (scene_id, region_key),
            ).fetchone()
            if not reg:
                continue
            geometry = _parse_json_text(reg["geometry_json"], {})
            if not _point_in_geometry(float(x), float(y), geometry):
                continue

        action = _parse_json_text(row["action_json"], {"raw": row["action_json"]})
        f = {
            "trigger_id": row["trigger_id"],
            "trigger_key": row["trigger_key"],
            "name": row["name"],
            "action": action,
        }
        fired.append(f)

        conn.execute(
            "INSERT INTO trg_firings (trigger_id, result_json) VALUES (?, ?)",
            (row["trigger_id"], json.dumps({"scene_external_id": scene_external_id, "action": action})),
        )

    return {"fired": fired, "count": len(fired)}


def _retrieve_rules(conn, args: dict) -> dict:
    query = (args.get("query") or "").strip()
    if not query:
        return {"error": "query is required"}
    top_k = _safe_int(args.get("top_k")) or 5
    top_k = max(1, min(top_k, 20))
    entity_type = (args.get("entity_type") or "").strip().lower()

    if entity_type:
        rows = conn.execute(
            """
            SELECT c.id, c.text, c.citation, s.heading, d.title AS document_title, src.title AS source_title
            FROM comp_chunks_fts f
            JOIN comp_chunks c ON c.id = f.rowid
            JOIN comp_sections s ON s.id = c.section_id
            JOIN comp_documents d ON d.id = s.document_id
            JOIN comp_sources src ON src.id = d.source_id
            WHERE comp_chunks_fts MATCH ?
              AND EXISTS (
                SELECT 1 FROM comp_entities e
                WHERE e.section_id = s.id AND lower(e.entity_type)=lower(?)
              )
            ORDER BY bm25(comp_chunks_fts)
            LIMIT ?
            """,
            (query, entity_type, top_k),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT c.id, c.text, c.citation, s.heading, d.title AS document_title, src.title AS source_title
            FROM comp_chunks_fts f
            JOIN comp_chunks c ON c.id = f.rowid
            JOIN comp_sections s ON s.id = c.section_id
            JOIN comp_documents d ON d.id = s.document_id
            JOIN comp_sources src ON src.id = d.source_id
            WHERE comp_chunks_fts MATCH ?
            ORDER BY bm25(comp_chunks_fts)
            LIMIT ?
            """,
            (query, top_k),
        ).fetchall()

    return {
        "query": query,
        "count": len(rows),
        "results": [dict(r) for r in rows],
    }


def _get_monster_stats(conn, args: dict) -> dict:
    name = (args.get("name") or "").strip()
    if not name:
        return {"error": "name is required"}

    row = conn.execute(
        """
        SELECT e.id AS entity_id, e.name, e.raw_json,
               m.size, m.creature_type, m.alignment, m.armor_class, m.hit_points_avg,
               m.hit_dice, m.speed_json, m.str_score, m.dex_score, m.con_score,
               m.int_score, m.wis_score, m.cha_score, m.challenge_rating,
               m.proficiency_bonus, m.saves_json, m.skills_json, m.senses_json,
               m.languages_json, m.traits_json, m.actions_json, m.reactions_json,
               m.legendary_actions_json
        FROM comp_entities e
        LEFT JOIN comp_monsters m ON m.entity_id = e.id
        WHERE lower(e.entity_type)='monster' AND lower(e.name)=lower(?)
        LIMIT 1
        """,
        (name,),
    ).fetchone()

    if not row:
        return {"error": f"monster not found: {name!r}"}
    return dict(row)


def _save_ruling(conn, args: dict) -> dict:
    topic = (args.get("topic") or "").strip()
    decision = (args.get("decision") or "").strip()
    if not topic or not decision:
        return {"error": "topic and decision are required"}

    cur = conn.execute(
        "INSERT INTO dm_rulings (session_ref, topic, decision, citation) VALUES (?, ?, ?, ?)",
        (args.get("session_ref"), topic, decision, args.get("citation")),
    )
    return {"ruling_id": cur.lastrowid, "status": "saved"}


def _get_rulings(conn, args: dict) -> dict:
    limit = _safe_int(args.get("limit")) or 10
    limit = max(1, min(limit, 50))
    session_ref = args.get("session_ref")
    topic = args.get("topic")

    sql = "SELECT * FROM dm_rulings WHERE 1=1"
    params = []
    if session_ref:
        sql += " AND session_ref = ?"
        params.append(session_ref)
    if topic:
        sql += " AND lower(topic) LIKE lower(?)"
        params.append(f"%{topic}%")
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, tuple(params)).fetchall()
    return {"count": len(rows), "rulings": [dict(r) for r in rows]}


def execute_query_tool(tool_name: str, arguments: dict, game_state: str) -> str:
    """Execute a query tool and return JSON string for tool-result messages."""
    arguments = arguments or {}

    if tool_name == "list_tokens":
        filter_type = arguments.get("filter", "all")
        all_tokens = _parse_tokens(game_state)
        if filter_type == "player":
            result = [t for t in all_tokens if t["type"] == "player"]
        elif filter_type == "npc":
            result = [t for t in all_tokens if t["type"] == "npc"]
        else:
            result = all_tokens
        return json.dumps({"tokens": result, "count": len(result)}, indent=2)

    try:
        with get_conn() as conn:
            if tool_name == "retrieve_rules":
                result = _retrieve_rules(conn, arguments)
            elif tool_name == "get_monster_stats":
                result = _get_monster_stats(conn, arguments)
            elif tool_name == "roll_dice":
                result = _roll_dice_expression(arguments)
            elif tool_name == "resolve_attack_vs_ac":
                result = _resolve_attack_vs_ac(arguments)
            elif tool_name == "resolve_damage":
                result = _resolve_damage(arguments)
            elif tool_name == "upsert_character":
                result = _upsert_character(conn, arguments)
            elif tool_name == "set_character_stats":
                result = _upsert_character_stats(conn, arguments)
            elif tool_name == "set_character_resources":
                result = _upsert_character_resources(conn, arguments)
            elif tool_name == "get_character_sheet":
                result = _get_character_sheet(conn, arguments.get("name", ""))
            elif tool_name == "add_inventory_item":
                result = _add_inventory_item(conn, arguments)
            elif tool_name == "set_npc_personality":
                result = _set_npc_personality(conn, arguments)
            elif tool_name == "set_npc_opinion":
                result = _set_npc_opinion(conn, arguments)
            elif tool_name == "set_npc_relationship":
                result = _set_npc_relationship(conn, arguments)
            elif tool_name == "record_combat_event":
                result = _record_combat_event(conn, arguments)
            elif tool_name == "upsert_map_config":
                result = _upsert_map_config(conn, arguments)
            elif tool_name == "list_map_configs":
                result = _list_map_configs(conn, arguments)
            elif tool_name == "upsert_token_position":
                result = _upsert_token_position(conn, arguments)
            elif tool_name == "define_map_region":
                result = _define_map_region(conn, arguments)
            elif tool_name == "define_trigger":
                result = _define_trigger(conn, arguments)
            elif tool_name == "evaluate_triggers":
                result = _evaluate_triggers(conn, arguments)
            elif tool_name == "save_ruling":
                result = _save_ruling(conn, arguments)
            elif tool_name == "get_rulings":
                result = _get_rulings(conn, arguments)
            else:
                result = {"error": f"Unknown query tool: {tool_name}"}

            conn.commit()
            return json.dumps(result, indent=2)
    except Exception as exc:
        return json.dumps({"error": str(exc), "tool": tool_name}, indent=2)
