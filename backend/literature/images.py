"""文献 PDF 图片提取模块：提取单张位图，并按图题把整幅复合图渲染为一张 PNG"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path

from pypdf import PdfReader

from backend.config import PROJECT_ROOT, settings
from backend.literature.parser import resolve_pdf_path
from backend.literature.translation_layout import figure_caption_number
from backend.utils.text import sanitize_unicode

logger = logging.getLogger(__name__)

# 过滤过小 / 图标类图片（按文件体积）
_MIN_IMAGE_BYTES = 2048
# 单篇文献最多保存的图片数，避免正文图库图过多
_MAX_IMAGES = 30
# 每张图片记录的所在页文字上下文长度
_CONTEXT_CHARS = 300

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff"}


def image_storage_dir(workspace_id: str, literature_id: str) -> Path:
  """文献图片存放目录：data/literature/{workspace_id}/{literature_id}/images/"""
  path = (
    PROJECT_ROOT / settings.literature_dir / workspace_id / literature_id / "images"
  ).resolve()
  path.mkdir(parents=True, exist_ok=True)
  return path


def _safe_image_name(raw_name: str, index: int, ext: str) -> str:
  stem = Path(raw_name or "image").stem
  stem = re.sub(r"[^\w.\- ()]+", "_", stem, flags=re.UNICODE)[:80]
  return f"{index:03d}-{stem or 'image'}{ext}"


def extract_pdf_images(
  pdf_path: str | Path,
  workspace_id: str,
  literature_id: str,
  *,
  max_images: int = _MAX_IMAGES,
) -> list[dict]:
  """从 PDF 中提取图片保存到文献目录，返回图片元信息列表。

  每条记录形如: {filename, page, width, height, context}
  - context 为该图所在页的文字片段，供后续定位图片对应的文章内容
  仅保留体积 >= _MIN_IMAGE_BYTES 的图片，并按内容指纹去重。
  """
  path = resolve_pdf_path(pdf_path)
  if not path.exists():
    return []

  out_dir = image_storage_dir(workspace_id, literature_id)
  # 清理旧图片，避免多次分析后残留
  for old in out_dir.iterdir():
    if old.is_file():
      old.unlink(missing_ok=True)

  try:
    reader = PdfReader(str(path))
  except Exception as e:
    logger.warning("PDF 打开失败，跳过图片提取: %s — %s", path, e)
    return []

  images: list[dict] = []
  seen_hashes: set[str] = set()

  for page_idx, page in enumerate(reader.pages, start=1):
    if len(images) >= max_images:
      break
    try:
      raw_images = list(page.images)
    except Exception as e:
      logger.warning("第 %d 页图片枚举失败: %s", page_idx, e)
      continue

    try:
      page_text = sanitize_unicode(page.extract_text() or "").strip()
    except Exception:
      page_text = ""
    context = page_text[:_CONTEXT_CHARS] if page_text else ""

    for img in raw_images:
      if len(images) >= max_images:
        break
      try:
        data = img.data
        if not isinstance(data, bytes):
          data = bytes(data)
      except Exception:
        continue
      if not data or len(data) < _MIN_IMAGE_BYTES:
        continue

      digest = hashlib.md5(data).hexdigest()
      if digest in seen_hashes:
        continue
      seen_hashes.add(digest)

      raw_ext = Path(img.name or "image.png").suffix.lower()
      ext = raw_ext if raw_ext in _IMAGE_EXTENSIONS else ".png"
      filename = _safe_image_name(img.name or "image", len(images) + 1, ext)

      try:
        (out_dir / filename).write_bytes(data)
      except Exception as e:
        logger.warning("图片写入失败 %s: %s", filename, e)
        continue

      width = height = None
      try:
        pil_img = img.image  # type: ignore[attr-defined]
        width, height = pil_img.size
      except Exception:
        pass

      images.append({
        "filename": filename,
        "page": page_idx,
        "width": width,
        "height": height,
        "context": context,
      })

  logger.info("文献 %s 图片提取完成，共 %d 张", literature_id, len(images))
  return images


# ── 整幅图区域渲染（复合图不拆分） ────────────────────────────
# 一幅流程图常由「矢量流程框 + 多张位图 + 文字标签」拼成，逐位图提取会被拆成
# 多个组件图；这里按图题（Figure N）把整幅图区域整体渲染为一张 PNG。

# 渲染分辨率（基准 / 按位图原始分辨率提升的上限）与单篇上限
_REGION_DPI = 200
_MAX_REGION_DPI = 400
_MAX_REGIONS = 30
# 图形元素聚类容差、图题绑定阈值（单位：磅）
_CLUSTER_GAP = 6.0
_MAX_CAPTION_GAP = 90.0
_MIN_CAPTION_OVERLAP = 0.25
# 过滤装饰性小图形与整页背景
_MIN_GRAPHIC_AREA = 36.0
_PAGE_FILL_RATIO = 0.97
# 区域外扩边距
_REGION_PADDING = 3.0
# 并入区域的文字标签：与图形区域重叠比例下限、最大字数
_MIN_LABEL_INSIDE = 0.6
_MAX_LABEL_CHARS = 200
# 图区域清单缓存文件（存在且不早于 PDF 时直接复用，避免每次翻译重复渲染）
_REGION_MANIFEST = "figure_regions.json"
_REGION_STEM = "figure"


def _rect_area(rect: tuple[float, float, float, float]) -> float:
  return max(rect[2] - rect[0], 0.0) * max(rect[3] - rect[1], 0.0)


def _merge_graphic_rects(
  rects: list[tuple[float, float, float, float]],
  gap: float,
) -> list[tuple[float, float, float, float]]:
  """把相互邻近（间距 <= gap）的图形区域合并成整幅图区域"""
  merged = [tuple(rect) for rect in rects]
  changed = True
  while changed:
    changed = False
    out: list[tuple[float, float, float, float]] = []
    for rect in merged:
      for index, kept in enumerate(out):
        if (
          rect[0] - gap <= kept[2] and kept[0] - gap <= rect[2]
          and rect[1] - gap <= kept[3] and kept[1] - gap <= rect[3]
        ):
          out[index] = (
            min(kept[0], rect[0]), min(kept[1], rect[1]),
            max(kept[2], rect[2]), max(kept[3], rect[3]),
          )
          changed = True
          break
      else:
        out.append(rect)
    merged = out
  return merged


def _horizontal_overlap_ratio(
  rect: tuple[float, float, float, float],
  other: tuple[float, float, float, float],
) -> float:
  """矩形在水平方向的重叠比例（相对较窄的一方）"""
  overlap = min(rect[2], other[2]) - max(rect[0], other[0])
  if overlap <= 0:
    return 0.0
  narrow = min(rect[2] - rect[0], other[2] - other[0])
  return overlap / max(narrow, 1e-6)


def _inside_ratio(
  rect: tuple[float, float, float, float],
  other: tuple[float, float, float, float],
) -> float:
  """矩形落在另一矩形内的面积比例"""
  width = min(rect[2], other[2]) - max(rect[0], other[0])
  height = min(rect[3], other[3]) - max(rect[1], other[1])
  if width <= 0 or height <= 0:
    return 0.0
  return (width * height) / max(_rect_area(rect), 1e-6)


def _page_text_blocks(page) -> list[tuple[str, tuple[float, float, float, float]]]:
  """页面文字块及其区域（用于识别图题、并把图内文字标签并入图区域）"""
  blocks: list[tuple[str, tuple[float, float, float, float]]] = []
  try:
    raw_blocks = page.get_text("dict").get("blocks", [])
  except Exception as e:
    logger.warning("第 %s 页文字解析失败: %s", getattr(page, "number", "?"), e)
    return blocks
  for block in raw_blocks:
    if block.get("type") != 0:
      continue
    text = " ".join(
      span.get("text", "")
      for line in block.get("lines", [])
      for span in line.get("spans", [])
    ).strip()
    bbox = block.get("bbox")
    if not text or not bbox:
      continue
    blocks.append((
      text,
      (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])),
    ))
  return blocks


def _page_graphic_rects(page) -> list[tuple[float, float, float, float]]:
  """收集页面图形元素区域：矢量绘制 + 位图（过滤装饰性小图、整页背景）"""
  page_w, page_h = float(page.rect.width), float(page.rect.height)
  rects: list[tuple[float, float, float, float]] = []
  fill_rects: list[tuple[float, float, float, float]] = []

  def add(raw) -> None:
    if not raw:
      return
    x0, y0, x1, y1 = (float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3]))
    rect = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
    if _rect_area(rect) < _MIN_GRAPHIC_AREA:
      return
    if (
      rect[2] - rect[0] >= _PAGE_FILL_RATIO * page_w
      and rect[3] - rect[1] >= _PAGE_FILL_RATIO * page_h
    ):
      # 整页大小的图形（扫描页整页位图 / 页面边框）：仅在没有其他图形时单独使用
      fill_rects.append(rect)
      return
    rects.append(rect)

  try:
    for item in page.get_drawings():
      add(item.get("rect"))
  except Exception as e:
    logger.warning("第 %s 页矢量图形解析失败: %s", getattr(page, "number", "?"), e)
  try:
    for item in page.get_image_info():
      add(item.get("bbox"))
  except Exception as e:
    logger.warning("第 %s 页位图区域解析失败: %s", getattr(page, "number", "?"), e)

  if not rects and len(fill_rects) == 1:
    rects.append(fill_rects[0])
  return rects


def _bind_caption_region(
  clusters: list[tuple[float, float, float, float]],
  caption_rect: tuple[float, float, float, float],
  used: set[int],
) -> tuple[int, tuple[float, float, float, float]] | None:
  """为图题挑选所属图形区域：优先取图题上方的图形，其次下方的，再比较间距与面积"""
  best: tuple[tuple[int, float, float], int, tuple[float, float, float, float]] | None = None
  for index, cluster in enumerate(clusters):
    if index in used:
      continue
    if _horizontal_overlap_ratio(cluster, caption_rect) < _MIN_CAPTION_OVERLAP:
      continue
    if cluster[3] <= caption_rect[1] + 2.0:
      rank = (0, caption_rect[1] - cluster[3], -_rect_area(cluster))
    elif cluster[1] >= caption_rect[3] - 2.0:
      rank = (1, cluster[1] - caption_rect[3], -_rect_area(cluster))
    else:
      continue
    if rank[1] > _MAX_CAPTION_GAP:
      continue
    if best is None or rank < best[0]:
      best = (rank, index, cluster)
  return (best[1], best[2]) if best else None


def _page_figure_regions(page) -> list[tuple[str, tuple[float, float, float, float]]]:
  """按图题把一页图形聚类成整幅图区域，返回 [(图题编号, 区域矩形), ...]"""
  page_w, page_h = float(page.rect.width), float(page.rect.height)
  if page_w <= 0 or page_h <= 0:
    return []

  blocks = _page_text_blocks(page)
  captions: list[tuple[str, tuple[float, float, float, float]]] = []
  for text, rect in blocks:
    number = figure_caption_number(text)
    if number:
      captions.append((number, rect))
  if not captions:
    return []

  graphics = _page_graphic_rects(page)
  if not graphics:
    return []
  clusters = _merge_graphic_rects(graphics, _CLUSTER_GAP)

  # 把图内的文字标签（流程框文字等）并入所在图形区域，避免标签被裁掉
  labels = [(rect, text) for text, rect in blocks if len(text) <= _MAX_LABEL_CHARS]
  for index, cluster in enumerate(clusters):
    grown = cluster
    for rect, _text in labels:
      if _inside_ratio(rect, cluster) >= _MIN_LABEL_INSIDE:
        grown = (
          min(grown[0], rect[0]), min(grown[1], rect[1]),
          max(grown[2], rect[2]), max(grown[3], rect[3]),
        )
    clusters[index] = grown

  regions: list[tuple[str, tuple[float, float, float, float]]] = []
  used: set[int] = set()
  for number, caption_rect in captions:
    matched = _bind_caption_region(clusters, caption_rect, used)
    if matched is None:
      continue
    matched_index, cluster = matched
    used.add(matched_index)

    region = (
      max(cluster[0] - _REGION_PADDING, 0.0),
      max(cluster[1] - _REGION_PADDING, 0.0),
      min(cluster[2] + _REGION_PADDING, page_w),
      min(cluster[3] + _REGION_PADDING, page_h),
    )
    # 图题本身由题注块原样保留，渲染时裁掉，避免图中重复出现英文题注
    if region[1] + 2.0 < caption_rect[1] < region[3]:
      region = (region[0], region[1], region[2], max(caption_rect[1] - 2.0, region[1]))
    if _rect_area(region) > 0:
      regions.append((number, region))
  return regions


def _region_dpi(
  page,
  region: tuple[float, float, float, float],
  base_dpi: float,
) -> int:
  """按区域内位图的原始分辨率提升渲染精度，避免整幅渲染反而损失清晰度"""
  best = float(base_dpi)
  try:
    infos = page.get_image_info()
  except Exception:
    return int(round(best))
  for info in infos:
    bbox = info.get("bbox")
    if not bbox:
      continue
    x0, y0, x1, y1 = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
    if not (x1 > region[0] and x0 < region[2] and y1 > region[1] and y0 < region[3]):
      continue
    width_pt = x1 - x0
    pixels = float(info.get("width") or 0)
    if width_pt <= 1 or pixels <= 0:
      continue
    best = max(best, pixels / width_pt * 72.0)
  return int(round(min(best, _MAX_REGION_DPI)))


def _read_region_manifest(
  manifest: Path,
  pdf_path: Path,
) -> list[dict] | None:
  """读取图区域清单缓存；缓存缺失 / 过期 / 对应图片不存在时返回 None"""
  try:
    if manifest.stat().st_mtime < pdf_path.stat().st_mtime:
      return None
    payload = json.loads(manifest.read_text("utf-8"))
  except Exception:
    return None
  if not isinstance(payload, list):
    return None
  regions: list[dict] = []
  for item in payload:
    if not isinstance(item, dict) or not item.get("filename"):
      return None
    if not (manifest.parent / str(item["filename"])).exists():
      return None
    regions.append(item)
  return regions


def render_figure_regions(
  pdf_path: str | Path,
  workspace_id: str,
  literature_id: str,
  *,
  dpi: int = _REGION_DPI,
  max_regions: int = _MAX_REGIONS,
  reuse: bool = True,
) -> list[dict]:
  """把 PDF 中每一幅复合图整体渲染为一张 PNG，返回图片元信息列表。

  逐页把矢量绘制与位图按邻近关系聚类成整幅图区域，再按图题（Figure N）绑定，
  整体渲染后保存到文献图片目录，因此一幅流程图只对应一张图片，不会被拆成组件图。
  每条记录形如 {filename, page, width, height, caption, number, context, region}。
  """
  path = resolve_pdf_path(pdf_path)
  if not path.exists():
    return []

  out_dir = image_storage_dir(workspace_id, literature_id)
  manifest = out_dir / _REGION_MANIFEST
  if reuse:
    cached = _read_region_manifest(manifest, path)
    if cached is not None:
      return cached

  try:
    import fitz
  except Exception as e:
    logger.warning("PyMuPDF 不可用，跳过整幅图渲染: %s", e)
    return []

  try:
    doc = fitz.open(str(path))
  except Exception as e:
    logger.warning("PDF 打开失败，跳过整幅图渲染: %s — %s", path, e)
    return []

  regions: list[dict] = []
  try:
    if doc.needs_pass:
      logger.warning("PDF 已加密，跳过整幅图渲染: %s", path)
      return []
    for page_index in range(doc.page_count):
      if len(regions) >= max_regions:
        break
      page = doc[page_index]
      for number, rect in _page_figure_regions(page):
        if len(regions) >= max_regions:
          break
        clip = fitz.Rect(rect)
        if page.rotation:
          # 图题 / 图形坐标处于旋转后的可视坐标系，渲染前需还原
          clip = clip * page.derotation_matrix
        try:
          pix = page.get_pixmap(
            clip=clip,
            dpi=_region_dpi(page, rect, dpi),
            alpha=False,
          )
        except Exception as e:
          logger.warning("第 %d 页图区域渲染失败: %s", page_index + 1, e)
          continue
        filename = _safe_image_name(f"{_REGION_STEM}-{number}", len(regions) + 1, ".png")
        try:
          pix.save(str(out_dir / filename))
        except Exception as e:
          logger.warning("图区域写入失败 %s: %s", filename, e)
          continue
        regions.append({
          "filename": filename,
          "page": page_index + 1,
          "width": pix.width,
          "height": pix.height,
          "caption": "",
          "number": number,
          "context": "",
          "region": True,
        })
  except Exception as e:
    logger.warning("整幅图渲染中断，返回已渲染部分: %s — %s", path, e)
  finally:
    try:
      doc.close()
    except Exception:
      pass

  if regions:
    try:
      manifest.write_text(
        json.dumps(regions, ensure_ascii=False),
        encoding="utf-8",
      )
    except Exception as e:
      logger.warning("图区域清单写入失败: %s", e)
  logger.info("文献 %s 整幅图渲染完成，共 %d 张", literature_id, len(regions))
  return regions