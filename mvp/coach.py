from __future__ import annotations

import json

from .llm_client import OpenCodeGoClient, build_client_or_none


class CoachAgent:
    """B's coach module. It only advises; it never writes domain data."""

    def __init__(self, client: OpenCodeGoClient | None = None):
        self.client = client or build_client_or_none()

    def advise(self, *, user_id: str, context: dict) -> str | None:
        if self.client is None:
            return None
        prompt = f"""
你是 MVP 的 B 教练 Agent。你只根据 C 提供的最近上下文，给用户一句可执行的
下一步建议。你不创建、修改、撤销任何任务，不判断任务写入是否正确，不输出 JSON，
不评价用户的自律、能力或情绪。没有足够上下文时只给一个很小的中立建议。

用户：{user_id}
最近上下文：
{json.dumps(context, ensure_ascii=False, indent=2)}
""".strip()
        last_error: Exception | None = None
        for model in self.client.models:
            try:
                response = self.client.complete(
                    [
                        {
                            "role": "system",
                            "content": "你只返回一段简短的中文建议，不修改任何数据。",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    model=model,
                    session_id=f"coach:{user_id}",
                    temperature=0.2,
                    max_tokens=800,
                    reasoning_effort="none" if model == "hy4-flash-free" else None,
                )
                text = response["content"].strip()
                if text:
                    return text
                last_error = RuntimeError("coach returned empty text")
            except Exception as exc:
                last_error = exc
        if last_error:
            return None
        return None

