"""用户上传参考文件管理"""
import re
import uuid
from pathlib import Path

from backend.config import PROJECT_ROOT, settings

_ALLOWED_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".json"}
_MAX_BYTES = 2 * 1024 * 1024  # 2 MB


def _uploads_dir() -> Path:
  path = (PROJECT_ROOT / settings.uploads_dir).resolve()
  path.mkdir(parents=True, exist_ok=True)
  return path


def _safe_filename(name: str) -> str:
  base = Path(name).name
  base = re.sub(r"[^\w.\-]+", "_", base, flags=re.UNICODE)
  return base[:120] or "upload.txt"


class UploadStore:
  def save(self, content: bytes, filename: str) -> dict[str, str]:
    if len(content) > _MAX_BYTES:
      raise ValueError(f"文件过大，最大允许 {_MAX_BYTES // 1024 // 1024} MB")

    suffix = Path(filename).suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
      raise ValueError(f"不支持的文件类型，仅允许: {', '.join(sorted(_ALLOWED_SUFFIXES))}")

    file_id = str(uuid.uuid4())
    safe_name = _safe_filename(filename)
    stored_name = f"{file_id}_{safe_name}"
    path = _uploads_dir() / stored_name
    path.write_bytes(content)

    return {
      "id": file_id,
      "filename": safe_name,
      "stored_name": stored_name,
      "path": str(path),
      "size": len(content),
    }

  def get_path(self, file_id: str) -> Path | None:
    directory = _uploads_dir()
    for path in directory.iterdir():
      if path.is_file() and path.name.startswith(f"{file_id}_"):
        return path
    return None

  def resolve_paths(self, file_ids: list[str]) -> list[str]:
    paths: list[str] = []
    for fid in file_ids:
      path = self.get_path(fid)
      if path:
        paths.append(str(path))
    return paths


upload_store = UploadStore()
