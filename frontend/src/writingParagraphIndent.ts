/** 是否应对段落应用首行缩进（排除标题、关键词、参考文献条目等） */
export function shouldIndentParagraph(text: string): boolean {
  const stripped = text.trim()
  if (!stripped) return false
  if (/^[\t　]/.test(stripped)) return false
  if (/^#{1,6}\s/.test(stripped)) return false
  if (/^关键词[：:]/.test(stripped)) return false
  if (/^Keywords[：:]/i.test(stripped)) return false
  if (/^\[\d+\]/.test(stripped)) return false
  if (/^[-*•·]\s/.test(stripped)) return false
  return true
}
