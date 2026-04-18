TOOL_DEFINITIONS = [
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
            "name": "advance_turn",
            "description": "Advance the initiative tracker to the next combatant's turn.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]
