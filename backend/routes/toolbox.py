"""工具箱 API：运行记录统计、调用日志与用户 API 配置"""
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.auth import get_current_user
from backend.config import settings
from backend.storage import api_config_store, usage_store
from backend.storage.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/toolbox", tags=["toolbox"])


class ApiConfigRequest(BaseModel):
  api_key: str = Field("", max_length=512, description="用户自己的 API Key（留空则继续使用系统 Key）")
  base_url: str = Field("", max_length=256, description="OpenAI 兼容接口地址，留空使用系统默认")
  model: str = Field("", max_length=128, description="模型名称，留空使用系统默认")


# ── 运行记录与调用日志 ─────────────────────────────────────────

@router.get("/summary")
async def get_summary(current_user: User = Depends(get_current_user)):
  return usage_store.get_usage_summary(current_user.id)


@router.get("/runs")
async def list_runs(
  source: str | None = Query(None, description="按来源过滤：workflow/literature/writing/experiment"),
  limit: int = Query(100, ge=1, le=500),
  offset: int = Query(0, ge=0),
  current_user: User = Depends(get_current_user),
):
  return usage_store.list_runs(current_user.id, source=source, limit=limit, offset=offset)


@router.get("/runs/{run_id}")
async def get_run_detail(
  run_id: str,
  current_user: User = Depends(get_current_user),
):
  calls = usage_store.list_run_calls(current_user.id, run_id)
  if not calls:
    raise HTTPException(404, "未找到该运行记录")
  return {"run_id": run_id, "calls": calls}


@router.get("/logs")
async def list_logs(
  limit: int = Query(200, ge=1, le=500),
  offset: int = Query(0, ge=0),
  current_user: User = Depends(get_current_user),
):
  return usage_store.list_usage_logs(current_user.id, limit=limit, offset=offset)


# ── 用户 API 配置 ─────────────────────────────────────────────

@router.get("/api-config")
async def get_api_config(current_user: User = Depends(get_current_user)):
  cfg = api_config_store.get_user_api_config(current_user.id)
  if not cfg:
    return {
      "has_api_key": False,
      "base_url": "",
      "model": "",
      "updated_at": None,
      "using_system_key": True,
    }
  return {
    "has_api_key": bool(cfg["api_key"]),
    "base_url": cfg["base_url"],
    "model": cfg["model"],
    "updated_at": cfg["updated_at"],
    "using_system_key": not bool(cfg["api_key"]),
  }


@router.put("/api-config")
async def save_api_config(req: ApiConfigRequest, current_user: User = Depends(get_current_user)):
  saved = api_config_store.save_user_api_config(
    current_user.id,
    api_key=req.api_key,
    base_url=req.base_url,
    model=req.model,
  )
  return {
    **saved,
    "using_system_key": not saved["has_api_key"],
  }


@router.delete("/api-config")
async def clear_api_config(current_user: User = Depends(get_current_user)):
  api_config_store.clear_user_api_config(current_user.id)
  return {"status": "cleared", "using_system_key": True}


@router.post("/api-config/test")
async def test_api_config(req: ApiConfigRequest, current_user: User = Depends(get_current_user)):
  """用给定（或已保存、或系统）Key 发起一次最小调用，验证连通性。"""
  cfg = api_config_store.get_user_api_config(current_user.id) or {}
  api_key = (req.api_key or "").strip() or (cfg.get("api_key") or "").strip() or settings.deepseek_api_key
  base_url = (req.base_url or "").strip() or (cfg.get("base_url") or "").strip() or settings.deepseek_base_url
  model = (req.model or "").strip() or (cfg.get("model") or "").strip() or settings.deepseek_model

  if not api_key:
    raise HTTPException(400, "未配置 API Key（系统 Key 与用户 Key 均为空）")

  url = f"{base_url.rstrip('/')}/v1/chat/completions"
  payload = {
    "model": model,
    "messages": [{"role": "user", "content": "你好，请仅回复：OK"}],
    "max_tokens": 8,
    "temperature": 0,
    "stream": False,
  }
  try:
    async with httpx.AsyncClient(timeout=30.0) as client:
      resp = await client.post(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
      )
      if resp.status_code >= 400:
        detail = (resp.text or "")[:200]
        raise HTTPException(400, f"API 连接失败（HTTP {resp.status_code}）：{detail}")
      data = resp.json()
      reply = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
      return {
        "ok": True,
        "message": "连接成功",
        "model": model,
        "reply": (reply or "")[:50],
      }
  except HTTPException:
    raise
  except Exception as e:
    raise HTTPException(400, f"API 连接失败：{e}")
