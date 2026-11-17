from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import tempfile
import threading
import time
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode
from xml.etree import ElementTree

from mvp.app import Handler
from mvp.db import Database
from mvp.parser import MockParser
from mvp.pipeline import Pipeline
from mvp.wechat import WeChatAdapter, calculate_signature


FIXED_INPUT = "今天背完单词了，论文开头也改了，跟朋友聊完没那么焦虑了。"


def text_xml(
    *,
    from_user: str,
    msg_id: str,
    content: str,
    to_user: str = "gh_mock_account",
) -> bytes:
    return f"""<xml>
<ToUserName><![CDATA[{to_user}]]></ToUserName>
<FromUserName><![CDATA[{from_user}]]></FromUserName>
<CreateTime>1763308800</CreateTime>
<MsgType><![CDATA[text]]></MsgType>
<Content><![CDATA[{content}]]></Content>
<MsgId>{msg_id}</MsgId>
</xml>""".encode("utf-8")


def voice_xml(
    *, from_user: str, msg_id: str, recognition: str
) -> bytes:
    return f"""<xml>
<ToUserName><![CDATA[gh_mock_account]]></ToUserName>
<FromUserName><![CDATA[{from_user}]]></FromUserName>
<CreateTime>1763308801</CreateTime>
<MsgType><![CDATA[voice]]></MsgType>
<MediaId><![CDATA[mock-media-id]]></MediaId>
<Format><![CDATA[amr]]></Format>
<Recognition><![CDATA[{recognition}]]></Recognition>
<MsgId>{msg_id}</MsgId>
</xml>""".encode("utf-8")


def today_menu_xml(*, from_user: str) -> bytes:
    return f"""<xml>
<ToUserName><![CDATA[gh_mock_account]]></ToUserName>
<FromUserName><![CDATA[{from_user}]]></FromUserName>
<CreateTime>1763308802</CreateTime>
<MsgType><![CDATA[event]]></MsgType>
<Event><![CDATA[CLICK]]></Event>
<EventKey><![CDATA[TODAY]]></EventKey>
</xml>""".encode("utf-8")


class WeChatAdapterHttpTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "wechat-test.db"
        self.pipeline = Pipeline(Database(self.db_path), MockParser())
        self.token = secrets.token_urlsafe(24)

        class TestHandler(Handler):
            pipeline = self.pipeline
            wechat = WeChatAdapter(self.pipeline, token=self.token)

            def log_message(self, fmt: str, *args) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        connection = HTTPConnection(
            "127.0.0.1", self.server.server_port, timeout=5
        )
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            payload = response.read()
            response_headers = {
                key.lower(): value for key, value in response.getheaders()
            }
            return response.status, response_headers, payload
        finally:
            connection.close()

    def _signed_query(self, *, nonce: str | None = None) -> str:
        timestamp = str(int(time.time()))
        nonce = nonce or secrets.token_hex(8)
        signature = calculate_signature(self.token, timestamp, nonce)
        return urlencode(
            {
                "signature": signature,
                "timestamp": timestamp,
                "nonce": nonce,
            }
        )

    def _post_callback(self, xml_body: bytes) -> tuple[int, dict[str, str], bytes]:
        return self._request(
            "POST",
            f"/wechat/callback?{self._signed_query()}",
            body=xml_body,
            headers={"Content-Type": "text/xml; charset=utf-8"},
        )

    def _rows(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self.pipeline.db.session() as connection:
            return connection.execute(sql, args).fetchall()

    def _assert_text_reply(
        self,
        payload: bytes,
        *,
        to_user: str,
        from_user: str,
    ) -> str:
        reply = ElementTree.fromstring(payload)
        self.assertEqual(reply.tag, "xml")
        self.assertEqual(reply.findtext("ToUserName"), to_user)
        self.assertEqual(reply.findtext("FromUserName"), from_user)
        self.assertEqual(reply.findtext("MsgType"), "text")
        self.assertTrue(reply.findtext("CreateTime"))
        return reply.findtext("Content") or ""

    def test_get_signature_success(self) -> None:
        timestamp = "1763308800"
        nonce = "mock-nonce"
        expected_signature = hashlib.sha1(
            "".join(sorted((self.token, timestamp, nonce))).encode("utf-8")
        ).hexdigest()
        self.assertEqual(
            calculate_signature(self.token, timestamp, nonce),
            expected_signature,
        )

        path = (
            f"/wechat/callback?{self._signed_query()}"
            f"&{urlencode({'echostr': 'mock-echo-ok'})}"
        )
        status, headers, payload = self._request("GET", path)
        self.assertEqual(status, 200)
        self.assertEqual(payload.decode("utf-8"), "mock-echo-ok")
        self.assertIn("text/plain", headers["content-type"])

    def test_get_signature_failure(self) -> None:
        timestamp = str(int(time.time()))
        path = "/wechat/callback?" + urlencode(
            {
                "signature": "0" * 40,
                "timestamp": timestamp,
                "nonce": "wrong-nonce",
                "echostr": "must-not-echo",
            }
        )
        status, _, payload = self._request("GET", path)
        self.assertEqual(status, 403)
        self.assertEqual(payload.decode("utf-8"), "invalid signature")

    def test_text_callback_maps_user_and_message_id(self) -> None:
        status, headers, payload = self._post_callback(
            text_xml(
                from_user="openid-text-user",
                msg_id="wx-text-1001",
                content=FIXED_INPUT,
            )
        )
        self.assertEqual(status, 200)
        self.assertIn("application/xml", headers["content-type"])
        reply_text = self._assert_text_reply(
            payload,
            to_user="openid-text-user",
            from_user="gh_mock_account",
        )
        self.assertIn("已记下", reply_text)

        events = self._rows("SELECT * FROM raw_events")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["user_id"], "openid-text-user")
        self.assertEqual(events[0]["source"], "wechat")
        self.assertEqual(events[0]["source_message_id"], "wx-text-1001")
        self.assertEqual(events[0]["content"], FIXED_INPUT)
        self.assertEqual(len(self._rows("SELECT * FROM tasks")), 2)

    def test_voice_callback_uses_recognition_text(self) -> None:
        recognition = "今天背完单词了。"
        status, _, payload = self._post_callback(
            voice_xml(
                from_user="openid-voice-user",
                msg_id="wx-voice-2001",
                recognition=recognition,
            )
        )
        self.assertEqual(status, 200)
        self._assert_text_reply(
            payload,
            to_user="openid-voice-user",
            from_user="gh_mock_account",
        )

        events = self._rows("SELECT * FROM raw_events")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["source_message_id"], "wx-voice-2001")
        self.assertEqual(events[0]["content"], recognition)
        self.assertEqual(len(self._rows("SELECT * FROM tasks")), 1)

    def test_duplicate_msg_id_uses_existing_idempotency(self) -> None:
        body = text_xml(
            from_user="openid-duplicate-user",
            msg_id="wx-duplicate-3001",
            content=FIXED_INPUT,
        )
        first_status, _, _ = self._post_callback(body)
        second_status, _, second_payload = self._post_callback(body)
        self.assertEqual(first_status, 200)
        self.assertEqual(second_status, 200)
        reply_text = self._assert_text_reply(
            second_payload,
            to_user="openid-duplicate-user",
            from_user="gh_mock_account",
        )
        self.assertIn("未重复记录", reply_text)
        self.assertEqual(len(self._rows("SELECT * FROM raw_events")), 1)
        self.assertEqual(len(self._rows("SELECT * FROM tasks")), 2)

    def test_today_menu_returns_tasks_without_new_event(self) -> None:
        self._post_callback(
            text_xml(
                from_user="openid-menu-user",
                msg_id="wx-menu-seed-4001",
                content=FIXED_INPUT,
            )
        )
        before_events = len(self._rows("SELECT * FROM raw_events"))
        status, _, payload = self._post_callback(
            today_menu_xml(from_user="openid-menu-user")
        )
        self.assertEqual(status, 200)
        reply_text = self._assert_text_reply(
            payload,
            to_user="openid-menu-user",
            from_user="gh_mock_account",
        )
        self.assertIn("今日记录", reply_text)
        self.assertIn("背单词", reply_text)
        self.assertIn("毕业论文", reply_text)
        self.assertEqual(
            len(self._rows("SELECT * FROM raw_events")), before_events
        )

    def test_malformed_xml_preserves_best_effort_original(self) -> None:
        malformed = (
            "<xml>"
            "<ToUserName><![CDATA[gh_mock_account]]></ToUserName>"
            "<FromUserName><![CDATA[openid-broken-user]]></FromUserName>"
            "<CreateTime>1763308803</CreateTime>"
            "<MsgType><![CDATA[text]]></MsgType>"
            "<Content><![CDATA[今天背完单词了]]></Content>"
            "<MsgId>wx-broken-5001</MsgId>"
        ).encode("utf-8")
        status, _, payload = self._post_callback(malformed)
        self.assertEqual(status, 200)
        reply_text = self._assert_text_reply(
            payload,
            to_user="openid-broken-user",
            from_user="gh_mock_account",
        )
        self.assertIn("已先按最佳努力保存", reply_text)
        events = self._rows("SELECT * FROM raw_events")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["content"], "今天背完单词了")
        self.assertEqual(events[0]["source_message_id"], "wx-broken-5001")

    def test_pipeline_parse_failure_returns_explained_reply(self) -> None:
        class BrokenParser:
            def parse(self, content: str, session_id: str | None = None) -> dict:
                raise RuntimeError("mock parser rejected input")

        pipeline = Pipeline(
            Database(Path(self.temp_dir.name) / "parse-failure.db"),
            BrokenParser(),
        )
        adapter = WeChatAdapter(pipeline, token=self.token)
        reply = ElementTree.fromstring(
            adapter.handle_post(
                text_xml(
                    from_user="openid-parse-failed",
                    msg_id="wx-parse-failed-7001",
                    content="这句故意让解析器失败",
                )
            )
        )
        reply_text = reply.findtext("Content") or ""
        self.assertIn("原话已保存", reply_text)
        with pipeline.db.session() as connection:
            event = connection.execute(
                "SELECT * FROM raw_events"
            ).fetchone()
        self.assertEqual(event["content"], "这句故意让解析器失败")
        self.assertEqual(event["parse_status"], "failed")

    def test_h5_utterances_path_still_works(self) -> None:
        body = json.dumps(
            {
                "user_id": "h5-user",
                "source": "h5",
                "source_message_id": "h5-compat-6001",
                "content": FIXED_INPUT,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        status, _, payload = self._request(
            "POST",
            "/api/utterances",
            body=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        self.assertEqual(status, 200)
        result = json.loads(payload.decode("utf-8"))
        self.assertEqual(result["code"], "OK")
        self.assertEqual(result["data"]["status"], "recorded")
        events = self._rows("SELECT * FROM raw_events")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["source"], "h5")


if __name__ == "__main__":
    unittest.main()
