from __future__ import annotations

import json
from uuid import uuid4

from .channel import append_event, list_failed_events, update_event
from .coach import CoachAgent
from .db import Database
from .parser import Parser
from .records import get_event, get_task, insert_tasks, list_tasks, update_task
from .response import compose_receipt


def _now() -> str:
    from .channel import utc_now

    return utc_now()


def _envelope(request_id: str, data: dict, *, code: str = "OK", message: str = "") -> dict:
    return {
        "code": code,
        "message": message,
        "request_id": request_id,
        "timestamp": _now(),
        "data": data,
    }


class Pipeline:
    def __init__(
        self,
        db: Database,
        parser: Parser,
        *,
        coach: CoachAgent | None = None,
        reset_db: bool = False,
    ):
        self.db = db
        self.parser = parser
        self.coach = coach
        if reset_db:
            self.db.reset()
        else:
            self.db.init()

    def run_turn(
        self,
        *,
        user_id: str,
        source: str,
        source_message_id: str,
        content: str,
        request_id: str | None = None,
    ) -> dict:
        request_id = request_id or str(uuid4())
        with self.db.session() as conn:
            event, duplicate = append_event(
                conn,
                user_id=user_id,
                source=source,
                source_message_id=source_message_id,
                event_type="utterance",
                content=content,
                parse_status="received",
            )
            if duplicate:
                existing = get_event(
                    conn, event_id=event["event_id"], user_id=user_id
                )
                cached = (
                    json.loads(existing["response_payload_json"])
                    if existing and existing.get("response_payload_json")
                    else None
                )
                if cached:
                    cached.setdefault("data", {})["duplicate"] = True
                    return cached
                # A previous run may have failed before writing a cached response.
                data = {
                    "status": "duplicate",
                    "duplicate": True,
                    "event_id": event["event_id"],
                    "reply_text": "这条消息已经处理过。",
                    "tasks": existing["tasks"] if existing else [],
                    "clarification": None,
                    "coach_text": None,
                }
                return _envelope(request_id, data)

        with self.db.session() as conn:
            try:
                parsed = self.parser.parse(content, session_id=user_id)
                tasks = insert_tasks(
                    conn,
                    user_id=user_id,
                    source_event_id=event["event_id"],
                    records=parsed["records"],
                )
                update_event(
                    conn,
                    event_id=event["event_id"],
                    parse_status="parsed",
                    parse_result_json=json.dumps(parsed, ensure_ascii=False),
                )
            except Exception as exc:
                clarification = (
                    "我没判断出这句要记成任务还是进展，你是想记录哪一件？"
                )
                payload = _envelope(
                    request_id,
                    {
                        "status": "clarification_required",
                        "event_id": event["event_id"],
                        "reply_text": clarification,
                        "tasks": [],
                        "clarification": clarification,
                        "coach_text": None,
                        "error": str(exc),
                    },
                    code="PARSE_REJECTED",
                )
                update_event(
                    conn,
                    event_id=event["event_id"],
                    parse_status="failed",
                    parse_result_json=json.dumps(
                        {"error": str(exc)}, ensure_ascii=False
                    ),
                    response_payload_json=json.dumps(payload, ensure_ascii=False),
                )
                return payload

        # The coach is deliberately outside the write transaction. It cannot
        # block or roll back a successful record write.
        with self.db.session() as conn:
            event_after = get_event(
                conn, event_id=event["event_id"], user_id=user_id
            )
        context = {
            "recent_events": [
                {
                    "event_id": event_after["event_id"],
                    "content": event_after["content"],
                    "created_at": event_after["created_at"],
                }
            ],
            "open_tasks": [
                {
                    "record_id": task["record_id"],
                    "kind": task["kind"],
                    "title": task["title"],
                    "status": task["status"],
                }
                for task in event_after["tasks"]
                if task["status"] not in {"done", "cancelled", "revoked"}
            ],
        }
        coach_text = None
        if self.coach is not None:
            try:
                coach_text = self.coach.advise(user_id=user_id, context=context)
            except Exception:
                coach_text = None

        reply_text = compose_receipt(tasks, parsed["clarification"])
        data = {
            "status": "recorded" if parsed["records"] else "clarification_required",
            "event_id": event["event_id"],
            "reply_text": reply_text,
            "tasks": tasks,
            "clarification": parsed["clarification"],
            "coach_text": coach_text,
        }
        payload = _envelope(request_id, data)
        with self.db.session() as conn:
            update_event(
                conn,
                event_id=event["event_id"],
                response_payload_json=json.dumps(payload, ensure_ascii=False),
            )
        return payload

    def correct(
        self,
        *,
        user_id: str,
        source: str,
        source_message_id: str,
        target_record_id: str,
        content: str,
        changes: dict,
        request_id: str | None = None,
    ) -> dict:
        request_id = request_id or str(uuid4())
        with self.db.session() as conn:
            task = get_task(conn, record_id=target_record_id, user_id=user_id)
            if not task:
                raise LookupError("task not found")
            event, duplicate = append_event(
                conn,
                user_id=user_id,
                source=source,
                source_message_id=source_message_id,
                event_type="correction",
                content=content,
                related_event_id=task["source_event_id"],
                target_record_id=target_record_id,
                parse_status="parsed",
            )
            if duplicate:
                existing = get_event(
                    conn, event_id=event["event_id"], user_id=user_id
                )
                payload = (
                    json.loads(existing["response_payload_json"])
                    if existing and existing.get("response_payload_json")
                    else _envelope(request_id, {"status": "duplicate"})
                )
                payload.setdefault("data", {})["duplicate"] = True
                return payload
            updated = update_task(
                conn,
                record_id=target_record_id,
                user_id=user_id,
                changes=changes,
            )
            payload = _envelope(
                request_id,
                {
                    "status": "corrected",
                    "event_id": event["event_id"],
                    "target_record_id": target_record_id,
                    "task": updated,
                    "reply_text": "已更新这条记录。",
                    "clarification": None,
                    "coach_text": None,
                },
            )
            update_event(
                conn,
                event_id=event["event_id"],
                parse_status="parsed",
                response_payload_json=json.dumps(payload, ensure_ascii=False),
            )
            return payload

    def tasks(self, *, user_id: str, date: str | None = None) -> list[dict]:
        with self.db.session() as conn:
            return list_tasks(conn, user_id=user_id, date=date)

    def failed_events(self, *, user_id: str) -> list[dict]:
        with self.db.session() as conn:
            return list_failed_events(conn, user_id=user_id)

    def event(self, *, event_id: str, user_id: str) -> dict | None:
        with self.db.session() as conn:
            return get_event(conn, event_id=event_id, user_id=user_id)

