"""论文章节边界识别"""
import re
from dataclasses import dataclass, field

SECTION_KEYWORDS: dict[str, list[str]] = {
  "introduction": ["INTRODUCTION", "Introduction", "BACKGROUND", "Background", "引言", "绪论", "研究背景"],
  "methods": ["METHODS", "METHOD", "MATERIALS AND METHODS", "Materials and Methods", "方法", "研究方法", "实验方法"],
  "results": ["RESULTS", "Results", "结果", "实验结果"],
  "discussion": ["DISCUSSION", "Discussion", "讨论"],
  "conclusion": ["CONCLUSION", "CONCLUSIONS", "Conclusion", "Conclusions", "结论", "总结"],
}


@dataclass
class SectionContent:
  name: str
  content: str = ""


@dataclass
class StructuredSections:
  sections: dict[str, SectionContent] = field(default_factory=dict)
  full_text: str = ""

  def to_dict(self) -> dict[str, str]:
    return {k: v.content for k, v in self.sections.items()}


def _find_section_starts(text: str) -> list[tuple[int, str, str]]:
  """返回 [(位置, section_key, matched_heading), ...] 按位置排序"""
  hits: list[tuple[int, str, str]] = []
  for section_key, keywords in SECTION_KEYWORDS.items():
    for kw in keywords:
      pattern = rf"(?m)^\s*{re.escape(kw)}\s*$"
      for match in re.finditer(pattern, text):
        hits.append((match.start(), section_key, kw))
  hits.sort(key=lambda x: x[0])
  return hits


def split_sections(text: str) -> StructuredSections:
  """基于关键词匹配识别章节边界"""
  if not text.strip():
    return StructuredSections(full_text=text)

  hits = _find_section_starts(text)
  if not hits:
    return StructuredSections(
      sections={"full": SectionContent(name="full", content=text)},
      full_text=text,
    )

  sections: dict[str, SectionContent] = {}
  for i, (start, section_key, heading) in enumerate(hits):
    end = hits[i + 1][0] if i + 1 < len(hits) else len(text)
    content = text[start:end].strip()
    if section_key not in sections or len(content) > len(sections[section_key].content):
      sections[section_key] = SectionContent(name=heading, content=content)

  if hits[0][0] > 0:
    preamble = text[: hits[0][0]].strip()
    if preamble:
      sections.setdefault("preamble", SectionContent(name="preamble", content=preamble))

  return StructuredSections(sections=sections, full_text=text)
