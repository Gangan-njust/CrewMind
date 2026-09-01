"""PDF 文本提取模块"""
from pathlib import Path

from pypdf import PdfReader

from backend.config import PROJECT_ROOT
from backend.utils.text import sanitize_unicode

try:
  import magic
except ImportError:
  magic = None

_TEXT_CACHE: dict[str, str] = {}


def resolve_pdf_path(pdf_path: str | Path) -> Path:
  """解析 PDF 路径，兼容绝对路径与相对路径"""
  path = Path(pdf_path)
  candidates = [path]
  if not path.is_absolute():
    candidates.append(PROJECT_ROOT / path)
  for candidate in candidates:
    resolved = candidate.resolve()
    if resolved.exists():
      return resolved
  return path.resolve()


def is_pdf_file(path: str | Path, content: bytes | None = None) -> bool:
  p = Path(path)
  if p.suffix.lower() != ".pdf":
    return False
  if content is not None:
    if content[:4] == b"%PDF":
      return True
    if magic is not None:
      mime = magic.from_buffer(content, mime=True)
      return mime == "application/pdf"
  return True


def extract_full_text(pdf_path: str | Path, *, use_cache: bool = True) -> str:
  """从 PDF 提取全文文本"""
  path = resolve_pdf_path(pdf_path)
  key = str(path)
  if use_cache and key in _TEXT_CACHE:
    return _TEXT_CACHE[key]

  if not path.exists():
    raise FileNotFoundError(f"PDF 文件不存在: {path}")

  try:
    reader = PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages:
      text = page.extract_text() or ""
      if text.strip():
        parts.append(text)

    full_text = sanitize_unicode("\n\n".join(parts).strip())
  except Exception as e:
    err = str(e)
    if "cryptography" in err.lower() or "AES algorithm" in err:
      raise RuntimeError(
        "PDF 为加密格式，需要安装 cryptography 依赖。"
        "请运行: py -m pip install \"cryptography>=3.1\" 后重启服务"
      ) from e
    raise

  if use_cache:
    _TEXT_CACHE[key] = full_text
  return full_text


def extract_batch(pdf_paths: list[str | Path], *, use_cache: bool = True) -> dict[str, str]:
  """批量提取 PDF 文本，返回 {路径: 文本}"""
  results: dict[str, str] = {}
  for pdf_path in pdf_paths:
    path = Path(pdf_path)
    try:
      results[str(path)] = extract_full_text(path, use_cache=use_cache)
    except Exception as e:
      results[str(path)] = f"[提取失败: {e}]"
  return results


def clear_text_cache() -> None:
  _TEXT_CACHE.clear()
