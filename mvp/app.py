from __future__ import annotations

import argparse
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from .coach import CoachAgent
from .db import Database
from .parser import build_parser
from .pipeline import Pipeline
from .wechat import WeChatAdapter


ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"
DEFAULT_DB = ROOT / "data" / "demo.db"


def make_pipeline(
    db_path: str | Path = DEFAULT_DB, *, reset_db: bool = False
) -> Pipeline:
    return Pipeline(
        Database(db_path),
        build_parser(),
        coach=CoachAgent(),
        reset_db=reset_db,
    )


class Handler(BaseHTTPRequestHandler):
    pipeline: Pipeline
    wechat: WeChatAdapter | None = None

    def log_message(self, fmt: str, *args) -> None:
        print(f"[http] {self.address_string()} {fmt % args}")

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _text(
        self, status: int, body: str, content_type: str = "text/plain; charset=utf-8"
    ) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _xml(self, status: int, body: str) -> None:
        self._text(status, body, "application/xml; charset=utf-8")

    def _raw_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return b""
        return self.rfile.read(length)

    def _body(self) -> dict:
        raw = self._raw_body()
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _wechat_signature_ok(self, query: dict[str, list[str]]) -> bool:
        adapter = getattr(self, "wechat", None)
        if adapter is None or not adapter.configured:
            return False
        return adapter.verify_signature(
            signature=(query.get("signature") or [""])[0],
            timestamp=(query.get("timestamp") or [""])[0],
            nonce=(query.get("nonce") or [""])[0],
        )

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        user_id = (query.get("user_id") or ["demo-user"])[0]

        if parsed.path == "/":
            body = (WEB_ROOT / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path in {"/health", "/api/health"}:
            self._json(200, {"ok": True, "status": "healthy"})
            return
        if parsed.path == "/wechat/callback":
            adapter = getattr(self, "wechat", None)
            if adapter is None or not adapter.configured:
                self._text(503, "wechat token is not configured")
                return
            if not self._wechat_signature_ok(query):
                self._text(403, "invalid signature")
                return
            self._text(200, (query.get("echostr") or [""])[0])
            return
        if parsed.path in {"/api/v1/tasks", "/api/today"}:
            date = (query.get("date") or [None])[0]
            tasks = self.pipeline.tasks(user_id=user_id, date=date)
            self._json(
                200,
                {
                    "code": "OK",
                    "message": "",
                    "request_id": str(uuid4()),
                    "timestamp": __import__("datetime").datetime.now(
                        __import__("datetime").timezone.utc
                    ).isoformat(),
                    "data": {"tasks": tasks},
                },
            )
            return
        if parsed.path == "/api/v1/events":
            status = (query.get("parse_status") or [None])[0]
            if status == "failed":
                events = self.pipeline.failed_events(user_id=user_id)
            else:
                events = []
            self._json(
                200,
                {
                    "code": "OK",
                    "message": "",
                    "request_id": str(uuid4()),
                    "data": {"events": events},
                },
            )
            return
        match = re.fullmatch(r"/api/v1/events/([^/]+)", parsed.path)
        if not match:
            match = re.fullmatch(r"/api/utterances/([^/]+)", parsed.path)
        if match:
            event = self.pipeline.event(event_id=match.group(1), user_id=user_id)
            if not event:
                self._json(404, {"code": "NOT_FOUND", "message": "event not found"})
            else:
                self._json(200, {"code": "OK", "data": event})
            return
        self._json(404, {"code": "NOT_FOUND", "message": "not found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/wechat/callback":
            query = parse_qs(parsed.query)
            adapter = getattr(self, "wechat", None)
            if adapter is None or not adapter.configured:
                self._text(503, "wechat token is not configured")
                return
            if not self._wechat_signature_ok(query):
                self._text(403, "invalid signature")
                return
            raw = self._raw_body()
            self._xml(200, adapter.handle_post(raw))
            return
        try:
            body = self._body()
            if parsed.path in {"/api/v1/turns", "/api/utterances"}:
                payload = self.pipeline.run_turn(
                    user_id=str(body.get("user_id") or "demo-user"),
                    source=str(body.get("source") or "h5"),
                    source_message_id=str(
                        body.get("source_message_id") or uuid4()
                    ),
                    content=str(body["content"]),
                    request_id=body.get("request_id"),
                )
                self._json(200, payload)
                return
            if parsed.path == "/api/v1/corrections":
                payload = self.pipeline.correct(
                    user_id=str(body["user_id"]),
                    source=str(body.get("source") or "h5"),
                    source_message_id=str(
                        body.get("source_message_id") or uuid4()
                    ),
                    target_record_id=str(body["target_record_id"]),
                    content=str(body.get("content") or "用户纠正"),
                    changes=body.get("changes") or {},
                    request_id=body.get("request_id"),
                )
                self._json(200, payload)
                return
            self._json(404, {"code": "NOT_FOUND", "message": "not found"})
        except KeyError as exc:
            self._json(
                400,
                {"code": "VALIDATION_ERROR", "message": f"missing field: {exc}"},
            )
        except (ValueError, json.JSONDecodeError) as exc:
            self._json(400, {"code": "VALIDATION_ERROR", "message": str(exc)})
        except LookupError as exc:
            self._json(404, {"code": "NOT_FOUND", "message": str(exc)})
        except Exception as exc:
            self._json(500, {"code": "INTERNAL_ERROR", "message": str(exc)})

    def do_PATCH(self) -> None:
        """Compatibility alias for the previous H5 revoke endpoint."""
        match = re.fullmatch(r"/api/records/([^/]+)", urlparse(self.path).path)
        if not match:
            self._json(404, {"code": "NOT_FOUND", "message": "not found"})
            return
        try:
            body = self._body()
            payload = self.pipeline.correct(
                user_id=str(body.get("user_id") or "demo-user"),
                source="h5",
                source_message_id=str(body.get("source_message_id") or uuid4()),
                target_record_id=match.group(1),
                content=str(body.get("content") or "用户撤销"),
                changes=body.get("changes") or {"status": "revoked"},
            )
            self._json(200, payload)
        except Exception as exc:
            self._json(400, {"code": "VALIDATION_ERROR", "message": str(exc)})


def demo(db_path: str) -> None:
    pipeline = make_pipeline(db_path, reset_db=True)
    result = pipeline.run_turn(
        user_id="U-DEMO-001",
        source="h5",
        source_message_id=f"demo-{uuid4()}",
        content="今天背完单词了，论文开头也改了，跟朋友聊完没那么焦虑了。",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("\nTASKS:")
    print(
        json.dumps(
            pipeline.tasks(user_id="U-DEMO-001"),
            ensure_ascii=False,
            indent=2,
        )
    )
    print("\nEVENT:")
    print(
        json.dumps(
            pipeline.event(
                event_id=result["data"]["event_id"], user_id="U-DEMO-001"
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18765)
    parser.add_argument(
        "--reset-db",
        action="store_true",
        help="Reset the SQLite database before starting the server.",
    )
    parser.add_argument(
        "--db", default=os.environ.get("SQLITE_PATH", str(DEFAULT_DB))
    )
    args = parser.parse_args()
    if args.demo:
        demo(args.db)
        return
    Handler.pipeline = make_pipeline(args.db, reset_db=args.reset_db)
    Handler.wechat = WeChatAdapter(
        Handler.pipeline, token=os.environ.get("WECHAT_TOKEN", "")
    )
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Serving MVP at http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()

