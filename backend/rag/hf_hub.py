"""HuggingFace Hub 下载配置（镜像、超时、代理）"""
from __future__ import annotations

import logging
import os

from backend.config import PROJECT_ROOT, settings

logger = logging.getLogger(__name__)

_configured = False


def configure_hf_hub() -> None:
  """在加载 fastembed / huggingface_hub 模型前调用一次。"""
  global _configured
  if _configured:
    return

  cache_dir = (PROJECT_ROOT / settings.rag_dir / "fastembed_cache").resolve()
  cache_dir.mkdir(parents=True, exist_ok=True)
  os.environ.setdefault("FASTEMBED_CACHE_PATH", cache_dir.as_posix())
  os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

  endpoint = (settings.hf_endpoint or os.environ.get("HF_ENDPOINT", "")).strip()
  if endpoint:
    os.environ["HF_ENDPOINT"] = endpoint.rstrip("/")
    logger.info("HuggingFace 镜像: %s", os.environ["HF_ENDPOINT"])

  timeout = settings.hf_hub_download_timeout
  if timeout > 0:
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", str(timeout))

  _configured = True


def format_model_download_error(model_name: str, error: Exception) -> str:
  endpoint = os.environ.get("HF_ENDPOINT", "https://huggingface.co")
  return (
    f"无法下载/加载模型「{model_name}」: {error}. "
    f"当前 HF_ENDPOINT={endpoint}。若网络超时，请在 .env 设置 "
    f"HF_ENDPOINT=https://hf-mirror.com 或配置 HTTP_PROXY/HTTPS_PROXY 后重启，"
    f"并运行: py -3 scripts/preload_rag_models.py"
  )
