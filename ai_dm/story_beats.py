"""
Story beat harness for the DM loop, after Brandon Sanderson's
Promise / Progress / Payoff framework.

- A *promise* is a concrete narrative commitment the DM has made to the
  player: a villain to confront, a mystery to solve, a debt to collect,
  a relationship arc. Stored in beat_promises.
- *Progress* entries (beat_progress) are visible movement on a promise —
  the player must be able to feel the story advancing.
- A *payoff* resolves the promise ("surprising yet inevitable") and should
  seed the next promise.

Every /dm/turn increments a turn counter and injects a STORY BEATS block
into the planning prompts: the open promises, their progress, and
deterministic pacing directives (establish / advance / pay off / stop
promising). The DM maintains the ledger itself through the promise_beat,
progress_beat, payoff_beat, and list_beats query tools.
"""
from __future__ import annotations

import logging

from ai_dm.db import get_conn

logger = logging.getLogger("ai_dm")

TURN_KEY = "dm_turn"

MAX_OPEN_BEATS = 5
STALE_TURNS = 4
MAX_CONTEXT_CHARS = 2800

# Progress entries before a beat is considered ripe for payoff, by tension.
RIPE_THRESHOLD = {"minor": 2, "standard": 3, "major": 5}

VALID_TENSION = ("minor", "standard", "major")


# ---------------------------------------------------------------------------
# Turn counter
# ---------------------------------------------------------------------------

def increment_turn() -> int:
    """Bumps and returns the global DM turn number. Never raises."""
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO beat_meta (key, value) VALUES (?, 1) "
                "ON CONFLICT(key) DO UPDATE SET value = value + 1",
                (TURN_KEY,),
            )
            row = conn.execute(
                "SELECT value FROM beat_meta WHERE key=?", (TURN_KEY,)
            ).fetchone()
            conn.commit()
            return int(row["value"])
    except Exception:
        logger.exception("increment_turn failed")
        return 0


def current_turn(conn) -> int:
    row = conn.execute(
        "SELECT value FROM beat_meta WHERE key=?", (TURN_KEY,)
    ).fetchone()
    return int(row["value"]) if row else 0


# ---------------------------------------------------------------------------
# Tool operations (called from query_executor with an open connection)
# ---------------------------------------------------------------------------

def promise_beat(conn, args: dict) -> dict:
    title = (args.get("title") or "").strip()
    promise = (args.get("promise") or "").strip()
    if not title or not promise:
        return {"error": "title and promise are required"}

    open_count = conn.execute(
        "SELECT COUNT(*) AS n FROM beat_promises WHERE status='open'"
    ).fetchone()["n"]
    if open_count >= MAX_OPEN_BEATS:
        return {"error": f"too many open promises ({open_count}); "
                         "pay off or abandon one before promising more"}

    duplicate = conn.execute(
        "SELECT id FROM beat_promises WHERE status='open' AND lower(title)=lower(?)",
        (title,),
    ).fetchone()
    if duplicate:
        return {"error": f"an open promise titled {title!r} already exists "
                         f"(beat_id {duplicate['id']}); progress it instead"}

    tension = (args.get("tension") or "standard").strip().lower()
    if tension not in VALID_TENSION:
        tension = "standard"

    turn = current_turn(conn)
    cursor = conn.execute(
        "INSERT INTO beat_promises "
        "(title, promise, payoff_condition, subject, tension, created_turn) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (title, promise,
         (args.get("payoff_condition") or "").strip() or None,
         (args.get("subject") or "").strip() or None,
         tension, turn),
    )
    conn.commit()
    return {"ok": True, "beat_id": cursor.lastrowid, "title": title,
            "tension": tension, "turn": turn}


def _find_beat(conn, args: dict):
    beat_id = args.get("beat_id")
    if beat_id is not None:
        return conn.execute(
            "SELECT * FROM beat_promises WHERE id=?", (beat_id,)
        ).fetchone()
    title = (args.get("title") or "").strip()
    if title:
        return conn.execute(
            "SELECT * FROM beat_promises WHERE lower(title)=lower(?) "
            "ORDER BY status='open' DESC, id DESC LIMIT 1",
            (title,),
        ).fetchone()
    return None


def progress_beat(conn, args: dict) -> dict:
    note = (args.get("note") or "").strip()
    if not note:
        return {"error": "note is required — describe the visible movement"}
    beat = _find_beat(conn, args)
    if beat is None:
        return {"error": "beat not found; pass beat_id (or exact title) from list_beats"}
    if beat["status"] != "open":
        return {"error": f"beat {beat['id']} is {beat['status']}; only open promises can progress"}

    turn = current_turn(conn)
    conn.execute(
        "INSERT INTO beat_progress (beat_id, note, turn) VALUES (?, ?, ?)",
        (beat["id"], note, turn),
    )
    conn.execute(
        "UPDATE beat_promises SET progress_count = progress_count + 1, "
        "last_progress_turn = ?, updated_at = CURRENT_TIMESTAMP WHERE id=?",
        (turn, beat["id"]),
    )
    conn.commit()
    count = beat["progress_count"] + 1
    ripe = count >= RIPE_THRESHOLD.get(beat["tension"], 3)
    return {"ok": True, "beat_id": beat["id"], "title": beat["title"],
            "progress_count": count, "ripe_for_payoff": ripe}


