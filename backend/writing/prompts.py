"""学术写作 LLM 提示词模板"""
from backend.writing.templates import SECTION_LABELS

SECTION_WRITING_GUIDES = {
  "intro": """引言写作结构：
1. 研究背景：介绍领域现状与重要性
2. 研究空白：指出现有研究的不足
3. 研究问题：明确提出待解决的核心问题
4. 研究目标：说明本研究的目的与贡献""",

  "methods": """方法章节写作结构：
1. 实验设计：描述总体研究设计与假设
2. 数据收集：说明数据来源、样本与采集流程
3. 分析方法：详述算法、模型或统计方法""",

  "results": """结果章节写作结构：
1. 主要发现：概括核心实验结果
2. 数据呈现：用表格/图表描述关键数据
3. 统计分析：报告显著性检验与置信区间""",

  "discussion": """讨论章节写作结构：
1. 结果解释：解读实验结果的含义
2. 与已有研究对比：比较本研究与文献的差异
3. 研究意义：阐述理论与实践价值
4. 局限性：诚实讨论研究的不足与未来方向""",

  "abstract": "中文摘要应包含研究背景、方法、主要结果与结论，控制在约300字以内，输出为连贯中文段落，不要使用任何 Markdown 标题或小节标题。",
  "abstract_en": "English Abstract should cover background, methods, main results and conclusions in about 250-300 words. Write in formal academic English as continuous paragraphs without any Markdown headings.",
  "conclusion": "结论应总结主要贡献、回答研究问题，并指出未来工作方向。",
  "related_work": "相关工作应系统梳理领域进展，按主题分类，并指出现有方法的不足。",
  "acknowledgments": "致谢部分感谢导师、资助项目与协助人员。",
}

OUTLINE_GENERATION_PROMPT = """你是一位学术论文写作专家。请根据以下研究信息，生成详细的论文大纲。

论文类型：{paper_type_label}
研究主题：{topic}
目标期刊/会议：{target_journal}

已有研究方案内容（如有）：
{source_content}

请输出 JSON 格式，结构如下：
{{
  "title_suggestion": "建议论文标题",
  "sections": [
    {{
      "section_type": "intro",
      "title": "章节标题",
      "outline_points": ["要点1", "要点2"],
      "subsections": [
        {{
          "level": 2,
          "title": "二级小节标题",
          "outline_points": ["小节要点1"]
        }},
        {{
          "level": 3,
          "title": "三级小节标题",
          "outline_points": ["小节要点1"]
        }}
      ],
      "writing_hints": "写作提示"
    }}
  ]
}}

section_type 必须是以下之一：{section_types}
每个章节至少 3 个 outline_points，writing_hints 应具体可操作。
subsections 为章节内二/三/四级小节标题规划：level 仅可为 2、3、4；abstract（摘要）与 abstract_en（Abstract）不使用 subsections；除摘要类章节外，主要章节应包含至少 2 个 subsections，并体现合理的层级嵌套。"""

CONTINUE_PROMPT = """你是一位学术论文写作助手。请根据给定上下文，以学术语气续写段落。

续写长度：{length_label}（短=1-2句，中=1段，长=2-3段）
章节类型：{section_label}
研究主题：{topic}

已有上下文（段落开头）：
{prefix}

前后文参考：
{context}

要求：
- 保持学术语气，避免口语化
- 与上下文逻辑连贯
- 不要重复已有内容
- 直接输出续写内容，不要解释"""

EXPAND_PROMPT = """你是一位学术论文写作专家。请根据用户提供的章节草稿，重新整合并扩写为更完整、更规范的学术段落。

扩写强度：{length_label}
- 短：在保留核心观点基础上适度扩展（约 1.5 倍篇幅）
- 中：重新组织结构并充实论述（约 2 倍篇幅）
- 长：全面扩写，补充论证层次与学术表达（约 2.5–3 倍篇幅）

章节类型：{section_label}
研究主题：{topic}

用户输入的章节内容：
{input_text}

写作要求：
1. 保留原文的核心观点、数据与关键术语，不要编造不存在的实验结果
2. 重新整合段落结构，优化逻辑顺序与章节内衔接
3. 使用正式学术语气，避免口语化与重复表述
4. 根据章节类型补全应有的论述层次（如引言需含背景-空白-问题-目标）
5. 除 abstract（摘要）与 abstract_en（Abstract）外，可使用 Markdown 二/三/四级小节标题（##、###、####）组织章节内部结构，但不要添加与章节同级或更高层级的一级标题
6. 摘要类章节须为连贯段落，禁止任何标题（中文摘要约300字，英文 Abstract 约250-300词）
7. 直接输出扩写后的完整章节正文，不要添加解释或章节级标题"""

STRUCTURED_EXPAND_PROMPT = """你是一位学术论文写作专家。请根据给定的目录结构，逐小节扩写当前章节内容。

章节类型：{section_label}
研究主题：{topic}

章节前言（如有，保留并适当润色，不要重复展开各小节主题）：
{preamble}

全局写作要求：
{global_requirements}

各小节扩写任务（请严格按顺序输出，每个小节使用指定的 Markdown 标题层级）：
{items_spec}

输出要求：
1. 按上述顺序输出全部小节，每个小节以对应层级的 Markdown 标题开头（## / ### / ####）
2. 每个小节正文字数应尽量接近「目标字数」，允许 ±15% 浮动
3. 保留各小节已有内容中的核心观点、数据与术语，不要编造不存在的实验结果
4. 满足各小节的专属写作要求，并与全局要求保持一致
5. 小节之间逻辑连贯，避免重复论述
6. 若某小节暂无已有内容，请根据其标题、大纲要点与写作要求新撰
7. 直接输出完整章节正文，不要输出解释、JSON 或额外说明"""

