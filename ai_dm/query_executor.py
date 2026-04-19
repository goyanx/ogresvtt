"""
Executes query tools locally inside the sidecar by parsing the game_state
string — no extra LLM call, no round-trip to the browser.

Supported query tools:
  list_tokens(filter="all"|"player"|"npc")
"""
import json
import logging
import re

logger = logging.getLogger(__name__)


def _parse_tokens(game_state: str) -> list[dict]:
    """Parse the PLAYER TOKENS and NPC/MONSTER TOKENS sections from game_state."""
    tokens = []

    player_block = re.search(
        r"PLAYER TOKENS.*?:\n(.*?)(?=\nNPC/MONSTER TOKENS|\nINITIATIVE|\Z)",
        game_state, re.DOTALL
    )
    npc_block = re.search(
        r"NPC/MONSTER TOKENS.*?:\n(.*?)(?=\nINITIATIVE|\Z)",
        game_state, re.DOTALL
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
                    token["x"] = int(coords[0].strip())
                    token["y"] = int(coords[1].strip())

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

    if player_block:
        tokens.extend(parse_block(player_block.group(1), "player"))
    if npc_block:
        tokens.extend(parse_block(npc_block.group(1), "npc"))
    return tokens


def execute_query_tool(tool_name: str, arguments: dict, game_state: str) -> str:
    """
    Execute a query tool and return a JSON string suitable for a tool-result message.
    """
    if tool_name == "list_tokens":
        filter_type = arguments.get("filter", "all")
        all_tokens = _parse_tokens(game_state)
        logger.info(
            "query_tool list_tokens filter=%s total_tokens=%s",
            filter_type,
            len(all_tokens),
        )
        if filter_type == "player":
            result = [t for t in all_tokens if t["type"] == "player"]
        elif filter_type == "npc":
            result = [t for t in all_tokens if t["type"] == "npc"]
        else:
            result = all_tokens
        return json.dumps({"tokens": result, "count": len(result)}, indent=2)

    logger.warning("query_tool unknown tool_name=%s", tool_name)
    return json.dumps({"error": f"Unknown query tool: {tool_name}"})
