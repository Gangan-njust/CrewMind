"""DeepSeek API 连接与调用封装"""
import json
import logging
from typing import Any, AsyncIterator

import httpx

from backend.config import settings

from backend.utils.text import sanitize_deep

logger = logging.getLogger(__name__)


class DeepSeekClient:
    """DeepSeek 大模型客户端，供所有 Agent 复用"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
    ):
        self._api_key_override = api_key
        self.base_url = (base_url or settings.deepseek_base_url).rstrip("/")
        self.model = model or settings.deepseek_model
        self.temperature = temperature if temperature is not None else settings.default_temperature

    @property
    def api_key(self) -> str:
        """每次读取最新配置，避免启动时缓存空值"""
        return self._api_key_override or settings.deepseek_api_key

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        stream: bool = False,
        use_reasoning: bool = False,
    ) -> str | AsyncIterator[str]:
        """调用 DeepSeek Chat Completions API"""
        if not self.api_key:
            raise ValueError("未配置 DEEPSEEK_API_KEY，请在 .env 文件中设置")

        selected_model = model or (
            settings.deepseek_reasoning_model if use_reasoning else self.model
        )
        payload: dict[str, Any] = sanitize_deep({
            "model": selected_model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.temperature,
            "stream": stream,
        })

        url = f"{self.base_url}/v1/chat/completions"

        if stream:
            return self._stream_chat(url, payload)
        return await self._sync_chat(url, payload)

    async def _sync_chat(self, url: str, payload: dict) -> str:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(url, headers=self._headers(), json=payload)
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            logger.debug("LLM response length: %d", len(content))
            return content

    async def _stream_chat(self, url: str, payload: dict) -> AsyncIterator[str]:
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST", url, headers=self._headers(), json=payload
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    chunk = line[6:]
                    if chunk.strip() == "[DONE]":
                        break
                    try:
                        data = json.loads(chunk)
                        delta = data["choices"][0].get("delta", {})
                        if content := delta.get("content"):
                            yield content
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue


# 全局单例
llm_client = DeepSeekClient()
