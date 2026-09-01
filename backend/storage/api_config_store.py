"""用户自定义 LLM API 配置存储（未配置时回退系统 Key）"""
from datetime import datetime

from backend.storage.database import get_session
from backend.storage.models import UserApiConfig


def get_user_api_config(user_id: str) -> dict | None:
  """返回用户的自定义 API 配置；未配置返回 None"""
  if not user_id:
    return None
  with get_session() as session:
    row = session.get(UserApiConfig, user_id)
    if not row:
      return None
    return {
      "user_id": row.user_id,
      "api_key": row.api_key,
      "base_url": row.base_url,
      "model": row.model,
      "updated_at": row.updated_at.isoformat(),
    }


def get_user_api_key(user_id: str) -> str:
  cfg = get_user_api_config(user_id)
  return ((cfg or {}).get("api_key") or "").strip()


def save_user_api_config(
  user_id: str,
  api_key: str = "",
  base_url: str = "",
  model: str = "",
) -> dict:
  """保存用户自定义 API 配置；返回脱敏后的配置摘要"""
  with get_session() as session:
    row = session.get(UserApiConfig, user_id)
    now = datetime.now()
    if not row:
      row = UserApiConfig(user_id=user_id, api_key="", base_url="", model="", updated_at=now)
      session.add(row)
    row.api_key = (api_key or "").strip()
    row.base_url = (base_url or "").strip()
    row.model = (model or "").strip()
    row.updated_at = now
    session.commit()
    session.refresh(row)
    return {
      "user_id": row.user_id,
      "has_api_key": bool(row.api_key),
      "base_url": row.base_url,
      "model": row.model,
      "updated_at": row.updated_at.isoformat(),
    }


def clear_user_api_config(user_id: str) -> None:
  """清空用户自定义 API 配置（恢复使用系统 Key）"""
  with get_session() as session:
    row = session.get(UserApiConfig, user_id)
    if row:
      session.delete(row)
      session.commit()
