"""Embedding 封装：fastembed 默认，可选 OpenAI 兼容 API"""
from __future__ import annotations

import logging
from typing import Protocol

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

_embedder_instance: "Embedder | None" = None


class Embedder(Protocol):
  def embed(self, texts: list[str]) -> list[list[float]]: ...
  def embed_query(self, query: str) -> list[float]: ...


class FastEmbedEmbedder:
  def __init__(self, model_name: str | None = None):
    from fastembed import TextEmbedding

    from backend.rag.hf_hub import configure_hf_hub, format_model_download_error

    name = model_name or settings.embedding_model
    configure_hf_hub()
    try:
      self._model = TextEmbedding(model_name=name)
    except Exception as e:
      msg = format_model_download_error(name, e)
      logger.error(msg)
      raise RuntimeError(msg) from e
    logger.info("已加载 fastembed 模型: %s", name)

  def embed(self, texts: list[str]) -> list[list[float]]:
    if not texts:
      return []
    # Chroma 要求 Python float；fastembed 返回的 ndarray 经 list() 后仍是 np.float32
    return [list(map(float, v)) for v in self._model.embed(texts)]

  def embed_query(self, query: str) -> list[float]:
    return self.embed([query])[0]


class OpenAIEmbedder:
  def __init__(self):
    if not settings.embedding_api_key:
      raise ValueError("EMBEDDING_API_KEY 未配置")
    self._api_key = settings.embedding_api_key
    self._base_url = (settings.embedding_base_url or "https://api.openai.com/v1").rstrip("/")
    self._model = settings.embedding_model

  def _request(self, texts: list[str]) -> list[list[float]]:
    with httpx.Client(timeout=60.0) as client:
      resp = client.post(
        f"{self._base_url}/embeddings",
        headers={"Authorization": f"Bearer {self._api_key}"},
        json={"model": self._model, "input": texts},
      )
      resp.raise_for_status()
      data = resp.json()["data"]
      data.sort(key=lambda x: x["index"])
      return [item["embedding"] for item in data]

  def embed(self, texts: list[str]) -> list[list[float]]:
    if not texts:
      return []
    return self._request(texts)

  def embed_query(self, query: str) -> list[float]:
    return self.embed([query])[0]


def get_embedder() -> Embedder:
  global _embedder_instance
  if _embedder_instance is None:
    provider = (settings.embedding_provider or "fastembed").lower()
    if provider == "openai":
      _embedder_instance = OpenAIEmbedder()
    else:
      _embedder_instance = FastEmbedEmbedder()
  return _embedder_instance
