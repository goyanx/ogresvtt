TOOL_DEFINITIONS = [
    # ------------------------------------------------------------------
    # Query/Memory tools — executed inside the sidecar
    # ------------------------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "list_tokens",
            "description": (
                "Query current board tokens from serialized game state. "
                "Returns id, label, type (player/npc), position, size, hp, flags."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filter": {
                        "type": "string",
                        "enum": ["all", "player", "npc"],
                        "description": "Which tokens to return. Defaults to all.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "retrieve_rules",
            "description": "RAG retrieval over ingested DnD manuals/compendium text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "top_k": {"type": "integer", "description": "default 5"},
                    "entity_type": {
                        "type": "string",
                        "description": "Optional filter: monster|rule|condition|technique|lore",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_monster_stats",
            "description": "Fetch structured monster stats from compendium tables.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "roll_dice",
            "description": (
                "Roll dice from an expression like '1d20+5', '2d6+3', or '4d8-2'. "
                "For d20 tests, advantage/disadvantage can be applied."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "Dice expression, e.g. 1d20+5"},
                    "advantage": {"type": "boolean", "description": "Apply advantage to a single d20 roll."},
                    "disadvantage": {"type": "boolean", "description": "Apply disadvantage to a single d20 roll."},
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resolve_attack_vs_ac",
            "description": (
                "Resolve hit/miss/critical against Armor Class from a rolled attack total. "
                "Supports natural-roll auto miss/crit behavior."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "attack_total": {"type": "integer"},
                    "target_ac": {"type": "integer"},
                    "natural_roll": {"type": "integer", "description": "Optional raw d20 face result (1-20)."},
                    "crit_threshold": {"type": "integer", "description": "Critical threshold, default 20."},
                    "auto_miss_on_1": {"type": "boolean", "description": "Natural 1 auto miss, default true."},
                    "auto_crit_on_threshold": {"type": "boolean", "description": "Natural threshold auto crit, default true."},
                },
                "required": ["attack_total", "target_ac"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resolve_damage",
            "description": (
                "Resolve final damage after save effects and target damage traits "
                "(vulnerabilities, resistances, immunities)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "base_damage": {"type": "integer"},
                    "flat_modifier": {"type": "integer"},
                    "damage_type": {"type": "string"},
                    "save_outcome": {"type": "string", "description": "none|success|failure"},
                    "save_effect": {"type": "string", "description": "none|half|negates"},
                    "target_vulnerabilities": {"type": "array", "items": {"type": "string"}},
                    "target_resistances": {"type": "array", "items": {"type": "string"}},
                    "target_immunities": {"type": "array", "items": {"type": "string"}},
                    "target_traits_json": {
                        "type": "string",
                        "description": "Optional JSON with vulnerabilities/resistances/immunities arrays.",
                    },
                    "minimum_damage": {"type": "integer", "description": "Optional minimum floor when damage > 0."},
                },
                "required": ["base_damage"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "upsert_character",
            "description": "Create or update a campaign character record (PC or NPC).",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "external_id": {"type": "string"},
                    "is_player": {"type": "boolean"},
                    "race": {"type": "string"},
                    "class_name": {"type": "string"},
                    "subclass": {"type": "string"},
                    "background": {"type": "string"},
                    "level": {"type": "integer"},
                    "alignment": {"type": "string"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_character_stats",
            "description": "Set core DnD ability/proficiency stats for a character.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "proficiency_bonus": {"type": "integer"},
                    "str_score": {"type": "integer"},
                    "dex_score": {"type": "integer"},
                    "con_score": {"type": "integer"},
                    "int_score": {"type": "integer"},
                    "wis_score": {"type": "integer"},
                    "cha_score": {"type": "integer"},
                    "passive_perception": {"type": "integer"},
                    "passive_investigation": {"type": "integer"},
                    "passive_insight": {"type": "integer"},
                    "speeds_json": {"type": "string"},
                    "saves_json": {"type": "string"},
                    "skills_json": {"type": "string"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_character_resources",
            "description": "Set HP/resources for a character (hp current/max/temp etc).",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "hp_current": {"type": "integer"},
                    "hp_max": {"type": "integer"},
                    "hp_temp": {"type": "integer"},
                    "hit_dice_json": {"type": "string"},
                    "spell_slots_json": {"type": "string"},
                    "exhaustion_level": {"type": "integer"},
                    "death_successes": {"type": "integer"},
                    "death_failures": {"type": "integer"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_character_sheet",
            "description": "Return merged character profile/stats/resources/inventory.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_inventory_item",
            "description": "Add/update item quantity for a character inventory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "item_name": {"type": "string"},
                    "quantity": {"type": "integer"},
                    "equipped_slot": {"type": "string"},
                    "is_attuned": {"type": "boolean"},
                    "properties_json": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["name", "item_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_npc_personality",
            "description": "Set NPC personality traits/ideals/bonds/flaws/mannerisms.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "personality_traits_json": {"type": "string"},
                    "ideals_json": {"type": "string"},
                    "bonds_json": {"type": "string"},
                    "flaws_json": {"type": "string"},
                    "mannerisms_json": {"type": "string"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_npc_opinion",
            "description": "Set/update NPC opinion toward target entity.",
            "parameters": {
                "type": "object",
                "properties": {
                    "npc_name": {"type": "string"},
                    "target_type": {"type": "string"},
                    "target_ref": {"type": "string"},
                    "attitude": {"type": "string"},
                    "trust_score": {"type": "integer"},
                    "fear_score": {"type": "integer"},
                    "respect_score": {"type": "integer"},
                    "affection_score": {"type": "integer"},
                    "reason_text": {"type": "string"},
                },
                "required": ["npc_name", "target_type", "target_ref"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_npc_relationship",
            "description": "Set/update relationship between two characters.",
            "parameters": {
                "type": "object",
                "properties": {
                    "npc_name": {"type": "string"},
                    "other_name": {"type": "string"},
                    "relationship_type": {"type": "string"},
                    "strength_score": {"type": "integer"},
                    "visibility": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["npc_name", "other_name", "relationship_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "record_combat_event",
            "description": "Append combat/event log entry for encounter history and trigger context.",
            "parameters": {
                "type": "object",
                "properties": {
                    "encounter_id": {"type": "integer"},
                    "event_type": {"type": "string"},
                    "actor_name": {"type": "string"},
                    "target_name": {"type": "string"},
                    "payload_json": {"type": "string"},
                },
                "required": ["event_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "upsert_map_config",
            "description": "Create/update map scene configuration including file path/name and display settings.",
            "parameters": {
                "type": "object",
                "properties": {
                    "scene_external_id": {"type": "string"},
                    "name": {"type": "string"},
                    "map_file_path": {"type": "string"},
                    "map_file_name": {"type": "string"},
                    "image_hash": {"type": "string"},
                    "width": {"type": "integer"},
                    "height": {"type": "integer"},
                    "grid_size": {"type": "integer"},
                    "offset_x": {"type": "number"},
                    "offset_y": {"type": "number"},
                    "show_grid": {"type": "boolean"},
                    "dark_mode": {"type": "boolean"},
                    "grid_align": {"type": "boolean"},
                    "show_object_outlines": {"type": "boolean"},
                    "lighting": {"type": "string"},
                    "config_json": {"type": "string"}
                },
                "required": ["scene_external_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_map_configs",
            "description": "List saved map configurations for DM map switching and trigger context.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer"}
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "upsert_token_position",
            "description": "Store token position for trigger evaluation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "scene_external_id": {"type": "string"},
                    "token_id": {"type": "string"},
                    "character_name": {"type": "string"},
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                },
                "required": ["scene_external_id", "token_id", "x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "define_map_region",
            "description": "Create/update scene region geometry for trigger conditions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "scene_external_id": {"type": "string"},
                    "region_key": {"type": "string"},
                    "region_name": {"type": "string"},
                    "geometry_json": {"type": "string"},
                    "tags_json": {"type": "string"},
                },
                "required": ["scene_external_id", "region_key", "geometry_json"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "define_trigger",
            "description": "Create/update trigger definitions for map/location events.",
            "parameters": {
                "type": "object",
                "properties": {
                    "trigger_key": {"type": "string"},
                    "name": {"type": "string"},
                    "event_type": {"type": "string"},
                    "condition_json": {"type": "string"},
                    "action_json": {"type": "string"},
                    "is_enabled": {"type": "boolean"},
                },
                "required": ["trigger_key", "name", "event_type", "condition_json", "action_json"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "evaluate_triggers",
            "description": "Evaluate triggers for a map event and return fired actions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "scene_external_id": {"type": "string"},
                    "event_type": {"type": "string"},
                    "token_id": {"type": "string"},
                    "character_name": {"type": "string"},
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                },
                "required": ["scene_external_id", "event_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_ruling",
            "description": "Persist a DM ruling for campaign consistency.",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_ref": {"type": "string"},
                    "topic": {"type": "string"},
                    "decision": {"type": "string"},
                    "citation": {"type": "string"},
                },
                "required": ["topic", "decision"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_rulings",
            "description": "Retrieve prior DM rulings by topic/session.",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_ref": {"type": "string"},
                    "topic": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": [],
            },
        },
    },

    # ------------------------------------------------------------------
    # Action tools — dispatched to the ClojureScript client
    # ------------------------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "show_map",
            "description": "Switch or show a map in the app using map config metadata.",
            "parameters": {
                "type": "object",
                "properties": {
                    "scene_external_id": {"type": "string"},
                    "name": {"type": "string"},
                    "map_file_path": {"type": "string"},
                    "map_file_name": {"type": "string"},
                    "image_hash": {"type": "string"},
                    "grid_size": {"type": "integer"},
                    "show_grid": {"type": "boolean"},
                    "dark_mode": {"type": "boolean"},
                    "grid_align": {"type": "boolean"},
                    "show_object_outlines": {"type": "boolean"},
                    "lighting": {"type": "string"}
                },
                "required": ["scene_external_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "narrate",
            "description": "Emit narration text visible to all players. Call this once per turn.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Narration text, under 100 words."}
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_token",
            "description": "Move an existing NPC/monster token to a new grid position.",
            "parameters": {
                "type": "object",
                "properties": {
                    "token_id": {"type": "integer"},
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                },
                "required": ["token_id", "x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "spawn_token",
            "description": "Place a new NPC or monster token on the scene.",
            "parameters": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "size": {"type": "integer", "description": "Diameter in feet (5/10/15/20)."},
                },
                "required": ["label", "x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_token",
            "description": "Remove a defeated or unnecessary token from the scene.",
            "parameters": {
                "type": "object",
                "properties": {"token_id": {"type": "integer"}},
                "required": ["token_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_hp",
            "description": "Set a token's current hit points.",
            "parameters": {
                "type": "object",
                "properties": {
                    "token_id": {"type": "integer"},
                    "hp": {"type": "integer"},
                },
                "required": ["token_id", "hp"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_damage",
            "description": (
                "Apply HP delta to a token: subtract damage or add healing. "
                "Use this after resolve_damage so you do not recalculate absolute HP manually."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "token_id": {"type": "integer"},
                    "amount": {"type": "integer", "description": "Non-negative HP amount to apply."},
                    "mode": {
                        "type": "string",
                        "enum": ["damage", "healing"],
                        "description": "damage subtracts HP; healing adds HP.",
                    },
                },
                "required": ["token_id", "amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "roll_initiative",
            "description": "Add tokens to the initiative tracker and roll for them.",
            "parameters": {
                "type": "object",
                "properties": {
                    "token_ids": {"type": "array", "items": {"type": "integer"}}
                },
                "required": ["token_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_player_token",
            "description": (
                "Move a player-controlled token by a number of squares in a compass direction. "
                "Use ONLY when the player explicitly says their character moves. "
                "Never use this on your own initiative."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "token_id": {"type": "integer"},
                    "direction": {
                        "type": "string",
                        "enum": [
                            "north", "south", "east", "west",
                            "northeast", "northwest", "southeast", "southwest",
                        ],
                    },
                    "squares": {
                        "type": "integer",
                        "description": "Number of grid squares to move. Defaults to 1.",
                    },
                },
                "required": ["token_id", "direction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "advance_turn",
            "description": "Advance the initiative tracker to the next combatant's turn.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


# Tools resolved inside the sidecar — never sent to the ClojureScript client.
QUERY_TOOLS = {
    "list_tokens",
    "retrieve_rules",
    "get_monster_stats",
    "roll_dice",
    "resolve_attack_vs_ac",
    "resolve_damage",
    "upsert_character",
    "set_character_stats",
    "set_character_resources",
    "get_character_sheet",
    "add_inventory_item",
    "set_npc_personality",
    "set_npc_opinion",
    "set_npc_relationship",
    "record_combat_event",
    "upsert_map_config",
    "list_map_configs",
    "upsert_token_position",
    "define_map_region",
    "define_trigger",
    "evaluate_triggers",
    "save_ruling",
    "get_rulings",
}
