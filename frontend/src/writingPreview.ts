import { getSectionDisplayName, isAbstractSection, type WritingProject } from './api'

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

export function buildFullDocumentMarkdown(
  project: WritingProject,
  activeSectionId: string | null,
  liveContent: string,
): string {
  const sections = [...project.sections].sort((a, b) => a.sort_order - b.sort_order)
  const lines = [`# ${project.title || '未命名论文'}`, '']

  if (project.topic) {
    lines.push(`*${project.topic}*`, '')
  }

  let hasContent = false
  for (const section of sections) {
    const content = sectionPreviewContent(section, activeSectionId, liveContent)
    if (!content) continue
    hasContent = true
    lines.push(`## ${getSectionDisplayName(section)}`, '', content, '')
  }

  if (!hasContent) {
    lines.push('*暂无章节内容，请在各章节中撰写正文后再预览。*')
  }

  return lines.join('\n').trim() + '\n'
}