STRUCTURED_POLISH_PROMPT = """你是一位学术写作润色与重写专家。请根据目录结构，逐小节对已有内容进行润色或按指定要求重写。

润色强度：{style_label}
- 保守：修正语法与明显错误，尽量保留原句与篇幅
- 中等：优化句式与衔接，替换口语表达，可适度调整篇幅
- 深度：重构论述逻辑与段落结构，显著提升学术表达，可按目标字数重写

章节类型：{section_label}
研究主题：{topic}

章节前言（如有，请润色但勿展开各小节主题）：
{preamble}

全局重写要求：
{global_requirements}

各小节任务（按顺序处理，保留指定 Markdown 标题层级）：
{items_spec}

输出要求：
1. 输出 JSON，包含 polished_text 与 changes_summary 两个字段
2. polished_text 为润色/重写后的完整章节 Markdown 正文，按顺序包含全部小节标题（## / ### / ####）
3. 每个小节篇幅应尽量接近「目标字数」，允许 ±15% 浮动
4. 保留各小节核心观点、数据与术语，不要编造不存在的实验结果
5. 严格满足各小节的专属重写要求，并与全局要求一致
6. 若某小节要求「缩写/精简」，不得超过目标字数；要求「扩写/充实」时可适度超出
7. changes_summary 列出 3–8 条主要改动说明（中文）"""

POLISH_PROMPT = """你是一位学术写作润色专家。请优化以下文本。

润色强度：{style_label}
- 保守润色：修正语法和明显错误，尽量保留原句
- 中等润色：优化句式，替换口语表达，改进衔接
- 深度润色：重构段落逻辑，提升学术表达质量

章节类型：{section_label}

原文：
{text}

请输出 JSON：
{{
  "polished_text": "润色后的完整文本",
  "changes_summary": ["改动说明1", "改动说明2"]
}}"""

TERM_CHECK_PROMPT = """你是一位学术术语一致性检查专家。请分析以下全文，识别关键术语的不一致用法。

全文内容：
{full_text}

请输出 JSON：
{{
  "terms": [
    {{
      "concept": "概念名称",
      "variants": ["变体1", "变体2"],
      "recommended": "推荐统一术语",
      "occurrences": [{{"text": "出现的文本片段", "section": "章节"}}]
    }}
  ],
  "suggestions": ["统一建议1"]
}}"""

COHERENCE_CHECK_PROMPT = """你是一位学术论文逻辑审查专家。请检查以下各章节之间的逻辑连贯性。

论文大纲：
{outline}

各章节内容摘要：
{sections_summary}

请输出 JSON：
{{
  "issues": [
    {{
      "severity": "high|medium|low",
      "location": "章节间位置",
      "description": "问题描述",
      "suggestion": "建议补充的过渡或内容"
    }}
  ],
  "overall_score": 0-100,
  "summary": "总体评价"
}}"""

STYLE_CHECK_PROMPT = """你是一位学术写作规范审查专家。请检查以下文本的学术表达规范性。

章节类型：{section_label}
文本：
{text}

请检查：
1. 第一人称使用（中文论文通常避免"我/我们"，英文视期刊要求）
2. 时态使用（方法/结果用过去时，结论/普遍真理用现在时）
3. 数据报告格式（如"均值±标准差"是否规范）

请输出 JSON：
{{
  "issues": [
    {{
      "type": "first_person|tense|data_format|other",
      "text": "问题文本",
      "suggestion": "修改建议",
      "severity": "high|medium|low"
    }}
  ],
  "score": 0-100
}}"""

CITATION_RECOMMEND_PROMPT = """你是一位文献引用推荐专家。用户选中了以下文本，请从候选文献中推荐最相关的引用。

选中文字：
{selected_text}

章节上下文：
{context}

候选文献：
{literature_list}

请输出 JSON：
{{
  "recommendations": [
    {{
      "literature_id": "文献ID",
      "relevance_score": 0.0-1.0,
      "reason": "推荐理由",
      "suggested_position": "引用位置建议"
    }}
  ]
}}

按相关度降序排列，最多推荐 5 篇。"""

CITATION_SENTENCE_PROMPT = """请为以下文献生成多种学术引用句式。

文献信息：
标题：{title}
作者：{authors}
年份：{year}
期刊：{journal}

核心观点/引用目的：{purpose}

请输出 JSON：
{{
  "sentences": [
    {{
      "style": "author_prominent|idea_prominent|chronological",
      "style_label": "作者突出|观点突出|时间顺序",
      "text": "引用句式"
    }}
  ]
}}

每种风格至少 2 个句式，共 6 个以上。"""

CITATION_COMPLETENESS_PROMPT = """你是一位学术引用完整性审查专家。请扫描全文，识别需要引用但缺失文献支撑的论断。

全文：
{full_text}

请输出 JSON：
{{
  "missing_citations": [
    {{
      "text": "需要引用的论断",
      "section": "所在章节",
      "reason": "为何需要引用",
      "suggested_keywords": ["检索关键词"]
    }}
  ]
}}"""


def get_section_guide(section_type: str) -> str:
  return SECTION_WRITING_GUIDES.get(section_type, "请按学术规范撰写该章节。")


def get_section_label(section_type: str) -> str:
  return SECTION_LABELS.get(section_type, section_type)
