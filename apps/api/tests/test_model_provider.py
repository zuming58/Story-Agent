from __future__ import annotations

import pytest

from story_agent_api.model_provider import ModelProviderError, OpenAICompatibleModelProvider


@pytest.mark.anyio
async def test_stream_retry_does_not_duplicate_an_emitted_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = OpenAICompatibleModelProvider("https://example.test", "secret", 5, max_retries=1)
    attempts = 0

    async def partial_then_fail(_payload: dict):
        nonlocal attempts
        attempts += 1
        yield "prefix"
        raise ModelProviderError("network_error", "lost", retryable=True)

    monkeypatch.setattr(provider, "_stream_once", partial_then_fail)
    received: list[str] = []
    with pytest.raises(ModelProviderError):
        async for delta in provider.stream_chat({}):
            received.append(delta)

    assert attempts == 1
    assert received == ["prefix"]
