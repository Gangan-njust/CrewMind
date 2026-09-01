"""文献分块：章节识别 + 滑窗切分（可选语义辅助边界）"""
from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from backend.config import settings
from backend.literature.section_splitter import split_sections

logger = logging.getLogger(__name__)


@dataclass
class TextChunk:
  id: str
  literature_id: str
  workspace_id: str
  section_key: str
  chunk_index: int
  content: str
  content_hash: str
  char_start: int
  char_end: int


def _hash_content(text: str) -> str:
  return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _cosine_similarity(a: list[float], b: list[float]) -> float:
  """余弦相似度；维度不一致或零向量按 0 处理"""
  if not a or not b or len(a) != len(b):
    return 0.0
  dot = sum(x * y for x, y in zip(a, b))
  norm_a = sum(x * x for x in a) ** 0.5
  norm_b = sum(y * y for y in b) ** 0.5
  if norm_a == 0.0 or norm_b == 0.0:
    return 0.0
  return dot / (norm_a * norm_b)


def _compute_para_similarities(text: str, embedder) -> list[float]:
  """计算相邻段落间的 embedding 余弦相似度，返回长度 = 段落数 - 1

  段落数 < 2 或 embedding 失败时返回空列表（由调用方决定回退）。
  """
  paras = _paragraph_split(text)
  if len(paras) < 2:
    return []
  try:
    vectors = embedder.embed(paras)
  except Exception:
    return []
  if len(vectors) != len(paras):
    return []
  return [
    _cosine_similarity(vectors[i], vectors[i + 1])
    for i in range(len(vectors) - 1)
  ]


def _paragraph_split(text: str) -> list[str]:
  parts = [p.strip() for p in text.split("\n\n") if p.strip()]
  return parts if parts else ([text.strip()] if text.strip() else [])


def _sliding_window(
  text: str,
  *,
  chunk_size: int,
  chunk_overlap: int,
  base_offset: int = 0,
  para_similarities: list[float] | None = None,
  semantic: bool = False,
  semantic_min_sim: float = 0.50,
  semantic_max_sim: float = 0.82,
  semantic_max_ratio: float = 1.30,
) -> list[tuple[str, int, int]]:
  """按段落边界优先的滑窗切分，返回 (content, char_start, char_end)

  semantic=True 时在合并决策引入相邻段落 embedding 相似度信号：
    - 相邻段落相似度 < semantic_min_sim：即使长度尚有余量也强制落盘（语义突降点切开）
    - 相邻段落相似度 >= semantic_max_sim：允许把段落并入超限的缓冲（语义相近不舍切）
  para_similarities[i] 为第 i 与第 i+1 段的相似度；不传则纯规则切分。
  """
  if not text.strip():
    return []

  paragraphs = _paragraph_split(text)
  chunks: list[tuple[str, int, int]] = []
  buf = ""
  buf_start = base_offset
  cursor = base_offset
  para_idx = 0

  for para in paragraphs:
    para_start = text.find(para, cursor - base_offset) + base_offset if cursor == base_offset else cursor
    if not buf:
      buf_start = para_start
    candidate = f"{buf}\n\n{para}".strip() if buf else para

    # 语义信号：当前段落与缓冲区最后一段的相似度（para_similarities[para_idx - 1]）
    prev_sim = None
    if semantic and para_similarities and para_idx > 0:
      prev_sim = para_similarities[para_idx - 1]

    if len(candidate) <= chunk_size:
      # 长度有余量：正常合并，但若与前一段语义突降则强制在此切开
      if semantic and prev_sim is not None and prev_sim < semantic_min_sim and buf:
        chunks.append((buf, buf_start, buf_start + len(buf)))
        buf = para
        buf_start = para_start
        cursor = para_start + len(para)
        para_idx += 1
        continue
      buf = candidate
      cursor = para_start + len(para)
      para_idx += 1
      continue

    if buf:
      # 超限：若与前一段高度相似且超限幅度在允许比例内，则语义合并
      if (
        semantic
        and prev_sim is not None
        and prev_sim >= semantic_max_sim
        and len(candidate) <= chunk_size * semantic_max_ratio
      ):
        buf = candidate
        cursor = para_start + len(para)
        para_idx += 1
        continue
      chunks.append((buf, buf_start, buf_start + len(buf)))
      overlap_text = buf[-chunk_overlap:] if chunk_overlap and len(buf) > chunk_overlap else ""
      buf = f"{overlap_text}\n\n{para}".strip() if overlap_text else para
      buf_start = buf_start + len(buf) - len(overlap_text) if overlap_text else para_start
    else:
      if len(para) <= chunk_size:
        buf = para
        buf_start = para_start
        cursor = para_start + len(para)
        para_idx += 1
        continue
      start = 0
      while start < len(para):
        end = min(start + chunk_size, len(para))
        piece = para[start:end]
        abs_start = para_start + start
        chunks.append((piece, abs_start, abs_start + len(piece)))
        if end >= len(para):
          break
        start = max(end - chunk_overlap, start + 1)
      buf = ""
    cursor = para_start + len(para)
    para_idx += 1

  if buf.strip():
    chunks.append((buf, buf_start, buf_start + len(buf)))

  return chunks


