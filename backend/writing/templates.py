"""论文类型模板与 IMRaD 结构定义"""

SECTION_LABELS = {
  "abstract": "摘要",
  "abstract_en": "Abstract",
  "intro": "引言",
  "methods": "方法",
  "results": "结果",
  "discussion": "讨论",
  "conclusion": "结论",
  "related_work": "相关工作",
  "acknowledgments": "致谢",
  "appendix": "附录",
}

ABSTRACT_SECTION_TYPES = frozenset({"abstract", "abstract_en"})


def is_abstract_section(section_type: str) -> bool:
  return section_type in ABSTRACT_SECTION_TYPES


DEFAULT_SECTIONS = {
  "journal": ["abstract", "abstract_en", "intro", "methods", "results", "discussion", "conclusion"],
  "conference": ["abstract", "abstract_en", "intro", "methods", "results", "discussion", "conclusion"],
  "thesis": [
    "abstract", "abstract_en", "intro", "related_work", "methods", "results",
    "discussion", "conclusion", "acknowledgments",
  ],
}

PAPER_TEMPLATES = {
  "journal": {
    "label": "期刊论文",
    "description": "标准 IMRaD 结构，适用于 SCI/EI 期刊投稿",
    "sections": DEFAULT_SECTIONS["journal"],
    "word_targets": {
      "abstract": "280-320",
      "abstract_en": "250-350",
      "intro": "800-1500",
      "methods": "1000-2000",
      "results": "800-1500",
      "discussion": "1000-2000",
      "conclusion": "300-500",
    },
  },
  "conference": {
    "label": "会议论文",
    "description": "精简 IMRaD 结构，篇幅较短",
    "sections": DEFAULT_SECTIONS["conference"],
    "word_targets": {
      "abstract": "280-320",
      "abstract_en": "250-350",
      "intro": "500-800",
      "methods": "600-1000",
      "results": "500-800",
      "discussion": "500-800",
      "conclusion": "200-300",
    },
  },
  "thesis": {
    "label": "学位论文",
    "description": "完整学位论文结构，含相关工作与致谢",
    "sections": DEFAULT_SECTIONS["thesis"],
    "word_targets": {
      "abstract": "280-320",
      "abstract_en": "250-350",
      "intro": "3000-5000",
      "related_work": "5000-8000",
      "methods": "3000-5000",
      "results": "3000-5000",
      "discussion": "3000-5000",
      "conclusion": "1000-2000",
      "acknowledgments": "200-500",
    },
  },
}

CITATION_FORMATS = {
  "gb7714": {"label": "GB/T 7714", "description": "中国国家标准"},
  "apa": {"label": "APA 7th", "description": "美国心理学会格式"},
  "mla": {"label": "MLA 9th", "description": "现代语言协会格式"},
  "chicago": {"label": "Chicago", "description": "芝加哥手册格式"},
}


def section_display_title(section: dict) -> str:
  if section.get("title"):
    return section["title"]
  return SECTION_LABELS.get(section.get("section_type", ""), section.get("section_type", ""))
