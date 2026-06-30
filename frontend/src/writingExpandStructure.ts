import type { OutlineSubsection } from './api'
import {
  parseMarkdownHeadings,
  type ParsedHeading,
  type SubheadingLevel,
} from './writingHeadings'

export interface ExpandStructureItem {
  id: string
  title: string
  level: SubheadingLevel
  wordTarget: number
  requirements: string
  existingContent: string
  outlinePoints: string[]
  enabled: boolean
}

const DEFAULT_WORD_TARGETS: Record<SubheadingLevel, number> = {
  2: 400,
  3: 250,
  4: 150,
}

export function defaultWordTarget(level: SubheadingLevel): number {
  return DEFAULT_WORD_TARGETS[level]
}

export function splitContentByHeadings(content: string): {
  preamble: string
  blocks: Array<{ heading: ParsedHeading; body: string }>
} {
  const headings = parseMarkdownHeadings(content)
  const lines = content.split('\n')
  if (!headings.length) {
    return { preamble: content.trim(), blocks: [] }
  }

  const blocks = headings.map((heading, index) => {
    const startLine = heading.line + 1
    const endLine = index + 1 < headings.length ? headings[index + 1].line : lines.length
    return {
      heading,
      body: lines.slice(startLine, endLine).join('\n').trim(),
    }
  })

  return {
    preamble: lines.slice(0, headings[0].line).join('\n').trim(),
    blocks,
  }
}

function makeItemId(prefix: string, title: string, line?: number): string {
  return `${prefix}-${line ?? 0}-${title.toLowerCase().replace(/\s+/g, '-')}`
}

export function buildExpandStructureItems(
  content: string,
  outlineSubsections?: OutlineSubsection[],
  preserve?: ExpandStructureItem[],
): ExpandStructureItem[] {
  const preserveMap = new Map(preserve?.map(item => [item.title.toLowerCase(), item]) ?? [])
  const { blocks } = splitContentByHeadings(content)
  const items: ExpandStructureItem[] = []

  for (const block of blocks) {
    const key = block.heading.title.toLowerCase()
    const prev = preserveMap.get(key)
    items.push({
      id: prev?.id ?? makeItemId('h', block.heading.title, block.heading.line),
      title: block.heading.title,
      level: block.heading.level,
      wordTarget: prev?.wordTarget ?? defaultWordTarget(block.heading.level),
      requirements: prev?.requirements ?? '',
      existingContent: block.body,
      outlinePoints: prev?.outlinePoints ?? [],
      enabled: prev?.enabled ?? true,
    })
  }

  const existingTitles = new Set(items.map(item => item.title.toLowerCase()))
  for (const sub of outlineSubsections ?? []) {
    const key = sub.title.toLowerCase()
    const existing = items.find(item => item.title.toLowerCase() === key)
    if (existing) {
      if (sub.outline_points?.length) {
        existing.outlinePoints = sub.outline_points
      }
      continue
    }
    if (existingTitles.has(key)) continue
    const prev = preserveMap.get(key)
    items.push({
      id: prev?.id ?? makeItemId('o', sub.title),
      title: sub.title,
      level: sub.level,
      wordTarget: prev?.wordTarget ?? defaultWordTarget(sub.level),
      requirements: prev?.requirements ?? '',
      existingContent: '',
      outlinePoints: sub.outline_points ?? [],
      enabled: prev?.enabled ?? true,
    })
    existingTitles.add(key)
  }

  if (!items.length && content.trim()) {
    items.push({
      id: 'section-body',
      title: '章节正文',
      level: 2,
      wordTarget: 600,
      requirements: '',
      existingContent: content.trim(),
      outlinePoints: [],
      enabled: true,
    })
  }

  return items
}

export function getExpandPreamble(content: string): string {
  return splitContentByHeadings(content).preamble
}
