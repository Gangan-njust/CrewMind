"""文件解析工具：读取用户上传的参考文档"""
import logging
from pathlib import Path

from backend.tools.base import BaseTool

logger = logging.getLogger(__name__)

_MAX_CHARS = 8000
_ALLOWED_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".json"}


class FileParserTool(BaseTool):
  name = "file_parser"
  description = "解析文本或 Markdown 参考文件，提取内容供 Agent 参考"

  async def run(self, file_path: str = "", **_) -> str:
    if not file_path:
      return "错误：请提供文件路径"
    try:
      path = Path(file_path).resolve()
      if not path.exists():
        return f"错误：文件不存在 - {file_path}"
      if path.suffix.lower() not in _ALLOWED_SUFFIXES:
        return f"错误：不支持的文件类型 {path.suffix}，仅支持 {_ALLOWED_SUFFIXES}"
      content = path.read_text(encoding="utf-8", errors="replace")
      truncated = content[:_MAX_CHARS]
      if len(content) > _MAX_CHARS:
        truncated += f"\n\n...（已截断，原文共 {len(content)} 字符）"
      return f"### 文件: {path.name}\n\n{truncated}"
    except Exception as e:
      logger.error("File parse error: %s", e)
      return f"文件解析失败: {e}"

  async def run_for_files(self, file_paths: list[str]) -> str:
    if not file_paths:
      return ""
    parts: list[str] = []
    for fp in file_paths:
      result = await self.run(file_path=fp)
      if result and not result.startswith("错误"):
        parts.append(result)
    if not parts:
      return "参考文件解析失败或为空"
    return "\n\n---\n\n".join(parts)
