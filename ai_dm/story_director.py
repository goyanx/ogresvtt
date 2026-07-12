"""
Background story director for the beat harness.

Between turns — never blocking one — the director reviews the beat ledger
and recent play to answer a single question: is the story still *pointed*
somewhere, or is the player drifting with no active goal? Its output is a
short "director's note" stored in beat_directions and surfaced inside the
per-turn STORY BEATS block until it expires.

CPU-friendly by construction:
- runs at most once every AI_DM_DIRECTOR_EVERY_TURNS DM turns (default 5)
  AND at most once every AI_DM_DIRECTOR_MIN_SECONDS seconds (default 300)
- scheduled with asyncio.create_task after the turn response is sent, so
  the player never waits on it
- one small LLM call, no tools, low token budget
- disable entirely with AI_DM_DIRECTOR_ENABLED=false
"""
from __future__ import annotations

import json
import logging
import os
import re
import time

from ai_dm.db import get_conn
from ai_dm.story_beats import list_beats

logger = logging.getLogger("ai_dm")

LAST_TURN_KEY = "director_last_turn"
LAST_TS_KEY = "director_last_ts"

_running = False


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off")


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(os.getenv(name, default)))
    except (TypeError, ValueError):
        return default


def _meta(conn, key: str) -> int:
    row = conn.execute("SELECT value FROM beat_meta WHERE key=?", (key,)).fetchone()
    return int(row["value"]) if row else 0


def _set_meta(conn, key: str, value: int) -> None:
    conn.execute(
        "INSERT INTO beat_meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def should_run(turn: int) -> bool:
    """True when a director pass is due. Never raises."""
    if _running or turn <= 0:
        return False
    if not _env_flag("AI_DM_DIRECTOR_ENABLED", True):
        return False
    every = _env_int("AI_DM_DIRECTOR_EVERY_TURNS", 5, minimum=1)
    min_secs = _env_int("AI_DM_DIRECTOR_MIN_SECONDS", 300)
    try:
        with get_conn() as conn:
            last_turn = _meta(conn, LAST_TURN_KEY)
            last_ts = _meta(conn, LAST_TS_KEY)
    except Exception:
        logger.exception("director should_run failed")
        return False
    if turn - last_turn < every:
        return False
    if time.time() - last_ts < min_secs:
        return False
    return True


DIRECTOR_PROMPT = """You are the story DIRECTOR for a solo tabletop campaign, reviewing
the game between turns. You are not narrating — you are steering.

Your one question: is the story pointed somewhere the player can feel, or are
they drifting with no active goal?

Consider:
- Is any open promise being neglected while the player wanders?
- Does the player currently have a clear, felt objective? If not, which
  promise should be steered into their path, or what concrete hook/complication
  should redirect them?
- Is a ripe promise being stalled when it should pay off?
- Would a new pressure (deadline, rival, consequence of earlier choices)
  restore momentum without railroading?

SCENARIO:
{scenario}

BEAT LEDGER:
{ledger}

RECENT PLAY (latest last):
{recent}

Respond with JSON only, in English:
{{"direction": "1-3 imperative sentences telling the DM where to steer the next few turns",
  "spotlight_beat_id": <open beat id to prioritize, or null>,
  "reasoning": "one short internal sentence on why"}}
"""


def _extract_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _ledger_summary() -> str:
    with get_conn() as conn:
        data = list_beats(conn, {"status": "all"})
    lines = []
    for beat in data["beats"][:12]:
        lines.append(
            f"- [{beat['beat_id']}] {beat['title']} ({beat['status']}, {beat['tension']}, "
            f"progress {beat['progress_count']}, last movement turn {beat['last_progress_turn']})"
        )
        lines.append(f"  promise: {beat['promise'][:160]}")
        if beat["recent_progress"]:
            lines.append(f"  latest: {beat['recent_progress'][0]['note'][:160]}")
    return "\n".join(lines) or "(empty ledger)"


def _recent_play(history: list[dict], limit: int = 8) -> str:
    lines = []
    for msg in (history or [])[-limit:]:
        content = (msg.get("content") or "").strip()
        if content:
            lines.append(f"{msg.get('role', '?')}: {content[:220]}")
    return "\n".join(lines) or "(no recent messages)"


async def run_director(llm_call, scenario: str, history: list[dict], turn: int) -> None:
    """One background director pass. Never raises; never blocks a turn
    (schedule with asyncio.create_task)."""
    global _running
    if _running:
        return
    _running = True
    try:
        # Stamp first so overlapping turns can't double-schedule.
        with get_conn() as conn:
            _set_meta(conn, LAST_TURN_KEY, turn)
            _set_meta(conn, LAST_TS_KEY, int(time.time()))
            conn.commit()

        prompt = DIRECTOR_PROMPT.format(
            scenario=(scenario or "(none)")[:800],
            ledger=_ledger_summary(),
            recent=_recent_play(history),
        )
        response = await llm_call([{"role": "user", "content": prompt}], tools=[])
        content = response["choices"][0]["message"]["content"] or ""
        data = _extract_json(content)
        direction = (data.get("direction") or "").strip()
        if not direction:
            logger.info("director turn=%s produced no direction", turn)
            return

        spotlight = data.get("spotlight_beat_id")
        if not isinstance(spotlight, int):
            spotlight = None
        every = _env_int("AI_DM_DIRECTOR_EVERY_TURNS", 5, minimum=1)
        expires = turn + 2 * every
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO beat_directions "
                "(direction, reasoning, spotlight_beat_id, created_turn, expires_turn) "
                "VALUES (?, ?, ?, ?, ?)",
                (direction[:600], (data.get("reasoning") or "").strip()[:300] or None,
                 spotlight, turn, expires),
            )
            # Keep the table tidy — only recent notes matter.
            conn.execute(
                "DELETE FROM beat_directions WHERE id NOT IN "
                "(SELECT id FROM beat_directions ORDER BY id DESC LIMIT 10)"
            )
            conn.commit()
        logger.info("director turn=%s direction=%r spotlight=%s expires_turn=%s",
                    turn, direction[:120], spotlight, expires)
    except Exception:
        logger.exception("director pass failed (turn=%s)", turn)
    finally:
        _running = False
