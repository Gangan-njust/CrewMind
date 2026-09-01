import { getSectionDisplayName, isAbstractSection, type WritingSection } from './api'
import { BIBLIOGRAPHY_SECTION_TITLE } from './writingCitations'

export function isNumberedSection(section: Pick<WritingSection, 'section_type' | 'title'>): boolean {
  if (isAbstractSection(section.section_type)) return false
  if ((section.title || '').trim() === BIBLIOGRAPHY_SECTION_TITLE) return false
  return true
}

export function computeSectionNumbers(sections: WritingSection[]): Map<string, number> {
  const sorted = [...sections].sort((a, b) => a.sort_order - b.sort_order)
  const numbers = new Map<string, number>()
  let num = 0
  for (const sec of sorted) {
    if (!isNumberedSection(sec)) continue
    num += 1
    numbers.set(sec.id, num)
  }
  return numbers
}

export function getNumberedSectionDisplayName(
  section: Pick<WritingSection, 'id' | 'section_type' | 'title' | 'display_title'>,
  sectionNumbers: Map<string, number>,
): string {
  const base = getSectionDisplayName(section)
  const num = sectionNumbers.get(section.id)
  if (num == null) return base
  return `${num}.${base}`
}
