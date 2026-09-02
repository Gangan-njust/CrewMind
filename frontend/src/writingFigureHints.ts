/**
 * 写作图表提醒前端辅助：占位块生成 / 按行插入 / 预览内联提示 / cmasset 解析。
 * 占位标记与后端 figure_hints/export 保持一致：
 *   注释行：<!-- figure:... -->
 *   图片行：![图注占位](待插入图表)
 */
export const PLACEHOLDER_IMAGE_SRC = '待插入图表'

export interface FigureHintItem {
  section_id?: string
  section_type?: string
  display_title?: string
  line: number
  anchor_text?: string
  chart_type: string
  reason?: string
  suggestion?: string
  severity?: string
  key?: string
}

export interface FigureCandidates {
  experiment_charts: FigureCandidate[]
  experiment_metrics: FigureCandidate[]
  experiment_attachments: FigureCandidate[]
  literature_images: FigureCandidate[]
  total: number
  linked_experiment: boolean
  linked_workspace: boolean
}

export interface FigureCandidate {
  kind: string
  title?: string
  filename?: string
  [key: string]: any
}

export interface FigureAssetResult {
  id: string
  project_id: string
  kind: string
  filename: string
  caption: string
  source: Record<string, any>
  created_at: string
  markdown_ref: string
}

/** 生成占位块：一行注释 + 一行待插图，保持与后端导出清理规则兼容。 */
export function figurePlaceholderBlock(chartType: string, note: string, sectionType?: string): string {
  const cleanNote = String(note || '').trim().replace(/[\[\]]/g, '')
  const safeType = String(chartType || '图表').replace(/[\[\]]/g, '')
  const caption = cleanNote && !cleanNote.includes('建议') ? `建议${cleanNote}` : (cleanNote || '此处补图')
  const comment = `<!-- figure:${sectionType || ''}:${safeType}: ${caption} -->`
  const image = `![图：${caption}](待插入图表)`
  return `${comment}\n${image}`
}

/** 在 1 基行号 line 之后插入文本块（前后自动补空行，使块独立成段）。 */
export function insertTextAfterLine(content: string, line: number, insertion: string): string {
  const lines = content.split('\n')
  if (!lines.length) return insertion
  const pos = Math.max(1, Math.min(Math.floor(line), lines.length))
  const block = insertion.replace(/\n+$/, '').replace(/^\n+/, '')

  const before = lines.slice(0, pos)
  const after = lines.slice(pos)
  const spacer: string[] = []
  if (before[before.length - 1]?.trim()) spacer.push('')
  const out = [...before]
  if (spacer.length) out.push('')
  out.push(block)
  if (after[0]?.trim()) out.push('')
  out.push(...after)
  return out.join('\n')
}

function insideCodeFence(lines: string[], index: number): boolean {
  let fence = false
  for (let i = 0; i < index; i += 1) {
    if (/^\s*```/.test(lines[i])) fence = !fence
  }
  return fence
}

/** 预览用：在建议行之前插入引用块提示（编辑器内部生成的 markdown 字符串）。 */
export function withInlineFigureHints(content: string, hints: FigureHintItem[] | null | undefined): string {
  if (!hints?.length) return content
  const lines = content.split('\n')
  const inserts = hints
    .filter(h => h.line >= 1 && h.line <= lines.length && !insideCodeFence(lines, h.line - 1))
    .map(h => ({
      at: h.line - 1,
      text: `\n> 📊 **建议在此插入【${h.chart_type}】**：${h.reason || h.anchor_text || ''}\n`,
    }))
    .sort((a, b) => b.at - a.at)
  if (!inserts.length) return content
  const result = [...lines]
  for (const item of inserts) {
    result.splice(item.at, 0, item.text.trim())
  }
  return result.join('\n')
}

/** 判断该行是否属于"待插入占位"图片（导出时会被剔除）。 */
export function isPlaceholderImageSrc(src: string): boolean {
  return src.trim() === PLACEHOLDER_IMAGE_SRC || src.trim().startsWith('待插入图表')
}

/** cmasset://id → 真实图片 URL（带 token，供 <img> 展示）。 */
export function resolveCmassetSrc(src: string, resolver?: (assetId: string) => string | null): string | null {
  if (!src.startsWith('cmasset://')) return null
  const match = /^cmasset:\/\/([a-zA-Z0-9-]+)/.exec(src)
  if (!match || !resolver) return null
  return resolver(match[1])
}
