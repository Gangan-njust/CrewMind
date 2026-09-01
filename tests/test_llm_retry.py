"""LLM 客户端失败自动重试测试"""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.llm.client import DeepSeekClient


def _client(max_retries=2, backoff=0.0) -> DeepSeekClient:
  return DeepSeekClient(
    api_key="test-key",
    base_url="https://llm.test",
    model="test-model",
    max_retries=max_retries,
    retry_backoff=backoff,
  )


def _status_response(status: int) -> httpx.Response:
  return httpx.Response(status, request=httpx.Request("POST", "https://llm.test"))


def _ok_response(content: str = "你好") -> httpx.Response:
  return httpx.Response(
    200,
    json={"choices": [{"message": {"content": content}}]},
    request=httpx.Request("POST", "https://llm.test"),
  )


class TestSyncRetry:
  @pytest.mark.asyncio
  async def test_retries_on_rate_limit_then_succeeds(self):
    client = _client(max_retries=2)
    mock_client = MagicMock()
    mock_client.post = AsyncMock(side_effect=[_status_response(429), _ok_response("最终内容")])

    with patch("backend.llm.client.httpx.AsyncClient") as mock_cls:
      mock_cls.return_value.__aenter__.return_value = mock_client
      content = await client.chat([{"role": "user", "content": "hi"}])

    assert content == "最终内容"
    assert mock_client.post.await_count == 2

  @pytest.mark.asyncio
  async def test_retries_on_network_error(self):
    client = _client(max_retries=1)
    mock_client = MagicMock()
    mock_client.post = AsyncMock(side_effect=[httpx.ConnectError("connection refused"), _ok_response("ok")])

    with patch("backend.llm.client.httpx.AsyncClient") as mock_cls:
      mock_cls.return_value.__aenter__.return_value = mock_client
      content = await client.chat([{"role": "user", "content": "hi"}])

    assert content == "ok"

  @pytest.mark.asyncio
  async def test_gives_up_after_max_retries(self):
    client = _client(max_retries=2)
    mock_client = MagicMock()
    mock_client.post = AsyncMock(side_effect=httpx.ConnectError("down"))

    with patch("backend.llm.client.httpx.AsyncClient") as mock_cls:
      mock_cls.return_value.__aenter__.return_value = mock_client
      with pytest.raises(httpx.ConnectError):
        await client.chat([{"role": "user", "content": "hi"}])

    # 1 次原始请求 + 2 次重试
    assert mock_client.post.await_count == 3

  @pytest.mark.asyncio
  async def test_does_not_retry_business_error(self):
    client = _client(max_retries=2)
    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=_status_response(400))

    with patch("backend.llm.client.httpx.AsyncClient") as mock_cls:
      mock_cls.return_value.__aenter__.return_value = mock_client
      with pytest.raises(httpx.HTTPStatusError):
        await client.chat([{"role": "user", "content": "hi"}])

    assert mock_client.post.await_count == 1

  @pytest.mark.asyncio
  async def test_does_not_retry_when_no_api_key(self, monkeypatch):
    from backend.config import settings

    monkeypatch.setattr(settings, "deepseek_api_key", "")
    client = DeepSeekClient(api_key="", max_retries=2)
    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
      await client.chat([{"role": "user", "content": "hi"}])


class TestStreamRetry:
  @pytest.mark.asyncio
  async def test_retries_before_first_chunk(self):
    client = _client(max_retries=1)
    calls = {"n": 0}

    async def stream_attempt():
      calls["n"] += 1
      if calls["n"] == 1:
        raise httpx.ConnectError("connection lost")
      yield 'data: {"choices":[{"delta":{"content":"你好"}}]}'
      yield "data: [DONE]"

    mock_response = MagicMock()
    mock_response.aiter_lines = stream_attempt
    mock_client = MagicMock()
    mock_client.stream.return_value.__aenter__.return_value = mock_response

    with patch("backend.llm.client.httpx.AsyncClient") as mock_cls:
      mock_cls.return_value.__aenter__.return_value = mock_client
      stream = await client.chat([{"role": "user", "content": "hi"}], stream=True)
      chunks = [chunk async for chunk in stream]

    assert chunks == ["你好"]
    assert mock_client.stream.call_count == 2

  @pytest.mark.asyncio
  async def test_mid_stream_failure_raises_without_retry(self):
    client = _client(max_retries=2)

    async def stream_attempt():
      yield 'data: {"choices":[{"delta":{"content":"部分"}}]}'
      raise httpx.ConnectError("disconnect")

    mock_response = MagicMock()
    mock_response.aiter_lines = stream_attempt
    mock_client = MagicMock()
    mock_client.stream.return_value.__aenter__.return_value = mock_response

    with patch("backend.llm.client.httpx.AsyncClient") as mock_cls:
      mock_cls.return_value.__aenter__.return_value = mock_client
      stream = await client.chat([{"role": "user", "content": "hi"}], stream=True)
      with pytest.raises(httpx.ConnectError):
        chunks = [chunk async for chunk in stream]
        assert chunks == ["部分"]

    # 已产出内容后断流，不重复流式输出，仅一次请求
    assert mock_client.stream.call_count == 1
