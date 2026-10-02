"""译文版式布局：把原文切成「文本 / 表格 / 图片 / 题注」有序块

对应「翻译页面要显示图表、位置不变、表格格式与数据不变」的需求：
1. 文本块：交给大模型逐段翻译；
2. 表格块：**不经过大模型**，原样保留（格式与数据零改动）；
3. 图片块：优先按原文题注（Figure N）锚定位置，其次按 PDF 页码定位，在译文同一位置内联展示原图；
4. 题注块：Figure / Table 题注原文原样保留（编号不变），其译文作为紧随其后的独立块输出（role=caption）。

块顺序严格按原文顺序排列，因此译文的版式（段落顺序、图表所在位置）与原文一致。
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

from backend.literature.parser import extract_pages_text
from backend.literature.translation_split import (
  DEFAULT_SEGMENT_CHARS,
  split_for_translation,
)
from backend.utils.text import sanitize_unicode

BLOCK_KIND_TEXT = "text"
BLOCK_KIND_TABLE = "table"
BLOCK_KIND_FIGURE = "figure"
BLOCK_KIND_REFERENCE = "reference"

# 题注以文本块承载：原样保留原文，译文另存于 translation 字段
ROLE_BODY = "body"
ROLE_CAPTION = "caption"

# 译文版式版本号：存储结构变化时用于判定旧译文能否按序号续译
BLOCK_LAYOUT_VERSION = "blocks-v2"

_MIN_TABLE_ROWS = 2
_MAX_TABLE_ROWS = 80
_MAX_TABLE_CHARS = 4000
_MAX_TABLE_LINE_CHARS = 240
_MIN_TABLE_CELLS = 2

_CELL_SPLIT_RE = re.compile(r"\s{2,}|\t+")
_PIPE_SEPARATOR_RE = re.compile(r"^\|?[\s:|\-]+\|[\s:|\-]*$")
_TOC_LEADER_RE = re.compile(r"\.{3,}\s*\d+\s*$")
_DIGIT_RE = re.compile(r"\d")
_NUMBER_CELL_RE = re.compile(r"^[<>≈~]?\s*\d+(?:[.,]\d+)*(?:\s*%|%)?$")
_NUM_SPLIT_RE = re.compile(r"(\d+)")

_PAGE_PROBE_LENGTHS = (60, 120, 200, 300)
_MIN_PROBE_CHARS = 12

# ── 题注识别 ──────────────────────────────────────────────────

_MAX_CAPTION_CHARS = 600
_CAPTION_SEPARATORS = ".:：、|—–-"

_FIGURE_CAPTION_RE = re.compile(
  r"^\s*(?P<prefix>(?:fig(?:ure)?s?|图))\s*\.?\s*(?P<number>\d+[A-Za-z]?)(?P<rest>.*)$",
  re.IGNORECASE,
)
_TABLE_CAPTION_RE = re.compile(
  r"^\s*(?P<prefix>(?:tables?|tab|表))\s*\.?\s*(?P<number>\d+[A-Za-z]?)(?P<rest>.*)$",
  re.IGNORECASE,
)

# 题注后紧跟这些词时说明是正文中的交叉引用（“Figure 3 shows ...”），而非题注
_REFERENCE_WORDS = {
  "shows", "show", "depicts", "depict", "illustrates", "illustrate", "presents",
  "present", "lists", "list", "summarizes", "summarize", "compares", "compare",
  "reports", "report", "gives", "give", "provides", "provide", "indicates",
  "indicate", "reveals", "reveal", "demonstrates", "demonstrate", "describes",
  "describe", "displays", "display", "contains", "contain", "represents",
  "represent", "is", "are", "was", "were", "can", "may", "has", "have", "and",
  "or", "to", "in", "of", "for", "with", "above", "below",
  # 正文承接词："Figure 6 also visually illustrates ..." 之类仍是交叉引用
  "also", "further", "furthermore", "additionally", "moreover", "then",
}

# 有表注但未识别出表格区域时，向表注之后探测表格文本的最大跨度
_TABLE_FALLBACK_WINDOW = 1500


# ── 表格识别 ──────────────────────────────────────────────────

def _split_cells(line: str) -> list[str]:
  """把一行文本拆成单元格：优先按 | 拆分，其次按 2 个以上空格 / 制表符对齐拆分"""
  stripped = line.strip()
  if not stripped:
    return []
  if stripped.count("|") >= 2:
    cells = [cell.strip() for cell in stripped.strip("|").split("|")]
    return cells if len(cells) >= _MIN_TABLE_CELLS else []
  if "|" in stripped:
    return []
  cells = [cell for cell in _CELL_SPLIT_RE.split(stripped) if cell]
  return cells if len(cells) >= _MIN_TABLE_CELLS else []


def _is_separator_row(line: str) -> bool:
  stripped = line.strip()
  return "|" in stripped and "-" in stripped and bool(_PIPE_SEPARATOR_RE.match(stripped))


def _accept_group(rows: list[tuple[int, list[str]]], lines: list[str]) -> bool:
  """判断一组连续对齐行是否构成表格（管道表格 / 空格对齐表格）"""
  counts = [len(cells) for _, cells in rows]
  common, freq = Counter(counts).most_common(1)[0]
  if common < _MIN_TABLE_CELLS:
    return False

  pipe_rows = sum(1 for index, _ in rows if "|" in lines[index])
  has_separator = any(_is_separator_row(lines[index]) for index, _ in rows)
  if pipe_rows >= max(2, len(rows) - 1) and (has_separator or freq >= 2):
    return True

  if freq < max(2, len(rows) - 1):
    return False
  if not any(any(_DIGIT_RE.search(cell) for cell in cells) for _, cells in rows):
    return False
  numeric_rows = sum(
    1 for _, cells in rows if any(_NUMBER_CELL_RE.match(cell) for cell in cells)
  )
  return numeric_rows >= 1


def detect_table_blocks(text: str) -> list[dict[str, Any]]:
  """识别原文中的表格区域，返回 [{start, end, text}]（按出现顺序）"""
  if not text:
    return []

  lines = text.split("\n")
  offsets: list[int] = []
  position = 0
  for line in lines:
    offsets.append(position)
    position += len(line) + 1

  blocks: list[dict[str, Any]] = []
  rows: list[tuple[int, list[str]]] = []

  def flush() -> None:
    if len(rows) < _MIN_TABLE_ROWS or len(rows) > _MAX_TABLE_ROWS:
      return
    if not _accept_group(rows, lines):
      return
    first, last = rows[0][0], rows[-1][0]
    start = offsets[first]
    end = offsets[last] + len(lines[last])
    raw = text[start:end]
    if len(raw) > _MAX_TABLE_CHARS:
      return
    if any(len(line) > _MAX_TABLE_LINE_CHARS for line in lines[first:last + 1]):
      return
    blocks.append({"start": start, "end": end, "text": raw})

  for index, line in enumerate(lines):
    cells = _split_cells(line)
    if cells and not _TOC_LEADER_RE.search(line):
      rows.append((index, cells))
      continue
    flush()
    rows = []
  flush()
  return blocks


def table_as_markdown(block: dict[str, Any]) -> str:
  """把识别出的表格转成 Markdown 可渲染形式：管道表格原样保留；
  其它按空格对齐的表格包进围栏代码块，保持列对齐（格式与数据都不变）"""
  raw = str(block.get("text") or block.get("content") or "").strip("\n")
  if not raw:
    return ""
  lines = [line for line in raw.split("\n") if line.strip()]
  is_pipe = bool(lines) and all("|" in line for line in lines)
  if is_pipe:
    return raw
  return f"```text\n{raw}\n```"


def parse_caption(paragraph: str) -> dict[str, Any] | None:
  """识别一段文字是否为 Figure / Table 题注，返回 {caption_kind, number, content}"""
  original = (paragraph or "").strip()
  if not original or len(original) > _MAX_CAPTION_CHARS:
    return None

  first_line = original.split("\n", 1)[0].strip()
  for kind, pattern in (
    (BLOCK_KIND_FIGURE, _FIGURE_CAPTION_RE),
    (BLOCK_KIND_TABLE, _TABLE_CAPTION_RE),
  ):
    match = pattern.match(first_line)
    if not match:
      continue
    rest = (match.group("rest") or "").strip()
    has_separator = bool(rest) and rest[0] in _CAPTION_SEPARATORS
    body = rest[1:].strip() if has_separator else rest
    if not has_separator and body:
      first_word = re.split(r"[\s,;]+", body, 1)[0].strip(".,;:()[]").lower()
      if first_word in _REFERENCE_WORDS:
        return None
    return {
      "caption_kind": kind,
      "number": str(match.group("number")),
      "content": original,
    }
  return None


def figure_caption_number(text: str) -> str | None:
  """从一段文字（如 PDF 文本块）中识别图题注编号，供按坐标定位图片区域使用。

  正文中的交叉引用（“Figure 3 shows ...”“Figure 6 also illustrates ...”）返回 None。
  """
  info = parse_caption((text or "")[:_MAX_CAPTION_CHARS])
  if not info or info.get("caption_kind") != BLOCK_KIND_FIGURE:
    return None
  first_line = (text or "").strip().split("\n", 1)[0].strip()
  if not _FIGURE_CAPTION_RE.match(first_line):
    return None
  return str(info["number"])


def _iter_paragraphs(text: str, start: int, end: int):
  """按空行切分段落，产出 (段落文本, 起始偏移, 结束偏移)（偏移相对整段原文）"""
  chunk = text[start:end]
  position = 0
  for match in re.finditer(r"\n[ \t]*\n", chunk):
    segment = chunk[position:match.start()]
    if segment.strip():
      lead = len(segment) - len(segment.lstrip())
      yield segment.strip(), start + position + lead, start + match.start()
    position = match.end()
  tail = chunk[position:]
  if tail.strip():
    lead = len(tail) - len(tail.lstrip())
    yield tail.strip(), start + position + lead, start + len(chunk)


def _iter_caption_paragraphs(text: str):
  """遍历原文中所有题注段落，产出 (题注信息, 起始偏移, 结束偏移)"""
  for paragraph, start, end in _iter_paragraphs(text, 0, len(text)):
    info = parse_caption(paragraph)
    if info:
      yield info, start, end


# ── 参考文献区识别（不翻译） ──────────────────────────────────

# 参考文献标题：References / Bibliography / Literature Cited / 参考文献等，允许带编号前缀
_REFERENCE_HEADING_RE = re.compile(
  r"^\s*(?:(?:[IVXLC]+|\d+)[.)]?\s*)?"
  r"(references?|bibliography|literature\s+cited|works\s+cited|参考文献|引用文献|参考书目)"
  r"\s*[:：]?\s*$",
  re.IGNORECASE,
)

# 标题需出现在全文靠后位置，避免命中目录或正文中的偶然出现
_REFERENCE_MIN_RATIO = 0.3


def detect_reference_section_start(text: str) -> int | None:
  """定位参考文献区起点（取文末最后一个独立成行的参考文献标题），该区原样保留、不翻译"""
  if not text:
    return None
  threshold = int(len(text) * _REFERENCE_MIN_RATIO)
  found: int | None = None
  for paragraph, start, _end in _iter_paragraphs(text, 0, len(text)):
    if start < threshold:
      continue
    heading = paragraph.split("\n", 1)[0].strip()
    if _REFERENCE_HEADING_RE.match(heading):
      found = start
  return found


def _inside_ranges(position: int, ranges: list[tuple[int, int]]) -> bool:
  return any(range_start <= position < range_end for range_start, range_end in ranges)


# ── 图片定位 ──────────────────────────────────────────────────

def _locate_page_offset(content: str, page_text: str, start_at: int) -> int | None:
  """在原文中定位某一页文本的起始位置（用页首文字做探针，逐步放长）"""
  stripped = (page_text or "").strip()
  if not stripped:
    return None
  for length in _PAGE_PROBE_LENGTHS:
    probe = stripped[:length].strip()
    if len(probe) < _MIN_PROBE_CHARS:
      continue
    found = content.find(probe, start_at)
    if found < 0:
      found = content.find(probe)
    if found >= 0:
      return found
  return None


def _snap_to_paragraph(content: str, offset: int) -> int:
  """把偏移回退到最近的段落起点，使图片落在段落边界上"""
  if offset <= 0:
    return 0
  previous = content.rfind("\n\n", 0, offset)
  return 0 if previous < 0 else previous + 2


def _match_page_caption(
  page_text: str,
  captions: list[dict[str, Any]],
  used: set[int],
) -> dict[str, Any] | None:
  """在该页文本中匹配一个尚未被占用的图注，用于把图片锚定到题注位置"""
  head = " ".join((page_text or "").split())
  if not head:
    return None
  for caption in captions:
    if id(caption) in used:
      continue
    probe = " ".join(str(caption.get("content") or "").split())[:40]
    if probe and probe in head:
      return caption
  return None


def locate_figure_anchors(
  content: str,
  images: list[dict[str, Any]] | None,
  *,
  pdf_path: str = "",
  captions: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
  """为每张图片计算它在原文中的锚点偏移，优先锚定到对应图注，保证与原文顺序一致"""
  items = [img for img in (images or []) if img.get("filename")]
  if not items:
    return []

  pages: list[str] = []
  if pdf_path:
    try:
      pages = extract_pages_text(pdf_path)
    except Exception:
      pages = []

  remaining_captions = [
    caption for caption in (captions or [])
    if caption.get("caption_kind") == BLOCK_KIND_FIGURE
  ]

  ordered = sorted(
    items,
    key=lambda img: (int(img.get("page") or 0), str(img.get("filename") or "")),
  )
  max_page = max([int(img.get("page") or 0) for img in ordered] + [len(pages), 1])

  anchors: list[dict[str, Any]] = []
  seen: set[str] = set()
  cursor = 0
  for img in ordered:
    filename = str(img["filename"])
    if filename in seen:
      continue
    seen.add(filename)

    page_no = int(img.get("page") or 0)
    anchor: int | None = None
    number: str | None = None
    caption_start: int | None = None

    matched: dict[str, Any] | None = None
    if 0 < page_no <= len(pages):
      matched = _match_page_caption(pages[page_no - 1], remaining_captions, set())
    if matched is None and remaining_captions:
      # 无页文本或该页未找到图注时，按文档顺序兜底匹配，避免图注被误判为缺失
      matched = remaining_captions[0]
    if matched is not None:
      remaining_captions.remove(matched)
      anchor = int(matched["start"])
      number = str(matched.get("number") or "") or None
      caption_start = int(matched["start"])

    if number is None:
      # 原文无空行分隔导致题注段落未识别时，沿用图片自身的图号（如按图题渲染的整幅图）
      number = str(img.get("number") or "") or None

    if anchor is None and 0 < page_no <= len(pages):
      anchor = _locate_page_offset(content, pages[page_no - 1], cursor)
    if anchor is None:
      # 缺少页文本（无 PDF / 扫描件）时按页码比例近似落位，仍保持文档顺序
      anchor = int(len(content) * max(0, page_no - 1) / max(max_page, 1))

    anchor = min(max(anchor, cursor), len(content))
    anchor = min(max(_snap_to_paragraph(content, anchor), cursor), len(content))
    cursor = anchor
    anchors.append({
      "filename": filename,
      "page": page_no or None,
      "caption": str(img.get("caption") or ""),
      "number": number,
      "caption_start": caption_start,
      "offset": anchor,
      "placeholder": False,
    })
  return anchors


# ── 表格兜底 ──────────────────────────────────────────────────

def _looks_like_table_rows(paragraph: str) -> bool:
  lines = [line for line in (paragraph or "").split("\n") if line.strip()]
  if len(lines) < _MIN_TABLE_ROWS or len(lines) > _MAX_TABLE_ROWS:
    return False
  multi_cell_lines = [line for line in lines if len(_split_cells(line)) >= 2]
  if len(multi_cell_lines) < max(2, len(lines) - 1):
    return False
  return bool(_DIGIT_RE.search(paragraph))


def _fallback_table_regions(
  text: str,
  captions: list[dict[str, Any]],
  tables: list[dict[str, Any]],
) -> list[dict[str, Any]]:
  """有表注但未识别出表格区域时，把紧随其后、形态类似表格的段落冻结为表格，避免表格丢失"""
  extra: list[dict[str, Any]] = []
  existing_starts = [int(table["start"]) for table in tables]
  for caption in captions:
    if caption.get("caption_kind") != BLOCK_KIND_TABLE:
      continue
    caption_end = int(caption["end"])
    if any(caption_end <= start <= caption_end + _TABLE_FALLBACK_WINDOW for start in existing_starts):
      continue
    position = caption_end
    while position < len(text) and text[position] == "\n":
      position += 1
    paragraph_end = text.find("\n\n", position)
    if paragraph_end < 0:
      paragraph_end = len(text)
    paragraph = text[position:paragraph_end]
    if len(paragraph) > _MAX_TABLE_CHARS:
      continue
    if any(len(line) > _MAX_TABLE_LINE_CHARS for line in paragraph.split("\n")):
      continue
    if not _looks_like_table_rows(paragraph):
      continue
    extra.append({"start": position, "end": paragraph_end, "text": paragraph, "fallback": True})
  return extra


def _nearest_caption_number(
  captions: list[dict[str, Any]],
  kind: str,
  start: int,
  *,
  window: int = _TABLE_FALLBACK_WINDOW,
) -> str | None:
  best: str | None = None
  best_distance: int | None = None
  for caption in captions:
    if caption.get("caption_kind") != kind:
      continue
    distance = abs(int(caption["start"]) - start)
    if distance <= window and (best_distance is None or distance < best_distance):
      best = str(caption.get("number") or "") or None
      best_distance = distance
  return best


# ── 版式块组装 ────────────────────────────────────────────────

def _text_blocks(text: str, start: int, end: int, max_chars: int) -> list[dict[str, Any]]:
  """把一段原文按段落切成若干文本块，并记录各自在原文中的偏移"""
  chunk = text[start:end]
  if not chunk.strip():
    return []
  blocks: list[dict[str, Any]] = []
  search_from = 0
  for source in split_for_translation(chunk, max_chars):
    local = chunk.find(source, search_from)
    if local < 0:
      local = search_from
    char_start = start + local
    char_end = char_start + len(source)
    search_from = local + len(source)
    blocks.append({
      "kind": BLOCK_KIND_TEXT,
      "role": ROLE_BODY,
      "source": source,
      "char_start": char_start,
      "char_end": char_end,
    })
  return blocks


def build_layout_blocks(
  content: str,
  *,
  max_chars: int = DEFAULT_SEGMENT_CHARS,
  images: list[dict[str, Any]] | None = None,
  pdf_path: str = "",
) -> list[dict[str, Any]]:
  """把原文解析为有序版式块：文本块（待翻译）+ 表格块（原样）+ 图片块（按原文位置）+ 题注块（原样保留）"""
  text = sanitize_unicode(content or "").replace("\r\n", "\n")
  if not text.strip():
    return []

  reference_start = detect_reference_section_start(text)

  tables = detect_table_blocks(text)
  table_ranges = [(int(table["start"]), int(table["end"])) for table in tables]

  captions: list[dict[str, Any]] = [
    {
      "start": start,
      "end": end,
      "caption_kind": info["caption_kind"],
      "number": info["number"],
      "content": info["content"],
    }
    for info, start, end in _iter_caption_paragraphs(text)
    if not _inside_ranges(start, table_ranges)
  ]

  figures = locate_figure_anchors(text, images, pdf_path=pdf_path, captions=captions)
  matched_caption_starts = {
    int(figure["caption_start"])
    for figure in figures
    if figure.get("caption_start") is not None
  }

  # 有图注但未提取到图片（矢量图 / 提取失败）：生成占位图块，保证图表不缺失
  for caption in captions:
    if caption["caption_kind"] != BLOCK_KIND_FIGURE:
      continue
    if int(caption["start"]) in matched_caption_starts:
      continue
    figures.append({
      "filename": "",
      "page": None,
      "caption": caption["content"],
      "number": caption["number"],
      "caption_start": int(caption["start"]),
      "offset": int(caption["start"]),
      "placeholder": True,
    })

  tables = tables + _fallback_table_regions(text, captions, tables)
  table_ranges = [(int(table["start"]), int(table["end"])) for table in tables]

  events: list[tuple[int, int, str, dict[str, Any]]] = []
  for table in tables:
    events.append((int(table["start"]), 2, BLOCK_KIND_TABLE, table))
  for figure in figures:
    offset = int(figure["offset"])
    for table_start, table_end in table_ranges:
      if table_start < offset < table_end:
        offset = table_end
    events.append((offset, 0, BLOCK_KIND_FIGURE, {**figure, "offset": offset}))
  for caption in captions:
    events.append((int(caption["start"]), 1, ROLE_CAPTION, caption))
  events.sort(key=lambda item: (item[0], item[1]))
  if reference_start is not None:
    # 参考文献区不翻译：区内不再产生图表 / 题注事件，整段原文原样保留
    events = [event for event in events if event[0] < reference_start]

  blocks: list[dict[str, Any]] = []
  cursor = 0
  for offset, _, kind, payload in events:
    offset = max(offset, cursor)
    if offset > cursor:
      blocks.extend(_text_blocks(text, cursor, offset, max_chars))
      cursor = offset

    if kind == BLOCK_KIND_TABLE:
      blocks.append({
        "kind": BLOCK_KIND_TABLE,
        "content": table_as_markdown(payload),
        "raw": str(payload.get("text") or ""),
        "number": _nearest_caption_number(captions, BLOCK_KIND_TABLE, int(payload["start"])),
        "fallback": bool(payload.get("fallback")),
        "char_start": int(payload["start"]),
        "char_end": int(payload["end"]),
      })
      cursor = max(cursor, int(payload["end"]))
      continue

    if kind == BLOCK_KIND_FIGURE:
      blocks.append({
        "kind": BLOCK_KIND_FIGURE,
        "filename": str(payload.get("filename") or ""),
        "page": payload.get("page"),
        "caption": str(payload.get("caption") or ""),
        "number": payload.get("number"),
        "placeholder": bool(payload.get("placeholder")),
        "char_start": offset,
        "char_end": offset,
      })
      continue

    caption_text = str(payload.get("content") or "")
    blocks.append({
      "kind": BLOCK_KIND_TEXT,
      "role": ROLE_CAPTION,
      "caption_kind": str(payload.get("caption_kind") or ""),
      "number": payload.get("number"),
      "source": caption_text,
      "content": caption_text,
      "char_start": int(payload["start"]),
      "char_end": int(payload["end"]),
    })
    cursor = max(cursor, int(payload["end"]))

  if cursor < len(text):
    if reference_start is None:
      blocks.extend(_text_blocks(text, cursor, len(text), max_chars))
    else:
      if cursor < reference_start:
        blocks.extend(_text_blocks(text, cursor, reference_start, max_chars))
      reference_from = max(reference_start, cursor)
      reference_text = text[reference_from:].strip()
      if reference_text:
        blocks.append({
          "kind": BLOCK_KIND_REFERENCE,
          "content": reference_text,
          "char_start": reference_from,
          "char_end": len(text),
        })
  return blocks


def text_block_sources(blocks: list[dict[str, Any]]) -> list[str]:
  """取出所有文本块的原文（顺序与 blocks 中的文本块一致）"""
  return [
    str(block.get("source") or "")
    for block in blocks
    if block.get("kind") == BLOCK_KIND_TEXT
  ]


def text_block_positions(blocks: list[dict[str, Any]]) -> list[int]:
  """文本块在 blocks 中的下标列表"""
  return [index for index, block in enumerate(blocks) if block.get("kind") == BLOCK_KIND_TEXT]


def seal_blocks(
  blocks: list[dict[str, Any]],
  translations: list[str | None] | None = None,
) -> list[dict[str, Any]]:
  """生成可落库 / 可返回前端的块结构（文本块附译文，表格与图片附原始内容）"""
  values = translations or []
  sealed: list[dict[str, Any]] = []
  for index, block in enumerate(blocks):
    translated = values[index] if index < len(values) else None
    kind = block.get("kind") or BLOCK_KIND_TEXT
    sealed.append({
      "index": index + 1,
      "kind": kind,
      "role": str(block.get("role") or ROLE_BODY),
      "caption_kind": str(block.get("caption_kind") or ""),
      "number": block.get("number"),
      "placeholder": bool(block.get("placeholder")),
      "char_start": int(block.get("char_start") or 0),
      "char_end": int(block.get("char_end") or 0),
      "source": str(block.get("source") or ""),
      "translation": (translated or "") if kind == BLOCK_KIND_TEXT else "",
      "content": str(block.get("content") or ""),
      "filename": str(block.get("filename") or ""),
      "page": block.get("page"),
      "caption": str(block.get("caption") or ""),
    })
  return sealed


def blocks_to_markdown(blocks: list[dict[str, Any]] | None) -> str:
  """由版式块拼接完整译文 Markdown（文本译文 + 题注原文/译文 + 表格原样 + 图片位置标记）"""
  parts: list[str] = []
  for block in blocks or []:
    kind = block.get("kind")
    if kind == BLOCK_KIND_TEXT:
      if block.get("role") == ROLE_CAPTION:
        original = str(block.get("content") or block.get("source") or "").strip()
        translated = str(block.get("translation") or "").strip()
        for value in (original, translated):
          if value:
            parts.append(value)
        continue
      text = str(block.get("translation") or block.get("source") or "").strip()
      if text:
        parts.append(text)
      continue
    if kind == BLOCK_KIND_TABLE:
      content = str(block.get("content") or "").strip()
      if content:
        parts.append(content)
      continue
    if kind == BLOCK_KIND_REFERENCE:
      content = str(block.get("content") or "").strip()
      if content:
        parts.append(content)
      continue
    if kind == BLOCK_KIND_FIGURE:
      filename = str(block.get("filename") or "").strip()
      page = block.get("page")
      caption = str(block.get("caption") or "").strip()
      if filename:
        label = caption or (f"原文第 {page} 页图片" if page else "原文图片")
        parts.append(f"![{label}](literature-image:{filename})")
      else:
        label = caption or (f"原文第 {page} 页图" if page else "原文图")
        parts.append(f"> {label}（原图未提取，请对照原 PDF）")
  return "\n\n".join(parts)


# ── 图表完整性统计 ────────────────────────────────────────────

def _number_sort_key(value: str) -> list[Any]:
  return [int(part) if part.isdigit() else part.lower() for part in _NUM_SPLIT_RE.split(str(value)) if part]


def _format_numbers(values: list[str]) -> str:
  return "、".join(str(value) for value in values)


def collect_reference_numbers(text: str, kind: str) -> set[str]:
  """扫描原文中出现的 Figure N / Table N（含中文图 / 表）编号"""
  if kind == BLOCK_KIND_FIGURE:
    patterns = (r"(?:fig(?:ure)?s?)\.?\s*(\d+[A-Za-z]?)", r"图\s*(\d+[A-Za-z]?)")
  else:
    patterns = (r"(?:tables?|tab)\.?\s*(\d+[A-Za-z]?)", r"表\s*(\d+[A-Za-z]?)")
  found: set[str] = set()
  for pattern in patterns:
    for match in re.finditer(pattern, text or "", re.IGNORECASE):
      found.add(match.group(1))
  return found


def layout_reference_stats(text: str, blocks: list[dict[str, Any]] | None) -> dict[str, Any]:
  """比对原文图表引用与译文版式块，产出缺失清单与告警（保证不缺少图表）"""
  sealed = blocks or []
  figure_refs = collect_reference_numbers(text, BLOCK_KIND_FIGURE)
  table_refs = collect_reference_numbers(text, BLOCK_KIND_TABLE)
  present_figures = {
    str(block.get("number"))
    for block in sealed
    if block.get("kind") == BLOCK_KIND_FIGURE and block.get("number")
  }
  present_tables = {
    str(block.get("number"))
    for block in sealed
    if block.get("kind") == BLOCK_KIND_TABLE and block.get("number")
  }

  missing_figures = sorted(figure_refs - present_figures, key=_number_sort_key)
  missing_tables = sorted(table_refs - present_tables, key=_number_sort_key)
  unknown_images = sum(
    1 for block in sealed
    if block.get("kind") == BLOCK_KIND_FIGURE and not block.get("number")
  )
  placeholders = sum(
    1 for block in sealed
    if block.get("kind") == BLOCK_KIND_FIGURE and block.get("placeholder")
  )

  warnings: list[str] = []
  if missing_figures:
    warnings.append(
      f"原文出现图注 {_format_numbers(sorted(figure_refs, key=_number_sort_key))} 处，"
      f"其中第 {_format_numbers(missing_figures)} 图未定位到图片，已在原位置保留题注占位。"
    )
  if missing_tables:
    warnings.append(
      f"原文出现表注 {_format_numbers(sorted(table_refs, key=_number_sort_key))} 处，"
      f"其中第 {_format_numbers(missing_tables)} 表未解析出表格内容，请对照原 PDF 核对。"
    )
  if placeholders:
    warnings.append(
      f"有 {placeholders} 张图注未提取到原图（可能为矢量图或提取失败），"
      "已在原位置保留题注，可点击对照原 PDF 查看。"
    )
  if unknown_images:
    warnings.append(
      f"有 {unknown_images} 张图片未匹配到 Figure 编号，已按所在页码就近放置，请核对位置。"
    )

  return {
    "figure_refs": sorted(figure_refs, key=_number_sort_key),
    "table_refs": sorted(table_refs, key=_number_sort_key),
    "figure_blocks": sum(1 for block in sealed if block.get("kind") == BLOCK_KIND_FIGURE),
    "table_blocks": sum(1 for block in sealed if block.get("kind") == BLOCK_KIND_TABLE),
    "caption_blocks": sum(1 for block in sealed if block.get("role") == ROLE_CAPTION),
    "placeholder_figures": placeholders,
    "unknown_images": unknown_images,
    "missing_figures": missing_figures,
    "missing_tables": missing_tables,
    "warnings": warnings,
  }
