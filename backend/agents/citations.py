"""参考文献与引用格式约定"""

REFERENCE_CITATION_RULES = """
## 参考文献与引用规范（必须遵守）

1. **正文引用**：在引用观点、数据或结论处使用方括号编号，如 [1]、[2]。
2. **文末参考文献**：在全文末尾增设「## 参考文献」章节，列出正文引用的全部文献。每条格式示例：
   - `[1] 作者. 文献标题. 期刊/来源, 年份. [链接](完整URL)`
   - 必须为每条文献提供可访问的链接（使用检索结果中的 url 字段，或 DOI 链接 `https://doi.org/...`）。
3. **文献数据库说明**：在参考文献之后增设「## 文献数据库说明」章节，说明本次撰写所依据的外部文献检索数据库（如 Semantic Scholar、PubMed），以及用户上传的参考文件（如有）。
4. **真实性**：仅引用检索结果或参考文件中实际提供的文献；无检索结果时明确标注「需人工补充引用」，不得虚构 DOI、PMID 或链接。
"""


def format_citation_instruction(databases_used: list[str] | None = None) -> str:
  """生成注入提示词的引用规范说明，可附带本次检索数据库信息。"""
  parts = [REFERENCE_CITATION_RULES.strip()]
  if databases_used:
    db_text = "、".join(databases_used)
    parts.append(
      f"本次文献检索使用的数据库：**{db_text}**。"
      "请在「文献数据库说明」中如实写明上述数据库及检索词。"
    )
  return "\n\n".join(parts)
