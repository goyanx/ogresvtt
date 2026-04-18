TOOL_DEFINITIONS = [
    # ------------------------------------------------------------------
    # Query tools — executed inside the sidecar, results fed back to LLM
    # ------------------------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "list_tokens",
            "description": (
                "Query the current tokens on the board. "
                "Returns id, label, type (player/npc), position, size, hp, and flags. "
                "Call this when you need to confirm token IDs or check who is on the map."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filter": {
                        "type": "string",
                        "enum": ["all", "player", "npc"],
                        "description": "Which tokens to return. Defaults to 'all'.",
                    }
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
QUERY_TOOLS = {"list_tokens"}
