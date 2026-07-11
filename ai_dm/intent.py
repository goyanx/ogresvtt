"""
Intent helpers for deciding response stance:
- npc: in-world roleplay delivery
- dm: out-of-character facilitator/information delivery
"""
from __future__ import annotations

import re


_TURN_BOILERPLATE_RE = re.compile(
    r"^\s*It is your turn\.\s*Review the game state and take appropriate actions\.\s*$",
    re.IGNORECASE,
)
_CHAT_PREFIX_RE = re.compile(r"^\s*Latest chat UI message from [^:]+:\s*", re.IGNORECASE)

_DM_INFO_PATTERNS = [
    re.compile(
        r"\b(show|list|check|tell|give|what(?:'s| is)|how much)\b[\s\w]{0,40}\b"
        r"(inventory|items?|gear|equipment|bag|backpack|spells?|spell slots?|gold|money|coins?|"
        r"currency|gp|sp|cp|pp|hp|hit points?|ac|stats?|abilities|sheet|character sheet|"
        r"rulings?|rules?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(my|our)\s+(inventory|items?|gear|equipment|spells?|spell slots?|gold|money|coins?|"
        r"currency|hp|hit points?|ac|stats?|character sheet)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(rec(ap|all)|summary|quest log|what happened|what do we know)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(ooc|out of character)\b", re.IGNORECASE),
]

_DM_RULES_PATTERNS = [
    re.compile(r"\b(how does|can i|what happens if|is it allowed)\b", re.IGNORECASE),
    re.compile(r"\b(rule|rules|ruling|mechanic|dc|advantage|disadvantage)\b", re.IGNORECASE),
]


def _normalize_user_text(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    text = _CHAT_PREFIX_RE.sub("", text)
    return text.strip()


def latest_player_message(history: list[dict]) -> str:
    for msg in reversed(history or []):
        if (msg or {}).get("role") != "user":
            continue
        text = _normalize_user_text((msg or {}).get("content", ""))
        if not text:
            continue
        if _TURN_BOILERPLATE_RE.match(text):
            continue
        return text
    return ""


def classify_response_mode(player_text: str) -> tuple[str, str]:
    text = (player_text or "").strip()
    if not text:
        return ("npc", "no explicit player chat message; default to in-world narration")

    if text.startswith("/"):
        return ("dm", "slash-style command indicates out-of-character request")

    for pattern in _DM_INFO_PATTERNS:
        if pattern.search(text):
            return ("dm", "player asked for out-of-character character/campaign info")

    lower_text = text.lower()
    if "?" in lower_text and any(p.search(lower_text) for p in _DM_RULES_PATTERNS):
        return ("dm", "player asked an out-of-character rules/mechanics question")

    return ("npc", "player message reads as in-world roleplay/action")
