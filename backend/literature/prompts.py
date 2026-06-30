"""文献分析提示词模板"""

CORE_EXTRACTION_PROMPT = """你是一位专业的学术文献分析专家。请从以下论文内容中提取结构化信息。

## 论文信息
标题：{title}
作者：{authors}
期刊：{journal}
年份：{year}

## 论文内容（节选）
{content}

## 输出要求
请以 JSON 格式输出，包含以下字段：
- research_background: 研究背景（200字以内）
- research_goal: 研究目标（100字以内）
- methods_summary: 方法概述（200字以内）
- key_findings: 主要发现（字符串数组，3-5条）
- conclusion: 结论（150字以内）
- limitations: 局限性（字符串数组，2-4条）
- contribution_summary: 核心贡献摘要（150字以内）

只输出 JSON，不要其他文字。"""

FORMULA_EXTRACTION_PROMPT = """你是一位精通数学与工程公式的学术分析专家。请从以下论文内容中识别并提取**关键公式**（如损失函数、评估指标、目标函数、算法核心方程、性能度量等）。

## 论文信息
标题：{title}
方法概述：{methods}

## 论文内容（节选，重点关注方法与实验部分）
{content}

## 输出要求
请以 JSON 格式输出，包含 formulas 数组。每个公式对象包含：
- name: 公式名称（中文，如「交叉熵损失函数」）
- latex: LaTeX 格式的公式表达式（不含 $$ 包裹，使用标准 LaTeX 语法）
- variables: 变量说明（字符串数组，如 ["y_i: 真实标签", "\\\\hat{{y}}_i: 预测概率"]）
- explanation: 对该公式的详细解释（150-300字，说明数学含义、物理/统计意义及在本文中的具体用途）
- context: 公式在论文中的使用场景（1-2句话）

要求：
1. 优先提取论文中明确出现或定义的核心公式，通常 2-6 个
2. 若论文为综述/无明确公式，可提取文中重点讨论的代表性公式；若完全无公式则输出空数组
3. latex 字段须可被 KaTeX 渲染，避免使用不支持的宏包

只输出 JSON，不要其他文字。"""

INNOVATION_PROMPT = """分析以下论文的创新点，输出 JSON：
{{"innovations": ["创新点1", "创新点2", ...], "novelty_score": 0-10}}

论文标题：{title}
内容摘要：{content}"""

TAG_GENERATION_PROMPT = """为以下论文生成标签，输出 JSON：
{{"method_tags": ["方法标签"], "domain_tags": ["领域标签"]}}

论文标题：{title}
方法概述：{methods}
研究领域关键词：{user_topic}"""

CITATION_TEMPLATES_PROMPT = """为以下论文生成 3-5 条引用句式（中英文各一条为一组），输出 JSON：
{{"citations": [{{"zh": "中文引用句式", "en": "English citation sentence"}}]}}

论文：{title}
作者：{authors}
主要发现：{findings}"""

RELEVANCE_SCORE_PROMPT = """评估以下论文与用户研究方向的匹配度（0-10分），输出 JSON：
{{"relevance_score": 分数, "recommendation_score": 分数, "reason": "简要理由"}}

用户研究方向：{user_topic}
论文标题：{title}
论文摘要：{abstract}
核心贡献：{contribution}"""

RESEARCH_GAP_PROMPT = """基于以下多篇已分析文献，识别该领域的研究空白与未解决问题。

用户研究方向：{user_topic}

## 已分析文献摘要
{literature_summaries}

请输出 JSON：
{{"research_gaps": ["空白1", "空白2", ...], "future_directions": ["方向1", "方向2", ...]}}"""

PROPOSAL_CONTEXT_PROMPT = """以下为用户文献库中选定文献的分析结果，请在撰写开题报告时**优先引用**这些文献，并在正文中用 [编号] 标注引用来源。

## 用户研究主题
{topic}

## 选定文献分析
{literature_context}

## 数据源模式
{mode_description}

请确保引用内容与上述文献分析一致，不得虚构未提供的文献信息。"""