def payoff_beat(conn, args: dict) -> dict:
    resolution = (args.get("resolution") or "").strip()
    if not resolution:
        return {"error": "resolution is required — describe how the promise was paid off"}
    beat = _find_beat(conn, args)
    if beat is None:
        return {"error": "beat not found; pass beat_id (or exact title) from list_beats"}
    if beat["status"] != "open":
        return {"error": f"beat {beat['id']} is already {beat['status']}"}

    status = "abandoned" if args.get("abandoned") else "paid_off"
    turn = current_turn(conn)
    conn.execute(
        "UPDATE beat_promises SET status=?, resolution=?, resolved_turn=?, "
        "updated_at = CURRENT_TIMESTAMP WHERE id=?",
        (status, resolution, turn, beat["id"]),
    )
    conn.commit()
    return {"ok": True, "beat_id": beat["id"], "title": beat["title"],
            "status": status,
            "reminder": "Seed the next promise soon — a paid-off story needs a new hook."}


def list_beats(conn, args: dict) -> dict:
    status = (args.get("status") or "open").strip().lower()
    if status == "all":
        rows = conn.execute(
            "SELECT * FROM beat_promises ORDER BY status='open' DESC, id"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM beat_promises WHERE status=? ORDER BY id", (status,)
        ).fetchall()
    beats = []
    for row in rows:
        notes = conn.execute(
            "SELECT note, turn FROM beat_progress WHERE beat_id=? ORDER BY id DESC LIMIT 3",
            (row["id"],),
        ).fetchall()
        beats.append({
            "beat_id": row["id"],
            "title": row["title"],
            "promise": row["promise"],
            "payoff_condition": row["payoff_condition"],
            "subject": row["subject"],
            "tension": row["tension"],
            "status": row["status"],
            "progress_count": row["progress_count"],
            "created_turn": row["created_turn"],
            "last_progress_turn": row["last_progress_turn"],
            "resolution": row["resolution"],
            "recent_progress": [dict(n) for n in notes],
        })
    return {"count": len(beats), "beats": beats}


# ---------------------------------------------------------------------------
# Per-turn context block
# ---------------------------------------------------------------------------

def _directives(open_beats: list, turn: int) -> list[str]:
    if not open_beats:
        return ["No open promises. Establish one this turn with promise_beat: "
                "something concrete the player can anticipate (a foe, a mystery, "
                "a debt, an arc). Foreshadow it in narration."]

    out: list[str] = []
    ripe = [b for b in open_beats
            if b["progress_count"] >= RIPE_THRESHOLD.get(b["tension"], 3)]
    for beat in ripe:
        out.append(f"RIPE FOR PAYOFF: '{beat['title']}' (beat_id {beat['beat_id']}) has "
                   f"{beat['progress_count']} progress steps. Pay it off when it can land "
                   "surprising-yet-inevitable (payoff_beat), then seed the next promise.")

    stale = [b for b in open_beats
             if b not in ripe
             and turn - (b["last_progress_turn"] or b["created_turn"] or turn) >= STALE_TURNS]
    for beat in stale:
        idle = turn - (beat["last_progress_turn"] or beat["created_turn"] or turn)
        out.append(f"STALE: '{beat['title']}' (beat_id {beat['beat_id']}) has had no visible "
                   f"movement for {idle} turns. Advance it this turn (progress_beat) or "
                   "retire it (payoff_beat with abandoned=true).")

    if len(open_beats) >= MAX_OPEN_BEATS:
        out.append("AT CAPACITY: do not create new promises; progress or pay off existing ones.")

    if not out:
        out.append("Advance at least one open promise with visible movement this turn, "
                   "and record it with progress_beat. Progress the player can feel — "
                   "escalation, revelation, or consequence, not filler.")
    return out


def build_beats_context(turn: int | None = None) -> str:
    """Returns the STORY BEATS block for this turn, or "" on failure.
    Never raises."""
    try:
        with get_conn() as conn:
            turn = current_turn(conn) if turn is None else turn
            data = list_beats(conn, {"status": "open"})
            open_beats = data["beats"]
            recent_paid = conn.execute(
                "SELECT title, resolution, resolved_turn FROM beat_promises "
                "WHERE status='paid_off' ORDER BY resolved_turn DESC LIMIT 2"
            ).fetchall()

        lines = [f"Turn {turn}. Open promises: {len(open_beats)}"]
        for beat in open_beats:
            ripe_at = RIPE_THRESHOLD.get(beat["tension"], 3)
            last = beat["last_progress_turn"] or beat["created_turn"]
            lines.append(
                f"- [beat {beat['beat_id']}] {beat['title']} "
                f"({beat['tension']}, progress {beat['progress_count']}/{ripe_at}, "
                f"last movement turn {last})"
            )
            lines.append(f"  promise: {beat['promise']}")
            if beat["payoff_condition"]:
                lines.append(f"  pays off when: {beat['payoff_condition']}")
            if beat["recent_progress"]:
                latest = beat["recent_progress"][0]
                lines.append(f"  latest progress (turn {latest['turn']}): {latest['note']}")

        for row in recent_paid:
            lines.append(f"- (paid off, turn {row['resolved_turn']}) {row['title']}: "
                         f"{row['resolution']} — usable as callback material.")

        lines.append("PACING DIRECTIVES (Promise -> Progress -> Payoff):")
        for directive in _directives(open_beats, turn or 0):
            lines.append(f"- {directive}")

        text = "\n".join(lines)
        if len(text) > MAX_CONTEXT_CHARS:
            text = text[:MAX_CONTEXT_CHARS].rsplit("\n", 1)[0]
        return text
    except Exception:
        logger.exception("build_beats_context failed")
        return ""
