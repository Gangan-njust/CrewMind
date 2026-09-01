"""论文章节段落首行缩进（两个全角空格，约等于一个 Tab / 2 字符）"""
import re

FULL_WIDTH_INDENT = "　　"
_SKIP_FIRST_LINE = re.compile(
  r"^(#{1,6}\s|关键词[：:]|Keywords[：:]|\[\d+\]|[-*•·]\s|\||```)"
)


def _line_has_indent(line: str) -> bool:
  return line.startswith(FULL_WIDTH_INDENT) or line.startswith("\t")


def ensure_paragraph_first_indent(content: str) -> str:
  if not content.strip():
    return content

  blocks = content.split("\n\n")
  result: list[str] = []
  for block in blocks:
    if not block.strip():
      result.append(block)
      continue

    lines = block.split("\n")
    first = lines[0]
    stripped_first = first.strip()

    if _SKIP_FIRST_LINE.match(stripped_first) or _line_has_indent(first):
      result.append(block)
      continue

    lines[0] = FULL_WIDTH_INDENT + first.lstrip()
    result.append("\n".join(lines))

  return "\n\n".join(result)
