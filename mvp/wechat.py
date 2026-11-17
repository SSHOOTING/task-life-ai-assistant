from __future__ import annotations

import hashlib
import hmac
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol
from xml.etree import ElementTree


MAX_CALLBACK_BYTES = 1024 * 1024
MAX_REPLY_BYTES = 1800
SHANGHAI_TZ = timezone(timedelta(hours=8))

STATUS_LABELS = {
    "pending": "待开始",
    "in_progress": "进行中",
    "active": "进行中",
    "done": "已完成",
    "cancelled": "已取消",
    "revoked": "已撤销",
}
KIND_LABELS = {
    "task": "任务",
    "task_progress": "任务进展",
    "daily_task": "每日任务",
}


class PipelineLike(Protocol):
    def run_turn(
        self,
        *,
        user_id: str,
        source: str,
        source_message_id: str,
        content: str,
        request_id: str | None = None,
    ) -> dict: ...

    def tasks(self, *, user_id: str, date: str | None = None) -> list[dict]: ...


class WeChatMessageError(ValueError):
    """The callback body is not a supported WeChat message."""


@dataclass(frozen=True)
class WeChatMessage:
    to_user_name: str
    from_user_name: str
    create_time: str
    message_type: str
    content: str
    message_id: str
    event: str
    event_key: str
    recognition: str


def calculate_signature(token: str, timestamp: str, nonce: str) -> str:
    """Return the SHA-1 signature used by WeChat server verification."""
    material = "".join(sorted((token, timestamp, nonce)))
    return hashlib.sha1(material.encode("utf-8")).hexdigest()


def verify_signature(
    *, token: str, signature: str, timestamp: str, nonce: str
) -> bool:
    if not token or not signature or not timestamp or not nonce:
        return False
    expected = calculate_signature(token, timestamp, nonce)
    return hmac.compare_digest(expected, signature.lower())


def _decode_body(body: bytes | str) -> str:
    if isinstance(body, bytes):
        if len(body) > MAX_CALLBACK_BYTES:
            raise WeChatMessageError("callback body is too large")
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WeChatMessageError("callback body is not valid UTF-8") from exc
    else:
        text = body
        if len(text.encode("utf-8")) > MAX_CALLBACK_BYTES:
            raise WeChatMessageError("callback body is too large")
    return text.lstrip("\ufeff")


def _field(values: dict[str, str], name: str, *, strip: bool = True) -> str:
    value = values.get(name, "")
    return value.strip() if strip else value


def parse_wechat_xml(body: bytes | str) -> WeChatMessage:
    """Parse the WeChat plaintext XML callback format."""
    text = _decode_body(body)
    if not text.strip():
        raise WeChatMessageError("callback body is empty")
    declaration_scan = text.upper()
    if "<!DOCTYPE" in declaration_scan or "<!ENTITY" in declaration_scan:
        raise WeChatMessageError("DTD and entities are not allowed")
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise WeChatMessageError("callback body is not valid XML") from exc
    if root.tag != "xml":
        raise WeChatMessageError("callback root element must be xml")

    values = {child.tag: child.text or "" for child in root}
    message = WeChatMessage(
        to_user_name=_field(values, "ToUserName"),
        from_user_name=_field(values, "FromUserName"),
        create_time=_field(values, "CreateTime"),
        message_type=_field(values, "MsgType").lower(),
        content=_field(values, "Content", strip=False),
        message_id=_field(values, "MsgId"),
        event=_field(values, "Event").upper(),
        event_key=_field(values, "EventKey").upper(),
        recognition=_field(values, "Recognition", strip=False),
    )
    if not message.from_user_name:
        raise WeChatMessageError("FromUserName is required")
    if not message.message_type:
        raise WeChatMessageError("MsgType is required")
    return message


