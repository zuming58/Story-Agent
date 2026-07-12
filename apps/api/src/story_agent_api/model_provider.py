from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import httpx


class ModelProviderError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass
class ModelStreamResult:
    text: str = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    actual_model: str | None = None


@dataclass
class ModelStreamChunk:
    text: str = ""
    done: bool = False
    usage: dict[str, int] | None = None
    model: str | None = None


@dataclass
class OpenAICompatibleModelProvider:
    base_url: str
    api_key: str
    timeout_seconds: int
    max_retries: int = 1
    _last_result: ModelStreamResult = field(default_factory=ModelStreamResult, init=False)

    @property
    def last_result(self) -> ModelStreamResult:
        return self._last_result

    async def stream_chat(self, payload: dict[str, Any]) -> AsyncIterator[str]:
        attempts = max(1, min(self.max_retries + 1, 2))
        last_error: ModelProviderError | None = None
        for attempt in range(attempts):
            self._last_result = ModelStreamResult()
            try:
                async for text in self._stream_once(payload):
                    yield text
                return
            except ModelProviderError as exc:
                last_error = exc
                if not exc.retryable or attempt >= attempts - 1:
                    raise
        if last_error:
            raise last_error

    async def _stream_once(self, payload: dict[str, Any]) -> AsyncIterator[str]:
        request_payload = {**payload, "stream": True, "stream_options": {"include_usage": True}}
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        timeout = httpx.Timeout(self.timeout_seconds, connect=min(self.timeout_seconds, 10))
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", f"{self.base_url.rstrip('/')}/chat/completions", headers=headers, json=request_payload) as response:
                    if response.status_code in {401, 403}:
                        raise ModelProviderError("auth_failed", "模型服务拒绝鉴权。", retryable=False)
                    if response.status_code == 429:
                        raise ModelProviderError("rate_limited", "模型服务达到限流。", retryable=True)
                    if response.status_code >= 500:
                        raise ModelProviderError("server_error", f"模型服务返回 HTTP {response.status_code}。", retryable=True)
                    if response.status_code >= 400:
                        raise ModelProviderError("request_failed", f"模型服务返回 HTTP {response.status_code}。", retryable=False)
                    async for line in response.aiter_lines():
                        chunk = self._parse_sse_line(line)
                        if not chunk:
                            continue
                        if chunk.done:
                            return
                        if chunk.model:
                            self._last_result.actual_model = chunk.model
                        if chunk.usage:
                            self._last_result.prompt_tokens = chunk.usage.get("prompt_tokens")
                            self._last_result.completion_tokens = chunk.usage.get("completion_tokens")
                            self._last_result.total_tokens = chunk.usage.get("total_tokens")
                        if chunk.text:
                            self._last_result.text += chunk.text
                            yield chunk.text
        except httpx.TimeoutException as exc:
            raise ModelProviderError("timeout", "模型调用超时。", retryable=True) from exc
        except httpx.RequestError as exc:
            raise ModelProviderError("network_error", "无法连接模型服务。", retryable=True) from exc

    def _parse_sse_line(self, line: str) -> ModelStreamChunk | None:
        if not line or line.startswith(":"):
            return None
        if line.startswith("data:"):
            raw = line[5:].strip()
        else:
            raw = line.strip()
        if not raw:
            return None
        if raw == "[DONE]":
            return ModelStreamChunk(done=True)
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise ModelProviderError("invalid_response", "模型服务返回了非法流式 JSON。", retryable=False) from exc
        usage = data.get("usage") if isinstance(data, dict) else None
        text = ""
        choices = data.get("choices") if isinstance(data, dict) else None
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                delta = first.get("delta")
                if isinstance(delta, dict):
                    content = delta.get("content")
                    if isinstance(content, str):
                        text = content
                finish_reason = first.get("finish_reason")
                if finish_reason == "length":
                    raise ModelProviderError("content_truncated", "模型输出被截断。", retryable=False)
        model = data.get("model") if isinstance(data, dict) and isinstance(data.get("model"), str) else None
        return ModelStreamChunk(text=text, usage=usage if isinstance(usage, dict) else None, model=model)
