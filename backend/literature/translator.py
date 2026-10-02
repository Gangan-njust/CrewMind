"""文献全文英译中（学术翻译）

按版式把英文原文切分为「文本 / 表格 / 图片」有序块：文本块逐段调用大模型翻译，
表格块原样保留（格式与数据不变），图片块按 PDF 页码定位后内联在译文同一位置；
复合图（矢量流程图 + 多张位图）按图题整体渲染为一张图，不会被拆成多个组件图；
边译边流式输出并增量落库，中断后再次调用可自动从未完成的片段续译。

整篇翻译在后台任务中执行，与客户端连接解耦：关闭文献助手（SSE 断线）不会中断翻译，
重新打开页面可重新接入事件流继续查看进度。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections import Counter
from datetime import datetime
from typing import Any, AsyncIterator

from sqlalchemy import select

from backend.literature.content import empty_content_error, resolve_literature_full_text
from backend.literature.prompts import (
  TRANSLATION_GLOSSARY_PLACEHOLDER,
  TRANSLATION_PREVIOUS_PLACEHOLDER,
  TRANSLATION_SEGMENT_PROMPT,
)
from backend.literature.translation_layout import (
  BLOCK_KIND_TEXT,
  BLOCK_LAYOUT_VERSION,
  blocks_to_markdown,
  build_layout_blocks,
  detect_reference_section_start,
  layout_reference_stats,
  seal_blocks,
  text_block_positions,
  text_block_sources,
)
# split_for_translation 由 translation_split 提供，此处再导出以保持历史引用可用
from backend.literature.translation_split import (  # noqa: F401
  DEFAULT_SEGMENT_CHARS,
  split_for_translation,
)
from backend.llm.client import llm_client
from backend.storage.database import get_session
from backend.storage.models import LiteratureAnalysisRecord, LiteratureRecord
from backend.utils.text import sanitize_deep, sanitize_unicode

logger = logging.getLogger(__name__)

DEFAULT_TEMPERATURE = 0.2
MAX_GLOSSARY_CHARS = 2000
MAX_CONTEXT_CHARS = 2000

TRANSLATION_STATUS_PENDING = "pending"
TRANSLATION_STATUS_RUNNING = "running"
TRANSLATION_STATUS_PAUSED = "paused"
TRANSLATION_STATUS_DONE = "done"
TRANSLATION_STATUS_FAILED = "failed"


# ── 文献与译文读写 ────────────────────────────────────────────

def _content_hash(content: str) -> str:
  return hashlib.sha256(content.encode("utf-8", errors="ignore")).hexdigest()[:16]


_NUMBER_TOKEN_RE = re.compile(r"\d+(?:[.,]\d+)*")


def _missing_numbers(source: str, translation: str) -> list[str]:
  """检查译文是否遗漏原文中的数值（数字 / 单位 / 引用编号等），用于提示人工核对"""
  source_counts = Counter(_NUMBER_TOKEN_RE.findall(source or ""))
  translation_counts = Counter(_NUMBER_TOKEN_RE.findall(translation or ""))
  return [
    token for token, count in source_counts.items()
    if translation_counts.get(token, 0) < count
  ]


def _load_json_list(raw: str) -> list[str]:
  try:
    data = json.loads(raw or "[]")
    return [str(item) for item in data] if isinstance(data, list) else []
  except (json.JSONDecodeError, TypeError):
    return []


def _analysis_context(literature_id: str) -> str:
  """取已有 AI 分析摘要作为翻译背景，帮助统一术语与理解上下文"""
  with get_session() as session:
    analysis = session.scalar(
      select(LiteratureAnalysisRecord).where(
        LiteratureAnalysisRecord.literature_id == literature_id
      )
    )
    if not analysis:
      return ""
    parts = []
    if analysis.research_goal:
      parts.append(f"研究目标：{analysis.research_goal}")
    if analysis.methods_summary:
      parts.append(f"方法概述：{analysis.methods_summary}")
    if analysis.contribution_summary:
      parts.append(f"核心贡献：{analysis.contribution_summary}")
    findings = _load_json_list(analysis.key_findings_json)
    if findings:
      parts.append("主要发现：" + "；".join(findings[:5]))
    return "\n".join(parts)


def _load_literature_images(literature_id: str, meta: dict[str, Any]) -> list[dict[str, Any]]:
  """读取文献已提取的图片（分析结果中的 images_json），缺失时直接从 PDF 提取"""
  with get_session() as session:
    analysis = session.scalar(
      select(LiteratureAnalysisRecord).where(
        LiteratureAnalysisRecord.literature_id == literature_id
      )
    )
  raw = (analysis.images_json if analysis else "") or "[]"
  try:
    images = json.loads(raw)
  except json.JSONDecodeError:
    images = []
  if not isinstance(images, list):
    images = []
  images = [img for img in images if isinstance(img, dict) and img.get("filename")]
  if images or not meta.get("pdf_path"):
    return images

  # 尚未做 AI 分析时，直接从 PDF 提取图片，保证译文页也能显示图表
  try:
    from backend.literature.images import extract_pdf_images

    return extract_pdf_images(
      meta["pdf_path"],
      meta.get("workspace_id", ""),
      literature_id,
    )
  except Exception:
    logger.warning("翻译前图片提取失败: %s", literature_id, exc_info=True)
    return []


def _load_layout_images(literature_id: str, meta: dict[str, Any]) -> list[dict[str, Any]]:
  """供译文版式使用的图片：优先把复合图整体渲染为一张图，避免流程图被拆成组件图。

  已整体渲染的页面上不再保留逐个位图碎片（它们只是该图的组成部分）；
  未覆盖的页面仍沿用已提取的单张图片，保证图表不缺失。
  """
  images = _load_literature_images(literature_id, meta)
  pdf_path = meta.get("pdf_path") or ""
  if not pdf_path:
    return images
  try:
    from backend.literature.images import render_figure_regions

    regions = render_figure_regions(
      pdf_path,
      meta.get("workspace_id", ""),
      literature_id,
    )
  except Exception:
    logger.warning("整幅图渲染失败，回退为逐图提取: %s", literature_id, exc_info=True)
    return images
  if not regions:
    return images
  covered_pages = {int(region.get("page") or 0) for region in regions}
  keep = [img for img in images if int(img.get("page") or 0) not in covered_pages]
  return regions + keep


class _LightLiterature:
  """轻量包装：供 content 模块复用文献字段（避免跨 session 持有 ORM 对象）"""

  def __init__(self, meta: dict[str, Any]):
    self.id = meta["literature_id"]
    self.full_text = meta["full_text"]
    self.pdf_path = meta["pdf_path"]
    self.abstract = meta["abstract"]


def load_literature_meta(literature_id: str) -> dict[str, Any]:
  """加载待翻译文献的元数据与全文（必要时从 PDF 补提取）"""
  with get_session() as session:
    lit = session.get(LiteratureRecord, literature_id)
    if not lit:
      raise ValueError(f"文献不存在: {literature_id}")
    snapshot = {
      "literature_id": literature_id,
      "workspace_id": lit.workspace_id,
      "title": lit.title or "",
      "authors": ", ".join(_load_json_list(lit.authors_json)),
      "journal": lit.journal or "",
      "year": lit.year,
      "abstract": lit.abstract or "",
      "pdf_path": lit.pdf_path or "",
      "full_text": lit.full_text or "",
    }

  light = _LightLiterature(snapshot)
  content, pdf_err = resolve_literature_full_text(light, persist=True)
  if not content.strip():
    raise ValueError(empty_content_error(light, pdf_err=pdf_err))
  snapshot["content"] = content
  return snapshot


def get_stored_translation(literature_id: str) -> dict[str, Any]:
  """读取数据库中已保存的译文原始结构（无则为空 dict）"""
  with get_session() as session:
    lit = session.get(LiteratureRecord, literature_id)
    if not lit:
      raise ValueError(f"文献不存在: {literature_id}")
    raw = lit.translation_json or "{}"
  try:
    data = json.loads(raw)
  except json.JSONDecodeError:
    return {}
  return data if isinstance(data, dict) else {}


def save_translation(literature_id: str, payload: dict[str, Any]) -> None:
  with get_session() as session:
    lit = session.get(LiteratureRecord, literature_id)
    if not lit:
      raise ValueError(f"文献不存在: {literature_id}")
    lit.translation_json = json.dumps(sanitize_deep(payload), ensure_ascii=False)
    session.commit()


def build_segments_payload(
  sources: list[str],
  translations: list[str | None],
) -> list[dict[str, Any]]:
  """按原文文本片段顺序生成 segments（保留原文偏移，便于前端对照与断点续译）"""
  segments: list[dict[str, Any]] = []
  offset = 0
  for index, source in enumerate(sources):
    segments.append({
      "index": index + 1,
      "char_start": offset,
      "char_end": offset + len(source),
      "translation": translations[index] or "",
    })
    offset += len(source) + 2
  return segments


def translation_markdown(payload: dict[str, Any]) -> str:
  """由版式块（或历史 segments）拼接完整译文（未译片段自动跳过）"""
  blocks = payload.get("blocks") or []
  if blocks:
    return blocks_to_markdown(blocks)
  parts = [
    str(seg.get("translation") or "").strip()
    for seg in payload.get("segments") or []
  ]
  return "\n\n".join(part for part in parts if part)


def build_translation_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
  """整理为对外返回结构：附 markdown 全文、版式块与进度统计"""
  data = payload or {}
  segments = data.get("segments") or []
  blocks = data.get("blocks") or []
  markdown = translation_markdown(data)
  done = len([seg for seg in segments if str(seg.get("translation") or "").strip()])
  return {
    "status": data.get("status") or TRANSLATION_STATUS_PENDING,
    "target_language": data.get("target_language") or "zh",
    "source_language": data.get("source_language") or "en",
    "model": data.get("model") or "",
    "content_hash": data.get("content_hash") or "",
    "glossary": data.get("glossary") or "",
    "source_chars": int(data.get("source_chars") or 0),
    "translation_chars": len(markdown),
    "segment_total": int(data.get("segment_total") or len(segments)),
    "segment_done": done,
    "block_total": int(data.get("block_total") or len(blocks)),
    "figure_total": int(data.get("figure_total") or 0),
    "table_total": int(data.get("table_total") or 0),
    "caption_total": int(data.get("caption_total") or 0),
    "warnings": list(data.get("warnings") or []),
    "number_checks": list(data.get("number_checks") or []),
    "reference": data.get("reference") or {},
    "layout": data.get("layout") or "",
    "translated_at": data.get("translated_at"),
    "error": data.get("error") or "",
    "markdown": markdown,
    "segments": segments,
    "blocks": blocks,
  }


def get_translation_payload(literature_id: str) -> dict[str, Any]:
  """读取文献已保存的完整译文（含 markdown 全文）"""
  return build_translation_payload(get_stored_translation(literature_id))


# ── 提示词组装 ────────────────────────────────────────────────

def normalize_glossary(glossary: str) -> str:
  """规整用户术语表（逐行「英文=中文」），限制长度避免提示词过长"""
  text = sanitize_unicode(glossary or "").strip()
  if not text:
    return ""
  lines = [line.strip() for line in text.splitlines() if line.strip()]
  return "\n".join(lines)[:MAX_GLOSSARY_CHARS]


def build_context(meta: dict[str, Any], analysis_context: str) -> str:
  """组装翻译背景信息：摘要 + 已有 AI 分析摘要"""
  parts: list[str] = []
  abstract = (meta.get("abstract") or "").strip()
  if abstract:
    parts.append(f"摘要：{abstract[:1200]}")
  if analysis_context:
    parts.append(analysis_context)
  if not parts:
    parts.append("（暂无摘要与 AI 分析结果，请仅依据待翻译原文翻译，并保持术语一致）")
  return "\n".join(parts)[:MAX_CONTEXT_CHARS]


def _build_prompt(
  meta: dict[str, Any],
  *,
  context: str,
  glossary: str,
  content: str,
  index: int,
  total: int,
  previous: str = "",
) -> str:
  return TRANSLATION_SEGMENT_PROMPT.format(
    title=meta.get("title") or "（未提取到标题）",
    authors=meta.get("authors") or "（未提取到作者）",
    journal=meta.get("journal") or "（未提取到期刊）",
    year=meta.get("year") or "（未提取到年份）",
    index=index,
    total=total,
    context=context,
    previous=previous or TRANSLATION_PREVIOUS_PLACEHOLDER,
    glossary=glossary or TRANSLATION_GLOSSARY_PLACEHOLDER,
    content=content,
  )


# ── 翻译主流程 ────────────────────────────────────────────────

def _restore_translations(
  stored: dict[str, Any],
  blocks: list[dict[str, Any]],
  text_positions: list[int],
) -> list[str | None]:
  """按序号回填已完成的文本块译文（表格 / 图片块无需回填）

  只有分段数量与新块布局一致时才按序号回填，避免历史纯文本分段与含图表布局错位。
  """
  translations: list[str | None] = [None] * len(blocks)
  segments = stored.get("segments") or []
  stored_layout = str(stored.get("layout") or "")
  if stored_layout != BLOCK_LAYOUT_VERSION and len(segments) != len(text_positions):
    return translations

  by_index: dict[int, str] = {}
  for seg in segments:
    try:
      index = int(seg.get("index", 0)) - 1
    except (TypeError, ValueError):
      continue
    value = str(seg.get("translation") or "").strip()
    if value:
      by_index[index] = str(seg["translation"])

  for cursor, block_index in enumerate(text_positions):
    value = by_index.get(cursor)
    if value:
      translations[block_index] = value
  return translations


async def translate_literature_stream(
  literature_id: str,
  *,
  glossary: str = "",
  force: bool = False,
  max_chars: int = DEFAULT_SEGMENT_CHARS,
  temperature: float = DEFAULT_TEMPERATURE,
) -> AsyncIterator[dict[str, Any]]:
  """逐块流式翻译整篇文献，产出事件：start / segment_start / token / segment_done / done / error

  - 文本块：调用大模型逐段翻译（index 为文本段序号）；
  - 表格块 / 图片块：不调用大模型，直接下发原内容（index 为 0，携带 block_index 与该块信息）；
  - 中断（客户端断开）时已完成的片段会增量保存在数据库中，再次调用可自动续译。
  """
  meta = load_literature_meta(literature_id)
  content = meta["content"]
  images = _load_layout_images(literature_id, meta)
  blocks = build_layout_blocks(
    content,
    max_chars=max_chars,
    images=images,
    pdf_path=meta.get("pdf_path") or "",
  )
  if not blocks:
    raise ValueError("文献内容为空，无法翻译")

  sources = text_block_sources(blocks)
  text_positions = text_block_positions(blocks)

  glossary_text = normalize_glossary(glossary)
  stored = get_stored_translation(literature_id)
  content_hash = _content_hash(content)
  same_source = stored.get("content_hash") == content_hash

  translations: list[str | None] = [None] * len(blocks)
  if not force and same_source:
    translations = _restore_translations(stored, blocks, text_positions)

  base_markdown = blocks_to_markdown(seal_blocks(blocks, translations))
  done_count = len([t for t in translations if t])

  payload: dict[str, Any] = {
    "status": TRANSLATION_STATUS_RUNNING,
    "target_language": "zh",
    "source_language": "en",
    "model": llm_client.model,
    "content_hash": content_hash,
    "glossary": glossary_text,
    "source_chars": len(content),
    "layout": BLOCK_LAYOUT_VERSION,
    "segment_total": len(sources),
    "block_total": len(blocks),
    "translated_at": stored.get("translated_at") if same_source else None,
    "error": "",
    "segments": build_segments_payload(
      sources,
      [translations[index] for index in text_positions],
    ),
    "blocks": seal_blocks(blocks, translations),
  }
  # 参考文献区不参与图表完整性核对，避免条目中的 “Figure/Table” 造成误报
  reference_start = detect_reference_section_start(content)
  scan_text = content[:reference_start] if reference_start is not None else content
  layout_stats = layout_reference_stats(scan_text, payload["blocks"])
  payload["figure_total"] = layout_stats["figure_blocks"]
  payload["table_total"] = layout_stats["table_blocks"]
  payload["caption_total"] = layout_stats["caption_blocks"]
  payload["warnings"] = list(layout_stats["warnings"])
  payload["reference"] = layout_stats
  payload["number_checks"] = []
  save_translation(literature_id, payload)

  yield {
    "event": "start",
    "total": len(sources),
    "done_count": done_count,
    "resumed": done_count > 0,
    "base_markdown": base_markdown,
    "source_chars": len(content),
    "block_total": len(blocks),
    "figure_total": payload["figure_total"],
    "table_total": payload["table_total"],
    "caption_total": payload["caption_total"],
    "warnings": payload["warnings"],
    "blocks": payload["blocks"],
  }

  if done_count >= len(sources):
    payload["status"] = TRANSLATION_STATUS_DONE
    if not payload["translated_at"]:
      payload["translated_at"] = datetime.now().isoformat(timespec="seconds")
    save_translation(literature_id, payload)
    yield {"event": "done", "translation": build_translation_payload(payload)}
    return

  context = build_context(meta, _analysis_context(literature_id))

  def _sync_payload() -> None:
    payload["segments"] = build_segments_payload(
      sources,
      [translations[index] for index in text_positions],
    )
    payload["blocks"] = seal_blocks(blocks, translations)

  previous_translation = ""

  try:
    text_cursor = 0
    for index, block in enumerate(blocks):
      kind = block.get("kind") or BLOCK_KIND_TEXT
      if kind != BLOCK_KIND_TEXT:
        # 表格与图片不翻译：原样下发，位置与原文一致
        yield {
          "event": "segment_start",
          "index": 0,
          "total": len(sources),
          "block_index": index + 1,
          "kind": kind,
          "filename": block.get("filename") or "",
          "page": block.get("page"),
          "caption": block.get("caption") or "",
          "content": block.get("content") or "",
        }
        yield {
          "event": "segment_done",
          "index": 0,
          "total": len(sources),
          "block_index": index + 1,
          "kind": kind,
        }
        continue

      text_cursor += 1
      if translations[index]:
        continue

      yield {
        "event": "segment_start",
        "index": text_cursor,
        "total": len(sources),
        "block_index": index + 1,
        "kind": kind,
      }

      prompt = _build_prompt(
        meta,
        context=context,
        glossary=glossary_text,
        content=block["source"],
        index=text_cursor,
        total=len(sources),
        previous=previous_translation,
      )
      response = await llm_client.chat(
        [{"role": "user", "content": prompt}],
        temperature=temperature,
        stream=True,
      )

      parts: list[str] = []
      if hasattr(response, "__aiter__"):
        async for chunk in response:
          if not chunk:
            continue
          parts.append(chunk)
          yield {
            "event": "token",
            "content": chunk,
            "index": text_cursor,
            "block_index": index + 1,
          }
      else:
        text = str(response)
        parts.append(text)
        yield {
          "event": "token",
          "content": text,
          "index": text_cursor,
          "block_index": index + 1,
        }

      translation = sanitize_unicode("".join(parts).strip())
      if not translation:
        raise ValueError(f"第 {text_cursor} 段翻译结果为空")
      translations[index] = translation
      previous_translation = translation[-400:]
      missing_numbers = _missing_numbers(block["source"], translation)
      if missing_numbers and len(payload["number_checks"]) < 5:
        payload["number_checks"].append(
          f"第 {text_cursor} 段可能未完整保留原文数字 / 数值：{', '.join(missing_numbers[:8])}"
        )

      _sync_payload()
      save_translation(literature_id, payload)
      yield {
        "event": "segment_done",
        "index": text_cursor,
        "total": len(sources),
        "block_index": index + 1,
        "kind": kind,
      }
  except asyncio.CancelledError:
    payload["status"] = TRANSLATION_STATUS_PAUSED
    _sync_payload()
    save_translation(literature_id, payload)
    raise
  except Exception as e:
    logger.exception("文献翻译失败: %s", literature_id)
    payload["status"] = TRANSLATION_STATUS_FAILED
    payload["error"] = str(e)
    _sync_payload()
    save_translation(literature_id, payload)
    yield {"event": "error", "message": str(e)}
    return

  payload["status"] = TRANSLATION_STATUS_DONE
  payload["error"] = ""
  payload["translated_at"] = datetime.now().isoformat(timespec="seconds")
  _sync_payload()
  save_translation(literature_id, payload)
  yield {"event": "done", "translation": build_translation_payload(payload)}


async def translate_literature(
  literature_id: str,
  *,
  glossary: str = "",
  force: bool = False,
  max_chars: int = DEFAULT_SEGMENT_CHARS,
) -> dict[str, Any]:
  """非流式整篇翻译，返回完整译文结构"""
  result: dict[str, Any] | None = None
  async for event in translate_literature_stream(
    literature_id,
    glossary=glossary,
    force=force,
    max_chars=max_chars,
  ):
    if event.get("event") == "done":
      result = event.get("translation")
    elif event.get("event") == "error":
      raise ValueError(event.get("message") or "翻译失败")
  if result is None:
    raise ValueError("翻译未完成")
  return result
# ── 后台整篇翻译任务（与客户端连接解耦） ──────────────────────

# 每个订阅者（SSE 连接）的事件队列上限：客户端消费过慢时丢弃最早的 token，避免拖慢翻译
_SUBSCRIBER_QUEUE_SIZE = 512

# 尚无订阅者时缓存的事件上限：保证刚发起翻译的页面能收到完整流式输出，同时避免内存无界增长
_REPLAY_LIMIT = 4000

# 正在进行 / 刚结束的后台翻译任务：literature_id -> TranslationRun
_RUNS: dict[str, "TranslationRun"] = {}


def build_start_event(literature_id: str) -> dict[str, Any] | None:
  """按已落库的译文重建 SSE start 事件（供中途加入 / 断线重连的订阅者初始化页面）"""
  stored = get_stored_translation(literature_id)
  if not stored:
    return None
  payload = build_translation_payload(stored)
  return {
    "event": "start",
    "total": payload["segment_total"],
    "done_count": payload["segment_done"],
    "resumed": payload["segment_done"] > 0,
    "base_markdown": payload["markdown"],
    "source_chars": payload["source_chars"],
    "block_total": payload["block_total"],
    "figure_total": payload["figure_total"],
    "table_total": payload["table_total"],
    "caption_total": payload["caption_total"],
    "warnings": payload["warnings"],
    "blocks": payload["blocks"],
  }


class TranslationRun:
  """一次后台整篇翻译：脱离客户端连接运行，退出文献助手后仍继续翻译

  - 翻译事件分发给所有订阅者（SSE 连接），订阅者断开只影响自己，不影响任务；
  - 每段译完仍按原逻辑增量落库，因此页面关闭后进度可见、重新打开可继续观看；
  - 首个订阅者按产生顺序回放已缓存事件（发起翻译的页面流式体验不变），
    中途重新接入的订阅者改用按数据库重建的 start 快照续看，不会丢失已译内容。
  """

  def __init__(self, literature_id: str):
    self.literature_id = literature_id
    self.subscribers: set[asyncio.Queue[dict[str, Any] | None]] = set()
    self.task: asyncio.Task[None] | None = None
    self.ready = asyncio.Event()
    self.finished = False
    self.terminal: dict[str, Any] | None = None
    self.error = ""
    self.buffer: list[dict[str, Any]] = []
    self.buffer_overflowed = False
    self.ever_subscribed = False

  @property
  def active(self) -> bool:
    return self.task is not None and not self.task.done()

  def start(self, *, glossary: str = "", force: bool = False) -> None:
    """把整篇翻译放到后台任务里执行（继承当前请求的 LLM 上下文变量）"""
    self.task = asyncio.create_task(self._run(glossary=glossary, force=force))

  async def wait(self) -> None:
    """等待后台翻译结束（等待被取消的任务时不抛出异常）"""
    if self.task is not None:
      await asyncio.gather(self.task, return_exceptions=True)

  async def cancel(self) -> None:
    """取消后台翻译（已完成片段已落库，可再次续译）"""
    task = self.task
    if task is None or task.done():
      return
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

  async def _run(self, *, glossary: str, force: bool) -> None:
    try:
      async for event in translate_literature_stream(
        self.literature_id,
        glossary=glossary,
        force=force,
      ):
        if event.get("event") == "start":
          # 首段事件：说明初始进度已落库，可以放心让订阅者用数据库快照续看
          self.ready.set()
        self._publish(event)
    except asyncio.CancelledError:
      self.error = "翻译已停止"
      raise
    except Exception as e:
      logger.exception("后台文献翻译失败: %s", self.literature_id)
      self.error = str(e)
      self._publish({"event": "error", "message": str(e)})
    finally:
      if self.terminal is None:
        self.terminal = (
          {"event": "error", "message": self.error}
          if self.error
          else {"event": "done", "translation": get_translation_payload(self.literature_id)}
        )
      self.finished = True
      self.ready.set()
      self._close_subscribers()
      if _RUNS.get(self.literature_id) is self:
        _RUNS.pop(self.literature_id, None)

  def _publish(self, event: dict[str, Any]) -> None:
    """把事件分发给订阅者；尚无订阅者时按序缓存，供首个订阅者回放"""
    if event.get("event") in ("done", "error"):
      self.terminal = event
    if not self.subscribers:
      if not self.ever_subscribed:
        if len(self.buffer) < _REPLAY_LIMIT:
          self.buffer.append(event)
        else:
          self.buffer_overflowed = True
      return
    for queue in list(self.subscribers):
      try:
        queue.put_nowait(event)
      except asyncio.QueueFull:
        # 订阅者消费过慢：丢弃最早的事件，保证翻译不被拖慢
        try:
          queue.get_nowait()
          queue.put_nowait(event)
        except Exception:
          pass

  def _close_subscribers(self) -> None:
    for queue in list(self.subscribers):
      try:
        queue.put_nowait(None)
      except asyncio.QueueFull:
        pass
    self.subscribers.clear()

  def _take_replay(self) -> list[dict[str, Any]] | None:
    """首个订阅者取出已缓存事件；已订阅过或缓存溢出时返回 None（改用数据库快照续看）"""
    if self.ever_subscribed or self.buffer_overflowed:
      return None
    self.ever_subscribed = True
    buffered, self.buffer = self.buffer, []
    return buffered or None

  async def subscribe(self) -> AsyncIterator[dict[str, Any]]:
    """订阅翻译事件：先补齐已产生的事件（回放或数据库快照），再接力实时事件直到结束"""
    await self.ready.wait()

    replay = self._take_replay()
    if replay is None:
      snapshot = build_start_event(self.literature_id)
      if snapshot is not None:
        yield snapshot

    if self.finished:
      if replay:
        for event in replay:
          yield event
      elif self.terminal is not None:
        yield self.terminal
      return

    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=_SUBSCRIBER_QUEUE_SIZE)
    self.subscribers.add(queue)
    if self.finished:
      # 注册队列与任务结束之间没有 await，此处只做兜底
      self.subscribers.discard(queue)
      if self.terminal is not None:
        yield self.terminal
      return
    try:
      for event in replay or []:
        yield event
      while True:
        event = await queue.get()
        if event is None:
          return
        yield event
    finally:
      self.subscribers.discard(queue)


def get_translation_run(literature_id: str) -> TranslationRun | None:
  """返回该文献正在进行的后台翻译任务（无则 None）"""
  run = _RUNS.get(literature_id)
  return run if run is not None and not run.finished else None


async def start_translation_run(
  literature_id: str,
  *,
  glossary: str = "",
  force: bool = False,
) -> TranslationRun:
  """启动（或复用）后台整篇翻译任务。

  - 已有任务在跑且未要求重新翻译时，直接复用它，避免重复消耗模型调用；
  - force=True（“重新翻译整篇”）时先停掉旧任务，再从头开始。
  """
  existing = _RUNS.get(literature_id)
  if existing is not None and not existing.finished:
    if not force:
      return existing
    await existing.cancel()

  run = TranslationRun(literature_id)
  _RUNS[literature_id] = run
  run.start(glossary=glossary, force=force)
  return run


async def stop_translation_run(literature_id: str) -> bool:
  """停止该文献的后台翻译（已译片段保留），返回是否真的停止了任务"""
  run = _RUNS.get(literature_id)
  if run is None or run.finished:
    return False
  await run.cancel()
  return True