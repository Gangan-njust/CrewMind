export type SubheadingLevel = 2 | 3 | 4

export interface ParsedHeading {
  level: SubheadingLevel
  title: string
  line: number
  offset: number
}

export interface OutlineSubsection {
  level: SubheadingLevel
  title: string
  outline_points?: string[]
}

const HEADING_RE = /^(#{2,4})\s+(.+?)\s*$/

export function headingMarkdown(level: SubheadingLevel, title: string): string {
  return `${'#'.repeat(level)} ${title.trim()}`
}

export function parseMarkdownHeadings(content: string): ParsedHeading[] {
  const headings: ParsedHeading[] = []
  let offset = 0
  content.split('\n').forEach((line, lineIndex) => {
    const match = line.match(HEADING_RE)
    if (match) {
      const level = match[1].length as SubheadingLevel
      headings.push({
        level,
        title: match[2].trim(),
        line: lineIndex,
        offset,
      })
    }
    offset += line.length + 1
  })
  return headings
}

export function lineStartOffset(content: string, lineNumber: number): number {
  if (lineNumber <= 0) return 0
  const lines = content.split('\n')
  return lines.slice(0, lineNumber).join('\n').length + 1
}

export function insertMarkdownHeading(
  content: string,
  selectionStart: number,
  selectionEnd: number,
  level: SubheadingLevel,
  explicitTitle?: string,
): { text: string; cursor: number; selectEnd?: number } {
  const selected = content.slice(selectionStart, selectionEnd).trim()
  const defaultTitle = '小节标题'
  const title = explicitTitle?.trim() || selected || defaultTitle
  const headingLine = headingMarkdown(level, title)
  const usePlaceholder = !explicitTitle && !selected

  const lineStart = content.lastIndexOf('\n', Math.max(0, selectionStart - 1)) + 1
  const lineEndIdx = content.indexOf('\n', selectionStart)
  const lineEnd = lineEndIdx === -1 ? content.length : lineEndIdx
  const currentLine = content.slice(lineStart, lineEnd)
  const lineIsEmpty = currentLine.trim() === ''

  let next: string
  let cursor: number

  if (selected && !explicitTitle) {
    next = content.slice(0, lineStart) + headingLine + content.slice(lineEnd)
    cursor = lineStart + headingLine.length
    return { text: next, cursor }
  }

  if (lineIsEmpty) {
    next = content.slice(0, lineStart) + headingLine + content.slice(lineEnd)
    cursor = lineStart + headingLine.length
  } else {
    const insertAt = explicitTitle ? selectionStart : lineEnd
    const prefix = content.slice(0, insertAt)
    const suffix = content.slice(insertAt)
    const needsLeadingBreak = prefix.length > 0 && !prefix.endsWith('\n')
    const block = `${needsLeadingBreak ? '\n\n' : ''}${headingLine}\n\n`
    next = prefix + block + suffix.replace(/^\n+/, '')
    cursor = prefix.length + block.length
  }

  if (usePlaceholder) {
    const titleStart = next.lastIndexOf(defaultTitle, cursor)
    if (titleStart >= 0 && titleStart <= cursor) {
      return { text: next, cursor: titleStart, selectEnd: titleStart + defaultTitle.length }
    }
  }

  return { text: next, cursor }
}

export function getSectionHeadings(
  sectionContent: string,
  activeSectionId: string | null,
  sectionId: string,
  liveContent: string,
): ParsedHeading[] {
  const content = sectionId === activeSectionId ? liveContent : sectionContent
  return parseMarkdownHeadings(content)
}

export function normalizeOutlineSubsections(raw: unknown): OutlineSubsection[] {
  if (!Array.isArray(raw)) return []
  return raw
    .map(item => {
      if (!item || typeof item !== 'object') return null
      const level = Number((item as OutlineSubsection).level)
      const title = String((item as OutlineSubsection).title || '').trim()
      if (!title || level < 2 || level > 4) return null
      const outline_points = Array.isArray((item as OutlineSubsection).outline_points)
        ? (item as OutlineSubsection).outline_points!.map(p => String(p).trim()).filter(Boolean)
        : undefined
      return { level: level as SubheadingLevel, title, outline_points }
    })
    .filter(Boolean) as OutlineSubsection[]
}
