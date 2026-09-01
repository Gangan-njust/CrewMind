export const BIBLIOGRAPHY_SECTION_TITLE = '参考文献'

export function formatCitationMarker(index: number): string {
  return `[${index}]`
}

export function insertCitationAtPosition(
  content: string,
  start: number,
  end: number,
  insertText: string,
): string {
  const safeStart = Math.max(0, Math.min(start, content.length))
  const safeEnd = Math.max(safeStart, Math.min(end, content.length))
  return content.slice(0, safeStart) + insertText + content.slice(safeEnd)
}

export function isBibliographySection(section: { title?: string; section_type?: string }): boolean {
  return (section.title || '').trim() === BIBLIOGRAPHY_SECTION_TITLE
}

export function renderTextWithCitationSuperscript(text: string): (string | { sup: string })[] {
  const parts = text.split(/(\[\d+\])/g)
  return parts.filter(Boolean).map(part =>
    /^\[\d+\]$/.test(part) ? { sup: part } : part,
  )
}