def chunk_literature(
  literature_id: str,
  workspace_id: str,
  full_text: str,
  abstract: str = "",
  *,
  chunk_size: int | None = None,
  chunk_overlap: int | None = None,
  semantic: bool = False,
  embedder: Any | None = None,
  semantic_min_sim: float | None = None,
  semantic_max_sim: float | None = None,
  semantic_max_ratio: float | None = None,
) -> list[TextChunk]:
  """将文献全文分块，摘要单独成块，章节内滑窗切分

  semantic=True 时启用语义辅助边界：用段落 embedding 相似度优化合并决策，
  模型加载/计算失败时自动回退为纯规则切分（保证索引不中断）。
  """
  size = chunk_size or settings.chunk_size
  overlap = chunk_overlap or settings.chunk_overlap
  min_sim = semantic_min_sim if semantic_min_sim is not None else settings.rag_semantic_min_sim
  max_sim = semantic_max_sim if semantic_max_sim is not None else settings.rag_semantic_max_sim
  max_ratio = semantic_max_ratio if semantic_max_ratio is not None else settings.rag_semantic_max_ratio
  chunks: list[TextChunk] = []
  idx = 0

  semantic_enabled = bool(semantic)
  if semantic_enabled and embedder is None:
    try:
      from backend.rag import embedder as embedder_mod
      embedder = embedder_mod.get_embedder()
    except Exception as e:
      logger.warning("语义辅助切块初始化失败，回退到规则切块: %s", e)
      semantic_enabled = False
  if semantic_enabled and embedder is None:
    semantic_enabled = False

  if abstract and abstract.strip():
    ab = abstract.strip()
    chunks.append(TextChunk(
      id=str(uuid.uuid4()),
      literature_id=literature_id,
      workspace_id=workspace_id,
      section_key="abstract",
      chunk_index=idx,
      content=ab,
      content_hash=_hash_content(ab),
      char_start=0,
      char_end=len(ab),
    ))
    idx += 1

  sections = split_sections(full_text or "")
  section_map = sections.to_dict()

  if not section_map and full_text.strip():
    section_map = {"full": full_text.strip()}

  for section_key, content in section_map.items():
    if not content.strip():
      continue
    para_sims: list[float] | None = None
    section_semantic = semantic_enabled
    if semantic_enabled:
      try:
        para_sims = _compute_para_similarities(content, embedder)
      except Exception as e:
        logger.warning(
          "语义辅助切块对章节 %s 计算失败，回退规则切块: %s", section_key, e,
        )
        para_sims = None
      section_semantic = bool(para_sims)
    for piece, start, end in _sliding_window(
      content,
      chunk_size=size,
      chunk_overlap=overlap,
      para_similarities=para_sims,
      semantic=section_semantic,
      semantic_min_sim=min_sim,
      semantic_max_sim=max_sim,
      semantic_max_ratio=max_ratio,
    ):
      chunks.append(TextChunk(
        id=str(uuid.uuid4()),
        literature_id=literature_id,
        workspace_id=workspace_id,
        section_key=section_key,
        chunk_index=idx,
        content=piece,
        content_hash=_hash_content(piece),
        char_start=start,
        char_end=end,
      ))
      idx += 1

  return chunks


def compute_document_hash(full_text: str, abstract: str = "") -> str:
  """用于增量索引判断的全文 hash"""
  payload = f"{abstract.strip()}\n---\n{full_text.strip()}"
  return hashlib.sha256(payload.encode("utf-8")).hexdigest()
