from __future__ import annotations

import json
import re
from datetime import date
from typing import Protocol

from .llm_client import OpenCodeGoClient, build_client_or_none


ALLOWED_KINDS = {"task", "task_progress", "daily_task"}
ALLOWED_STATUSES = {
    "task": {"pending", "in_progress", "done", "cancelled", "revoked"},
    "daily_task": {"pending", "done", "cancelled", "revoked"},
    "task_progress": {"active", "revoked"},
}


class Parser(Protocol):
    def parse(self, content: str, session_id: str | None = None) -> dict:
        ...


class MockParser:
    """Deterministic local equivalent of the C parser output contract."""

    def parse(self, content: str, session_id: str | None = None) -> dict:
        today = date.today().isoformat()
        records: list[dict] = []
        if "背完单词" in content:
            records.append(
                {
                    "kind": "daily_task",
                    "title": "背单词",
                    "content": "今天背完单词了",
                    "status": "done",
                    "occurred_on": today,
                    "due_at": None,
                    "confidence": 0.98,
                    "evidence": "今天背完单词了",
                    "payload": {},
                }
            )
        if "论文开头" in content:
            records.append(
                {
                    "kind": "task_progress",
                    "title": "毕业论文",
                    "content": "论文开头已经修改",
                    "status": "active",
                    "occurred_on": today,
                    "due_at": None,
                    "confidence": 0.94,
                    "evidence": "论文开头也改了",
                    "payload": {},
                }
            )
        clarification = None
        if not records:
            clarification = "我没判断出这句要记成任务还是进展，你是想记录哪一件？"
        return {"records": records, "clarification": clarification}


class OpenCodeGoParser:
    def __init__(self, client: OpenCodeGoClient | None = None):
        self.client = client or build_client_or_none()
        if self.client is None:
            raise RuntimeError("OpenCode Go parser requires OPENCODE_API_KEY")
        self.version = f"{self.client.primary_model}:spec-v1.0"

    def parse(self, content: str, session_id: str | None = None) -> dict:
        today = date.today().isoformat()
        prompt = f"""
# 模块身份
你是 MVP 的 C 解析与数据服务中的 LLM 解析器。你只负责把用户原话解析成
records 和 clarification。你不负责生成固定回执，不负责生成教练建议，
不修改数据库，不创建或修改任务状态。

# 其他模块边界
- A：渠道适配与前端，只收集输入和展示结果。
- B：请求编排与教练，负责回执、重复处理、失败降级和教练建议。
- C：你和数据服务，负责解析、校验、落库和查询。

# 输入
当前用户原话：
{content}

当前日期：{today}（Asia/Shanghai）。

# 输出协议
只能输出一个 JSON 对象，顶层必须且只能有：
{{
  "records": [],
  "clarification": null
}}

records 中每条只能包含以下字段：
- kind: task | task_progress | daily_task
- title: 可空字符串
- content: 必填，保留动作或事实；不要在这里写系统解释
- status: 按 kind 严格取值
  - task: pending | in_progress | done | cancelled | revoked
  - daily_task: pending | done | cancelled | revoked
  - task_progress: active | revoked
- occurred_on: YYYY-MM-DD 或 null
- due_at: RFC3339 或 null
- confidence: 0 到 1 之间的数字
- evidence: 原文中的连续片段
- payload: 对象，可放扩展字段

# 业务规则
1. 完成一次习惯动作生成 daily_task，状态必须是 done。
2. 对已有任务的局部进展生成 task_progress，状态必须是 active；不得把整项任务标完成。
3. 生活感受、情绪、生活片段不生成 tasks；它们保留在 raw_events.content 原话中。
4. 没有证据的日期、时间、对象、状态必须留空或要求 clarification，不得猜测。
5. 一句话可以生成多条 records。
6. 如果无法判断是否要形成记录，records 为空并给出 clarification。
7. 只输出合法 JSON，不要 Markdown、代码围栏、解释或前后缀。

# 示例
输入：今天背完单词了，论文开头也改了，跟朋友聊完没那么焦虑了。
输出：
{{
  "records": [
    {{
      "kind": "daily_task",
      "title": "背单词",
      "content": "今天背完单词了",
      "status": "done",
      "occurred_on": "{today}",
      "due_at": null,
      "confidence": 0.98,
      "evidence": "今天背完单词了",
      "payload": {{}}
    }},
    {{
      "kind": "task_progress",
      "title": "毕业论文",
      "content": "论文开头已经修改",
      "status": "active",
      "occurred_on": "{today}",
      "due_at": null,
      "confidence": 0.94,
      "evidence": "论文开头也改了",
      "payload": {{}}
    }}
  ],
  "clarification": null
}}
""".strip()
        failures: list[str] = []
        for model in self.client.models:
            try:
                response = self.client.complete(
                    [
                        {
                            "role": "system",
                            "content": "你只输出符合协议的 JSON 对象。",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    model=model,
                    session_id=session_id,
                    temperature=0,
                    max_tokens=4000,
                    reasoning_effort="none" if model == "hy4-flash-free" else None,
                )
                text = response["content"]
                match = re.search(r"\{[\s\S]*\}", text)
                if not match:
                    raise RuntimeError(
                        f"model={model} did not return a JSON object "
                        f"(finish_reason={response['finish_reason']}, "
                        f"content={text[:300]!r})"
                    )
                result = json.loads(match.group(0))
                return validate_parse_result(result)
            except Exception as exc:
                failures.append(str(exc))
        raise RuntimeError("OpenCode Go parse failed: " + " | ".join(failures))


def validate_parse_result(result: dict) -> dict:
    if not isinstance(result, dict):
        raise ValueError("parse result must be an object")
    if set(result) != {"records", "clarification"}:
        raise ValueError("parse result must contain exactly records and clarification")
    records = result["records"]
    clarification = result["clarification"]
    if not isinstance(records, list):
        raise ValueError("records must be a list")
    if clarification is not None and not isinstance(clarification, str):
        raise ValueError("clarification must be null or a string")
    allowed_record_keys = {
        "kind",
        "title",
        "content",
        "status",
        "occurred_on",
        "due_at",
        "confidence",
        "evidence",
        "payload",
    }
    for item in records:
        if not isinstance(item, dict):
            raise ValueError("each record must be an object")
        if not set(item).issubset(allowed_record_keys):
            raise ValueError("record contains unsupported fields")
        kind = item.get("kind")
        if kind not in ALLOWED_KINDS:
            raise ValueError(f"unsupported kind: {kind}")
        status = item.get("status")
        if status not in ALLOWED_STATUSES[kind]:
            raise ValueError(f"invalid status {status!r} for kind {kind!r}")
        if not str(item.get("content", "")).strip():
            raise ValueError("record content is required")
        if not str(item.get("evidence", "")).strip():
            raise ValueError("record evidence is required")
        confidence = item.get("confidence")
        if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise ValueError("confidence must be a number between 0 and 1")
        if item.get("occurred_on") is not None and not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}", str(item["occurred_on"])
        ):
            raise ValueError("occurred_on must be YYYY-MM-DD or null")
        if item.get("due_at") is not None and not isinstance(item["due_at"], str):
            raise ValueError("due_at must be a string or null")
        if not isinstance(item.get("payload", {}), dict):
            raise ValueError("payload must be an object")
    return {"records": records, "clarification": clarification}


def build_parser() -> Parser:
    client = build_client_or_none()
    if client is None:
        return MockParser()
    return OpenCodeGoParser(client)

