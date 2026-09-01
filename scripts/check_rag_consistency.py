#!/usr/bin/env python3
"""校验 Chroma 向量库与 SQLite literature_chunks 数据一致性

用法:
  py -3 scripts/check_rag_consistency.py [--workspace WS_ID] [--fix]

退出码: 0=一致, 1=存在不一致
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select

from backend.config import settings
from backend.rag import fts_store, vector_store
from backend.storage.database import setup_database, get_session
from backend.storage.models import LiteratureChunkRecord, LiteratureRecord, WorkspaceRecord


def check_workspace(workspace_id: str, *, fix: bool = False) -> list[str]:
  issues: list[str] = []
  with get_session() as session:
    sqlite_ids = set(session.scalars(
      select(LiteratureChunkRecord.id).where(
        LiteratureChunkRecord.workspace_id == workspace_id
      )
    ).all())

  try:
    col = vector_store._get_collection(workspace_id)  # noqa: SLF001
    chroma_data = col.get(include=[])
    chroma_ids = set(chroma_data.get("ids") or [])
  except Exception as e:
    issues.append(f"Chroma collection 读取失败: {e}")
    chroma_ids = set()

  only_sqlite = sqlite_ids - chroma_ids
  only_chroma = chroma_ids - sqlite_ids

  if only_sqlite:
    issues.append(f"仅 SQLite 存在 {len(only_sqlite)} 条 chunk")
  if only_chroma:
    issues.append(f"仅 Chroma 存在 {len(only_chroma)} 条 chunk")

  if fix and (only_sqlite or only_chroma):
    if only_chroma:
      vector_store.delete_chunks(workspace_id, list(only_chroma))
      issues.append(f"已清理 Chroma 孤立 chunk {len(only_chroma)} 条")
    if only_sqlite:
      for lit_id in _literature_ids_for_chunks(only_sqlite):
        from backend.rag.indexer import index_literature
        try:
          index_literature(lit_id, force=True)
          issues.append(f"已重新索引文献 {lit_id}")
        except Exception as e:
          issues.append(f"重新索引失败 {lit_id}: {e}")

  return issues


def _literature_ids_for_chunks(chunk_ids: set[str]) -> set[str]:
  with get_session() as session:
    rows = session.scalars(
      select(LiteratureChunkRecord.literature_id).where(
        LiteratureChunkRecord.id.in_(chunk_ids)
      )
    ).all()
  return set(rows)


def main() -> int:
  parser = argparse.ArgumentParser(description="RAG 数据一致性校验")
  parser.add_argument("--workspace", help="指定工作空间 ID，默认检查全部")
  parser.add_argument("--fix", action="store_true", help="尝试修复不一致")
  args = parser.parse_args()

  setup_database()
  settings.ensure_dirs()

  with get_session() as session:
    if args.workspace:
      ws_ids = [args.workspace]
    else:
      ws_ids = session.scalars(select(WorkspaceRecord.id)).all()

  has_issues = False
  for ws_id in ws_ids:
    lit_count = 0
    with get_session() as session:
      lit_count = session.scalar(
        select(func.count()).select_from(LiteratureRecord).where(
          LiteratureRecord.workspace_id == ws_id
        )
      ) or 0
    if lit_count == 0:
      continue
    issues = check_workspace(ws_id, fix=args.fix)
    if issues:
      has_issues = True
      print(f"\n工作空间 {ws_id}:")
      for msg in issues:
        print(f"  - {msg}")
    else:
      print(f"工作空间 {ws_id}: OK")

  if has_issues:
    print("\n存在不一致，请检查上述项。")
    return 1
  print("\n全部一致。")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
