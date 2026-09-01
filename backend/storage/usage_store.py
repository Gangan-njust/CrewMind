"""LLM 调用用量统计存储：记录每次调用的 token 数、耗时、模型等信息"""
import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from backend.storage.database import get_session
from backend.storage.models import LLMUsageLog, WorkflowRecord

logger = logging.getLogger(__name__)


def log_llm_usage(
  *,
  user_id: str | None,
  run_id: str | None,
  source: str,
  model: str,
  prompt_tokens: int,
  completion_tokens: int,
  total_tokens: int,
  duration_ms: int,
) -> None:
  """记录一次成功的 LLM 调用。失败仅记录日志，不影响主流程。"""
  try:
    with get_session() as session:
      session.add(
        LLMUsageLog(
          id=str(uuid.uuid4()),
          user_id=user_id or None,
          run_id=run_id or None,
          source=source or "workflow",
          model=model or "",
          prompt_tokens=prompt_tokens or 0,
          completion_tokens=completion_tokens or 0,
          total_tokens=total_tokens or 0,
          duration_ms=duration_ms or 0,
          created_at=datetime.now(),
        )
      )
      session.commit()
  except Exception:
    logger.exception("记录 LLM 用量失败")


def _run_row_to_dict(row) -> dict:
  return {
    "run_id": row.run_id,
    "source": row.source,
    "scenario": row.scenario,
    "title": row.title,
    "call_count": row.call_count,
    "prompt_tokens": row.prompt_tokens or 0,
    "completion_tokens": row.completion_tokens or 0,
    "total_tokens": row.total_tokens or 0,
    "duration_ms": row.duration_ms or 0,
    "first_at": row.first_at.isoformat() if row.first_at else None,
    "last_at": row.last_at.isoformat() if row.last_at else None,
  }


def list_runs(
  user_id: str,
  source: str | None = None,
  limit: int = 100,
  offset: int = 0,
) -> list[dict]:
  """按 run_id 聚合列出当前用户的运行记录（工作流每次运行为一条）"""
  filters = [LLMUsageLog.user_id == user_id, LLMUsageLog.run_id.isnot(None)]
  if source:
    filters.append(LLMUsageLog.source == source)

  stmt = (
    select(
      LLMUsageLog.run_id,
      LLMUsageLog.source,
      WorkflowRecord.scenario,
      WorkflowRecord.title,
      func.count(LLMUsageLog.id).label("call_count"),
      func.sum(LLMUsageLog.prompt_tokens).label("prompt_tokens"),
      func.sum(LLMUsageLog.completion_tokens).label("completion_tokens"),
      func.sum(LLMUsageLog.total_tokens).label("total_tokens"),
      func.sum(LLMUsageLog.duration_ms).label("duration_ms"),
      func.min(LLMUsageLog.created_at).label("first_at"),
      func.max(LLMUsageLog.created_at).label("last_at"),
    )
    .outerjoin(WorkflowRecord, WorkflowRecord.crew_id == LLMUsageLog.run_id)
    .where(*filters)
    .group_by(LLMUsageLog.run_id, LLMUsageLog.source, WorkflowRecord.scenario, WorkflowRecord.title)
    .order_by(func.max(LLMUsageLog.created_at).desc())
    .limit(limit)
    .offset(offset)
  )
  with get_session() as session:
    rows = session.execute(stmt).all()
    return [_run_row_to_dict(r) for r in rows]


def _log_to_dict(row: LLMUsageLog) -> dict:
  return {
    "id": row.id,
    "user_id": row.user_id,
    "run_id": row.run_id,
    "source": row.source,
    "model": row.model,
    "prompt_tokens": row.prompt_tokens,
    "completion_tokens": row.completion_tokens,
    "total_tokens": row.total_tokens,
    "duration_ms": row.duration_ms,
    "created_at": row.created_at.isoformat(),
  }


def list_run_calls(user_id: str, run_id: str, limit: int = 1000, offset: int = 0) -> list[dict]:
  """某次运行（run_id）内所有 LLM 调用的明细"""
  with get_session() as session:
    rows = session.scalars(
      select(LLMUsageLog)
      .where(LLMUsageLog.user_id == user_id, LLMUsageLog.run_id == run_id)
      .order_by(LLMUsageLog.created_at.asc())
      .limit(limit)
      .offset(offset)
    ).all()
    return [_log_to_dict(r) for r in rows]


def list_usage_logs(user_id: str, limit: int = 200, offset: int = 0) -> list[dict]:
  """最近 LLM 调用日志（不分运行）"""
  with get_session() as session:
    rows = session.scalars(
      select(LLMUsageLog)
      .where(LLMUsageLog.user_id == user_id)
      .order_by(LLMUsageLog.created_at.desc())
      .limit(limit)
      .offset(offset)
    ).all()
    return [_log_to_dict(r) for r in rows]


def _delete_for_test(user_id: str) -> None:
  """清理测试写入的用量日志（仅测试使用）"""
  with get_session() as session:
    rows = session.scalars(
      select(LLMUsageLog).where(LLMUsageLog.user_id == user_id)
    ).all()
    for row in rows:
      session.delete(row)
    session.commit()


def get_usage_summary(user_id: str) -> dict:
  """当前用户累计调用统计"""
  stmt = select(
    func.count(LLMUsageLog.id).label("call_count"),
    func.sum(LLMUsageLog.total_tokens).label("total_tokens"),
    func.sum(LLMUsageLog.prompt_tokens).label("prompt_tokens"),
    func.sum(LLMUsageLog.completion_tokens).label("completion_tokens"),
    func.sum(LLMUsageLog.duration_ms).label("duration_ms"),
  ).where(LLMUsageLog.user_id == user_id)
  with get_session() as session:
    row = session.execute(stmt).one()
    return {
      "call_count": row.call_count or 0,
      "total_tokens": row.total_tokens or 0,
      "prompt_tokens": row.prompt_tokens or 0,
      "completion_tokens": row.completion_tokens or 0,
      "duration_ms": row.duration_ms or 0,
    }
