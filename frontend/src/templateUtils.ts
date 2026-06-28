import type { WorkflowTemplate } from './api'

const VARIABLE_PATTERN = /\{\{([^}]+)\}\}/g

export function extractVariables(text: string): string[] {
  const seen = new Set<string>()
  const result: string[] = []
  for (const match of text.matchAll(VARIABLE_PATTERN)) {
    const name = match[1].trim()
    if (name && !seen.has(name)) {
      seen.add(name)
      result.push(name)
    }
  }
  return result
}

export function applyTemplateVariables(
  templateText: string,
  values: Record<string, string>,
): string {
  return templateText.replace(VARIABLE_PATTERN, (_, rawName: string) => {
    const name = rawName.trim()
    return values[name]?.trim() ?? `{{${name}}}`
  })
}

export function getTemplateVariables(template: WorkflowTemplate): string[] {
  return template.variables?.length
    ? template.variables
    : extractVariables(template.user_input)
}

export function buildEmptyVariableValues(variables: string[]): Record<string, string> {
  return Object.fromEntries(variables.map(v => [v, '']))
}

export function areTemplateVariablesFilled(
  variables: string[],
  values: Record<string, string>,
): boolean {
  return variables.every(v => (values[v] || '').trim().length > 0)
}

export function getVariablePlaceholder(name: string): string {
  const hintMatch = name.match(/如[：:]?\s*(.+)/)
  if (hintMatch) return `例如：${hintMatch[1]}`
  return `请输入${name}`
}
