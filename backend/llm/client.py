"""DeepSeek API 连接与调用封装（支持按用户回退 Key、用量统计）"""
import asyncio
import json
import logging
import time
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, AsyncIterator

import httpx

from backend.config import settings

from backend.utils.text import sanitize_deep

logger = logging.getLogger(__name__)

# 可重试的瞬时故障 HTTP 状态码（限流、服务端过载/网关错误）
_RETRIABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})


def _is_retriable_error(exc: Exception) -> bool:
    """判断异常是否属于可重试的瞬时故障。"""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRIABLE_STATUS_CODES
    return isinstance(exc, (httpx.TransportError, httpx.TimeoutException))


@dataclass
class LLMRunContext:
    """当前请求/任务内的 LLM 调用上下文：定位用户与归属运行。"""

    user_id: str | None = None
    run_id: str | None = None
    source: str = "workflow"


_llm_context_var: ContextVar[LLMRunContext | None] = ContextVar("llm_run_context", default=None)


def set_llm_run_context(
    user_id: str | None = None,
    run_id: str | None = None,
    source: str = "workflow",
) -> LLMRunContext:
    """在当前异步上下文中设置 LLM 调用上下文（contextvars 会随 asyncio 任务传递）。"""
    ctx = LLMRunContext(user_id=user_id, run_id=run_id, source=source)
    _llm_context_var.set(ctx)
    return ctx


def get_llm_run_context() -> LLMRunContext | None:
    return _llm_context_var.get()


class DeepSeekClient:
    """DeepSeek 大模型客户端，供所有 Agent 复用（含失败自动重试、按用户回退 Key、用量统计）"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_retries: int | None = None,
        retry_backoff: float | None = None,
    ):
        self._api_key_override = api_key
        self._base_url_override = base_url
        self._model_override = model
        self.temperature = temperature if temperature is not None else settings.default_temperature
        self.max_retries = max(0, max_retries if max_retries is not None else settings.llm_max_retries)
        self.retry_backoff = max(
            0.0, retry_backoff if retry_backoff is not None else settings.llm_retry_backoff
        )

    def _user_config(self) -> dict | None:
        """读取当前上下文对应用户的自定义 API 配置；无上下文时返回 None（用系统 Key）。"""
        ctx = get_llm_run_context()
        if not ctx or not ctx.user_id:
            return None
        try:
            from backend.storage.api_config_store import get_user_api_config

            return get_user_api_config(ctx.user_id)
        except Exception:
            logger.exception("读取用户 API 配置失败，回退系统配置")
            return None

    @property
    def api_key(self) -> str:
        """优先使用用户自定义 Key，其次构造参数，最后回退系统 Key（每次读取最新配置）。"""
        if self._api_key_override:
            return self._api_key_override
        cfg = self._user_config()
        if cfg and cfg.get("api_key"):
            return cfg["api_key"]
        return settings.deepseek_api_key

    @property
    def base_url(self) -> str:
        if self._base_url_override:
            return self._base_url_override.rstrip("/")
        cfg = self._user_config()
        if cfg and cfg.get("base_url"):
            return cfg["base_url"].rstrip("/")
        return settings.deepseek_base_url.rstrip("/")

    @property
    def model(self) -> str:
        if self._model_override:
            return self._model_override
        cfg = self._user_config()
        if cfg and cfg.get("model"):
            return cfg["model"]
        return settings.deepseek_model

    def _headers(self, api_key: str | None = None) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {api_key or self.api_key}",
            "Content-Type": "application/json",
        }

    def _record_usage(self, *, model: str, usage: dict, duration_ms: int) -> None:
        """记录一次成功 LLM 调用的用量（失败不阻塞主流程）。"""
        ctx = get_llm_run_context()
        if not ctx:
            return
        try:
            from backend.storage.usage_store import log_llm_usage

            log_llm_usage(
                user_id=ctx.user_id,
                run_id=ctx.run_id,
                source=ctx.source,
                model=model,
                prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
                completion_tokens=int(usage.get("completion_tokens", 0) or 0),
                total_tokens=int(usage.get("total_tokens", 0) or 0),
                duration_ms=duration_ms,
            )
        except Exception:
            logger.exception("记录 LLM 用量失败")

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        stream: bool = False,
        use_reasoning: bool = False,
    ) -> str | AsyncIterator[str]:
        """调用 DeepSeek Chat Completions API（瞬时故障自动重试）"""
        if not self.api_key:
            raise ValueError(
                "未配置 DEEPSEEK_API_KEY，请在 .env 文件中设置，"
                "或到「工具箱 → API 配置」填写自己的 Key"
            )

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
            return self._stream_chat(url, payload, model=selected_model)
        return await self._sync_chat(url, payload, model=selected_model)

    def _backoff_seconds(self, attempt: int) -> float:
        """第 attempt 次失败后的退避时间（1.5s, 3s, 6s ...）"""
        return self.retry_backoff * (2 ** attempt)


    async def _sync_chat(self, url: str, payload: dict, *, model: str) -> str:
        start = time.perf_counter()
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    response = await client.post(url, headers=self._headers(), json=payload)
                    response.raise_for_status()
                    data = response.json()
                    content = data["choices"][0]["message"]["content"]
                    duration_ms = int((time.perf_counter() - start) * 1000)
                    self._record_usage(
                        model=model, usage=data.get("usage") or {}, duration_ms=duration_ms
                    )
                    logger.debug("LLM response length: %d", len(content))
                    return content
            except (KeyError, IndexError, TypeError, ValueError) as e:
                # 响应内容解析失败属于业务错误，不重试
                raise
            except Exception as e:
                last_error = e
                if not _is_retriable_error(e):
                    raise
                if attempt >= self.max_retries:
                    break
                wait = self._backoff_seconds(attempt)
                logger.warning(
                    "LLM 调用失败，%.1fs 后重试 (%d/%d): %s",
                    wait, attempt + 1, self.max_retries, e,
                )
                await asyncio.sleep(wait)
        assert last_error is not None
        raise last_error

    async def _stream_chat(self, url: str, payload: dict, *, model: str) -> AsyncIterator[str]:
        """流式调用；尚未产出任何内容前的失败自动重试，中途断流则抛出由任务级重试兜底"""
        start = time.perf_counter()
        last_error: Exception | None = None
        usage: dict = {}
        for attempt in range(self.max_retries + 1):
            yielded_any = False
            try:
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
                                if data.get("usage"):
                                    usage = data["usage"]
                                delta = data["choices"][0].get("delta", {})
                                if content := delta.get("content"):
                                    yielded_any = True
                                    yield content
                            except (json.JSONDecodeError, KeyError, IndexError):
                                continue
                # 正常结束：记录用量（流式用量通常出现在最后一个 chunk）
                duration_ms = int((time.perf_counter() - start) * 1000)
                self._record_usage(model=model, usage=usage, duration_ms=duration_ms)
                return
            except Exception as e:
                last_error = e
                if not _is_retriable_error(e):
                    raise
                # 已向调用方产出过内容则无法干净回退，交由上层任务级重试
                if yielded_any:
                    raise
                if attempt >= self.max_retries:
                    break
                wait = self._backoff_seconds(attempt)
                logger.warning(
                    "LLM 流式调用失败，%.1fs 后重试 (%d/%d): %s",
                    wait, attempt + 1, self.max_retries, e,
                )
                await asyncio.sleep(wait)
        assert last_error is not None
        raise last_error


# 全局单例
llm_client = DeepSeekClient()
