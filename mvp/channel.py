from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def append_event(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    source: str,
    source_message_id: str,
    event_type: str,
    content: str,
    related_event_id: str | None = None,
    target_record_id: str | None = None,
    parse_status: str = "received",
    commit: bool = False,
) -> tuple[dict, bool]:
    existing = conn.execute(
        """
        SELECT * FROM raw_events
        WHERE user_id = ? AND source = ? AND source_message_id = ?
        """,
        (user_id, source, source_message_id),
    ).fetchone()
    if existing:
        return dict(existing), True

    event_id = str(uuid4())
    now = utc_now()
    conn.execute(
        """
        INSERT INTO raw_events
            (event_id, user_id, source, source_message_id, event_type, content,
             related_event_id, target_record_id, parse_status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            user_id,
            source,
            source_message_id,
            event_type,
            content,
            related_event_id,
            target_record_id,
            parse_status,
            now,
            now,
        ),
    )
    if commit:
        conn.commit()
    row = conn.execute(
        "SELECT * FROM raw_events WHERE event_id = ?", (event_id,)
    ).fetchone()
    return dict(row), False


def update_event(
    conn: sqlite3.Connection,
    *,
    event_id: str,
    parse_status: str | None = None,
    parse_result_json: str | None = None,
    response_payload_json: str | None = None,
) -> None:
    current = conn.execute(
        "SELECT * FROM raw_events WHERE event_id = ?", (event_id,)
    ).fetchone()
    if not current:
        raise LookupError("event not found")
    conn.execute(
        """
        UPDATE raw_events
        SET parse_status = ?, parse_result_json = ?, response_payload_json = ?,
            updated_at = ?
        WHERE event_id = ?
        """,
        (
            parse_status if parse_status is not None else current["parse_status"],
            parse_result_json
            if parse_result_json is not None
            else current["parse_result_json"],
            response_payload_json
            if response_payload_json is not None
            else current["response_payload_json"],
            utc_now(),
            event_id,
        ),
    )


def list_failed_events(
    conn: sqlite3.Connection, *, user_id: str, limit: int = 20
) -> list[dict]:
    rows = conn.execute(
        """
        SELECT event_id, content, event_type, parse_status, parse_result_json,
               response_payload_json, created_at, updated_at
        FROM raw_events
        WHERE user_id = ? AND parse_status = 'failed'
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()
    return [dict(row) for row in rows]

