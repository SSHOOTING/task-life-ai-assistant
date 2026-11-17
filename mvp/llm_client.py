from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from uuid import uuid4


class OpenCodeGoClient:
    """Small OpenAI-compatible client for OpenCode Go.

    Credentials come only from OPENCODE_API_KEY. The client never logs request
    headers or returns the key in an exception.
    """

    def __init__(self) -> None:
        self.base_url = os.environ.get(
            "OPENCODE_GO_BASE_URL",
            "https://opencode.ai/inference/go/openai/v1",
        ).rstrip("/")
        self.api_key = os.environ.get("OPENCODE_API_KEY", "")
        self.primary_model = os.environ.get(
            "OPENCODE_GO_MODEL", "hy4-flash-free"
        )
        self.fallback_model = os.environ.get(
            "OPENCODE_GO_FALLBACK_MODEL", "longcat-2.5-free"
        )
        if not self.api_key:
            raise RuntimeError("OpenCode Go requires OPENCODE_API_KEY")
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({})
        )

    @property
    def models(self) -> list[str]:
        values = [self.primary_model]
        if self.fallback_model and self.fallback_model not in values:
            values.append(self.fallback_model)
        return values

    def complete(
        self,
        messages: list[dict],
        *,
        model: str,
        session_id: str | None = None,
        temperature: float = 0,
        max_tokens: int = 4000,
        reasoning_effort: str | None = None,
    ) -> dict:
        payload: dict = {
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "User-Agent": "task-life-ai-assistant/1.0",
                "x-opencode-session": session_id or str(uuid4()),
            },
            method="POST",
        )
        try:
            with self.opener.open(request, timeout=120) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            raise RuntimeError(f"OpenCode Go HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"OpenCode Go request failed: {exc}") from exc

        choice = body["choices"][0]
        return {
            "model": body.get("model", model),
            "content": (choice["message"].get("content") or "").strip(),
            "finish_reason": choice.get("finish_reason"),
            "usage": body.get("usage", {}),
        }


def build_client_or_none() -> OpenCodeGoClient | None:
    if os.environ.get("LLM_MODE", "").strip().lower() == "mock":
        return None
    if not os.environ.get("OPENCODE_API_KEY"):
        return None
    return OpenCodeGoClient()

