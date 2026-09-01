"""文献 PDF 图片提取模块：从 PDF 中提取重要图片并保存到文献目录"""
from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

from pypdf import PdfReader

from backend.config import PROJECT_ROOT, settings
from backend.literature.parser import resolve_pdf_path
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