def _loose_tag(text: str, tag: str) -> str:
    match = re.search(
        rf"<{tag}>\s*(?:<!\[CDATA\[(.*?)\]\]>|(.*?))\s*</{tag}>",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return ""
    value = (
        match.group(1)
        if match.group(1) is not None
        else match.group(2) or ""
    )
    return value.strip()


def _cdata(value: str) -> str:
    return "<![CDATA[" + value.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def _truncate_utf8(value: str, max_bytes: int = MAX_REPLY_BYTES) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    suffix = "\n……内容过长，已截断。"
    budget = max(0, max_bytes - len(suffix.encode("utf-8")))
    shortened = encoded[:budget].decode("utf-8", errors="ignore")
    return shortened + suffix


def build_text_reply(
    *,
    to_user_name: str,
    from_user_name: str,
    content: str,
    create_time: int | None = None,
) -> str:
    """Build a valid plaintext passive reply XML document."""
    timestamp = int(time.time()) if create_time is None else int(create_time)
    safe_content = _truncate_utf8(content)
    return (
        "<xml>\n"
        f"<ToUserName>{_cdata(to_user_name)}</ToUserName>\n"
        f"<FromUserName>{_cdata(from_user_name)}</FromUserName>\n"
        f"<CreateTime>{timestamp}</CreateTime>\n"
        "<MsgType><![CDATA[text]]></MsgType>\n"
        f"<Content>{_cdata(safe_content)}</Content>\n"
        "</xml>"
    )


def format_today_tasks(tasks: list[dict], date_text: str) -> str:
    if not tasks:
        return f"{date_text} 暂无记录。发送一条文字或语音，就能开始记录。"
    lines = [f"{date_text} 今日记录："]
    for index, task in enumerate(tasks, start=1):
        kind = KIND_LABELS.get(str(task.get("kind")), "记录")
        title = str(task.get("title") or task.get("content") or "未命名记录")
        status = STATUS_LABELS.get(str(task.get("status")), str(task.get("status")))
        lines.append(f"{index}. [{kind}] {title}（{status}）")
    return "\n".join(lines)


def _shanghai_today() -> str:
    return datetime.now(SHANGHAI_TZ).date().isoformat()


class WeChatAdapter:
    """Translate WeChat callbacks into the existing Pipeline contract."""

    def __init__(self, pipeline: PipelineLike, *, token: str):
        self.pipeline = pipeline
        self._token = token

    @property
    def configured(self) -> bool:
        return bool(self._token)

    def verify_signature(
        self, *, signature: str, timestamp: str, nonce: str
    ) -> bool:
        return verify_signature(
            token=self._token,
            signature=signature,
            timestamp=timestamp,
            nonce=nonce,
        )

    def handle_post(self, body: bytes | str) -> str:
        size = len(body) if isinstance(body, bytes) else len(body.encode("utf-8"))
        if size > MAX_CALLBACK_BYTES:
            preview = (
                body[:8192].decode("utf-8", errors="replace")
                if isinstance(body, bytes)
                else body[:8192]
            )
            return self._handle_unparsed(
                preview, "callback body is too large", save=False
            )
        try:
            message = parse_wechat_xml(body)
        except WeChatMessageError as exc:
            return self._handle_unparsed(body, str(exc))
        return self._dispatch(message)

    def _dispatch(self, message: WeChatMessage) -> str:
        if message.message_type == "text":
            if not message.content.strip():
                return self._reply(
                    message,
                    "没有收到文字内容。请重新发送要记录的原话。",
                )
            return self._record(
                message,
                content=message.content,
                source_message_id=self._source_message_id(
                    message, message.content
                ),
            )

        if message.message_type == "voice":
            if not message.recognition.strip():
                return self._reply(
                    message,
                    "语音消息没有可用的 Recognition 转写文本，原消息未写入。"
                    "请改发文字，或确认公众号后台已开通语音识别。",
                )
            return self._record(
                message,
                content=message.recognition,
                source_message_id=self._source_message_id(
                    message, message.recognition
                ),
            )

        if (
            message.message_type == "event"
            and message.event == "CLICK"
            and message.event_key == "TODAY"
        ):
            today = _shanghai_today()
            try:
                tasks = self.pipeline.tasks(
                    user_id=message.from_user_name, date=today
                )
            except Exception:
                return self._reply(
                    message, "暂时无法读取今日记录，请稍后再试。"
                )
            return self._reply(message, format_today_tasks(tasks, today))

        return self._reply(
            message,
            f"暂不支持这种消息（MsgType={message.message_type or '未知'}）。"
            "请发送文字或语音；菜单 TODAY 可查看今日记录。",
        )

    def _record(
        self,
        message: WeChatMessage,
        *,
        content: str,
        source_message_id: str,
        prefix: str = "",
    ) -> str:
        try:
            payload = self.pipeline.run_turn(
                user_id=message.from_user_name,
                source="wechat",
                source_message_id=source_message_id,
                content=content,
            )
        except Exception:
            return self._reply(
                message,
                "收到消息，但系统处理失败，未确认写入。请稍后重试。",
            )

        data = payload.get("data") or {}
        reply_text = str(
            data.get("reply_text") or "消息已收到，但暂时没有可返回的回执。"
        )
        if payload.get("code") != "OK":
            reply_text = "原话已保存。" + reply_text
        if data.get("duplicate"):
            reply_text += "\n（这条消息此前已处理，未重复记录。）"
        if prefix:
            reply_text = prefix + reply_text
        return self._reply(message, reply_text)

    def _reply(self, message: WeChatMessage, content: str) -> str:
        return build_text_reply(
            to_user_name=message.from_user_name,
            from_user_name=message.to_user_name,
            content=content,
        )

    def _source_message_id(
        self, message: WeChatMessage, content: str
    ) -> str:
        if message.message_id:
            return message.message_id
        digest = hashlib.sha256(
            f"{message.from_user_name}\n{content}".encode("utf-8")
        ).hexdigest()
        return f"wechat-fallback:{digest}"

    def _handle_unparsed(
        self, body: bytes | str, reason: str, *, save: bool = True
    ) -> str:
        text = (
            body.decode("utf-8", errors="replace")
            if isinstance(body, bytes)
            else body
        )
        to_user_name = _loose_tag(text, "ToUserName")
        from_user_name = _loose_tag(text, "FromUserName")
        message_id = _loose_tag(text, "MsgId")
        content = _loose_tag(text, "Content") or _loose_tag(text, "Recognition")
        if not content and text.strip():
            content = text.strip()

        if not from_user_name:
            return build_text_reply(
                to_user_name="",
                from_user_name="",
                content="微信消息格式异常，且没有识别到用户身份，未能写入记录。"
                "请重新发送文字或语音。",
            )

        message = WeChatMessage(
            to_user_name=to_user_name,
            from_user_name=from_user_name,
            create_time=_loose_tag(text, "CreateTime"),
            message_type=_loose_tag(text, "MsgType").lower(),
            content=content,
            message_id=message_id,
            event=_loose_tag(text, "Event").upper(),
            event_key=_loose_tag(text, "EventKey").upper(),
            recognition=_loose_tag(text, "Recognition"),
        )
        if not content:
            return self._reply(
                message,
                f"微信消息格式异常（{reason}），没有可保存的文字内容。"
                "请重新发送。",
            )
        if not save:
            return self._reply(
                message,
                "微信消息体超过 1 MB，未写入记录。请拆分后重新发送。",
            )

        source_message_id = message_id or (
            "wechat-malformed:"
            + hashlib.sha256(
                text.encode("utf-8", errors="replace")
            ).hexdigest()
        )
        reply = self._record(
            message,
            content=content,
            source_message_id=source_message_id,
            prefix="微信消息格式异常，已先按最佳努力保存收到的原文。\n",
        )
        return reply
