import { isAbstractSection, type WritingProject } from './api'
import { parseMarkdownHeadings } from './writingHeadings'
import { computeSectionNumbers, getNumberedSectionDisplayName, isNumberedSection } from './writingSectionNumbers'

export interface TocItem {
  indent: number
  label: string
}

function stripMarkdownHeadings(content: string): string {
  return content
    .split('\n')
    .filter(line => !/^#{1,6}\s/.test(line.trim()))
    .join('\n')
    .trim()
}

function sectionPreviewContent(
  section: WritingProject['sections'][number],
  activeSectionId: string | null,
  liveContent: string,
): string {
  const raw = (section.id === activeSectionId ? liveContent : section.content).trim()
  if (isAbstractSection(section.section_type)) {
    return stripMarkdownHeadings(raw)
  }
  return raw
}

export function buildTableOfContentsItems(
  project: WritingProject,
  activeSectionId: string | null,
  liveContent: string,
): TocItem[] {
  const sections = [...project.sections].sort((a, b) => a.sort_order - b.sort_order)
  const sectionNumbers = computeSectionNumbers(sections)
  const items: TocItem[] = []

  for (const section of sections) {
    items.push({
      indent: 0,
      label: getNumberedSectionDisplayName(section, sectionNumbers),
    })

    const content = sectionPreviewContent(section, activeSectionId, liveContent)
    const chapterNum = sectionNumbers.get(section.id)
    const headings = parseMarkdownHeadings(content)
    const counters = [0, 0, 0]
    for (const heading of headings) {
      const idx = heading.level - 2
      counters[idx] += 1
      for (let i = idx + 1; i < counters.length; i += 1) counters[i] = 0

      let label = heading.title
      if (chapterNum != null && isNumberedSection(section)) {
        const numParts = [chapterNum, ...counters.slice(0, idx + 1)]
        label = `${numParts.join('.')} ${heading.title}`
      }
      items.push({ indent: heading.level - 1, label })
    }
  }

  return items
}

export function formatTableOfContentsMarkdown(items: TocItem[]): string {
  if (!items.length) return ''
  const lines = ['## 目录', '']
  for (const item of items) {
    const prefix = '  '.repeat(item.indent)
    lines.push(`${prefix}- ${item.label}`)
  }
  return `${lines.join('\n')}\n\n---\n\n`
}

export function buildFullDocumentMarkdown(
  project: WritingProject,
  activeSectionId: string | null,
  liveContent: string,
): string {
  const sections = [...project.sections].sort((a, b) => a.sort_order - b.sort_order)
  const sectionNumbers = computeSectionNumbers(sections)
  const lines = [`# ${project.title || '未命名论文'}`, '']

  if (project.topic) {
    lines.push(`*${project.topic}*`, '')
  }

  const tocItems = buildTableOfContentsItems(project, activeSectionId, liveContent)
  if (tocItems.length) {
    lines.push(formatTableOfContentsMarkdown(tocItems).trimEnd(), '')
  }

  let hasContent = false
  for (const section of sections) {
    const content = sectionPreviewContent(section, activeSectionId, liveContent)
    if (!content) continue
    hasContent = true
    lines.push(`## ${getNumberedSectionDisplayName(section, sectionNumbers)}`, '', content, '')
  }

  if (!hasContent) {
    lines.push('*暂无章节内容，请在各章节中撰写正文后再预览。*')
  }

  return lines.join('\n').trim() + '\n'
}
