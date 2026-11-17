from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def insert_tasks(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    source_event_id: str,
    records: list[dict],
) -> list[dict]:
    created: list[dict] = []
    now = utc_now()
    for item in records:
        record_id = str(uuid4())
        payload = dict(item.get("payload") or {})
        payload.setdefault("confidence", item.get("confidence"))
        payload.setdefault("evidence", item.get("evidence"))
        conn.execute(
            """
            INSERT INTO tasks
                (record_id, user_id, source_event_id, kind, title, content,
                 status, occurred_on, due_at, payload_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record_id,
                user_id,
                source_event_id,
                item["kind"],
                item.get("title"),
                item["content"],
                item["status"],
                item.get("occurred_on"),
                item.get("due_at"),
                json.dumps(payload, ensure_ascii=False),
                now,
                now,
            ),
        )
        created.append(
            {
                "record_id": record_id,
                "kind": item["kind"],
                "title": item.get("title"),
                "content": item["content"],
                "status": item["status"],
                "occurred_on": item.get("occurred_on"),
                "due_at": item.get("due_at"),
                "source_event_id": source_event_id,
            }
        )
    return created


def list_tasks(
    conn: sqlite3.Connection, *, user_id: str, date: str | None = None
) -> list[dict]:
    date = date or datetime.now(timezone.utc).date().isoformat()
    rows = conn.execute(
        """
        SELECT record_id, user_id, source_event_id, kind, title, content,
               status, occurred_on, due_at, payload_json, revoked_at,
               created_at, updated_at
        FROM tasks
        WHERE user_id = ?
          AND COALESCE(occurred_on, substr(created_at, 1, 10)) = ?
        ORDER BY created_at ASC
        """,
        (user_id, date),
    ).fetchall()
    return [dict(row) for row in rows]


def get_task(
    conn: sqlite3.Connection, *, record_id: str, user_id: str
) -> dict | None:
    row = conn.execute(
        "SELECT * FROM tasks WHERE record_id = ? AND user_id = ?",
        (record_id, user_id),
    ).fetchone()
    return dict(row) if row else None


def update_task(
    conn: sqlite3.Connection,
    *,
    record_id: str,
    user_id: str,
    changes: dict,
) -> dict:
    current = get_task(conn, record_id=record_id, user_id=user_id)
    if not current:
        raise LookupError("task not found")
    allowed = {
        "title",
        "content",
        "status",
        "occurred_on",
        "due_at",
        "revoked_at",
    }
    values = {key: value for key, value in changes.items() if key in allowed}
    if not values:
        return current
    values["updated_at"] = utc_now()
    assignments = ", ".join(f"{key} = ?" for key in values)
    conn.execute(
        f"UPDATE tasks SET {assignments} WHERE record_id = ?",
        (*values.values(), record_id),
    )
    return get_task(conn, record_id=record_id, user_id=user_id) or current


def get_event(
    conn: sqlite3.Connection, *, event_id: str, user_id: str | None = None
) -> dict | None:
    sql = "SELECT * FROM raw_events WHERE event_id = ?"
    args: list[str] = [event_id]
    if user_id is not None:
        sql += " AND user_id = ?"
        args.append(user_id)
    row = conn.execute(sql, args).fetchone()
    if not row:
        return None
    event = dict(row)
    tasks = conn.execute(
        """
        SELECT record_id, user_id, source_event_id, kind, title, content,
               status, occurred_on, due_at, payload_json, revoked_at,
               created_at, updated_at
        FROM tasks WHERE source_event_id = ? ORDER BY created_at ASC
        """,
        (event_id,),
    ).fetchall()
    event["tasks"] = [dict(task) for task in tasks]
    return event

