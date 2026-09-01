"""SQLite FTS5 全文检索"""
from __future__ import annotations

from sqlalchemy import text

from backend.storage.database import get_session


def upsert_chunks(
  chunk_ids: list[str],
  literature_ids: list[str],
  workspace_ids: list[str],
  section_keys: list[str],
  contents: list[str],
) -> None:
  if not chunk_ids:
    return
  with get_session() as session:
    for cid in chunk_ids:
      session.execute(
        text("DELETE FROM literature_chunks_fts WHERE chunk_id = :cid"),
        {"cid": cid},
      )
    for cid, lid, wid, sk, content in zip(
      chunk_ids, literature_ids, workspace_ids, section_keys, contents
    ):
      session.execute(
        text("""
          INSERT INTO literature_chunks_fts
            (chunk_id, literature_id, workspace_id, section_key, content)
          VALUES (:chunk_id, :literature_id, :workspace_id, :section_key, :content)
        """),
        {
          "chunk_id": cid,
          "literature_id": lid,
          "workspace_id": wid,
          "section_key": sk,
          "content": content,
        },
      )
    session.commit()


def delete_by_literature(literature_id: str) -> None:
  with get_session() as session:
    session.execute(
      text("DELETE FROM literature_chunks_fts WHERE literature_id = :lid"),
      {"lid": literature_id},
    )
    session.commit()


def delete_by_workspace(workspace_id: str) -> None:
  with get_session() as session:
    session.execute(
      text("DELETE FROM literature_chunks_fts WHERE workspace_id = :wid"),
      {"wid": workspace_id},
    )
    session.commit()


def search(
  workspace_id: str,
  query: str,
  *,
  top_k: int = 20,
  literature_ids: list[str] | None = None,
  section_keys: list[str] | None = None,
) -> list[dict]:
  if not query.strip():
    return []

  terms = [t.strip() for t in query.split() if t.strip()]
  if not terms:
    return []
  match_expr = " OR ".join(f'"{t}"' for t in terms)

  filters = ["workspace_id = :workspace_id"]
  params: dict = {"workspace_id": workspace_id, "match": match_expr, "limit": top_k}

  if literature_ids:
    placeholders = ", ".join(f":lid{i}" for i in range(len(literature_ids)))
    filters.append(f"literature_id IN ({placeholders})")
    for i, lid in enumerate(literature_ids):
      params[f"lid{i}"] = lid

  if section_keys:
    placeholders = ", ".join(f":sk{i}" for i in range(len(section_keys)))
    filters.append(f"section_key IN ({placeholders})")
    for i, sk in enumerate(section_keys):
      params[f"sk{i}"] = sk

  where_clause = " AND ".join(filters)
  sql = f"""
    SELECT chunk_id, literature_id, section_key, content,
           bm25(literature_chunks_fts) AS rank
    FROM literature_chunks_fts
    WHERE literature_chunks_fts MATCH :match
      AND {where_clause}
    ORDER BY rank
    LIMIT :limit
  """

  with get_session() as session:
    rows = session.execute(text(sql), params).mappings().all()

  return [
    {
      "chunk_id": row["chunk_id"],
      "literature_id": row["literature_id"],
      "section_key": row["section_key"],
      "content": row["content"],
      "score": float(-row["rank"]) if row["rank"] is not None else 0.0,
      "source": "fts",
    }
    for row in rows
  ]
