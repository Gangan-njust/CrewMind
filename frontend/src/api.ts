const API_BASE = '/api'
const TOKEN_KEY = 'crewmind-token'

export interface UserInfo {
  id: string
  username: string
  created_at: string
}

export interface AuthResponse {
  token: string
  user: UserInfo
}

export interface Scenario {
  id: string
  label: string
  agents: { id: string; name: string; title: string; category?: string }[]
  tasks: {
    id: string
    name: string
    agent_id: string
    depends_on: string[]
    requires_human_review: boolean
  }[]
}

export interface Agent {
  id: string
  name: string
  title: string
  background: string
  goal: string
  tools: string[]
  use_reasoning?: boolean
  category?: string
  is_builtin?: boolean
}

export interface ToolOption {
  id: string
  label: string
}

export interface AgentFormData {
  id?: string
  name: string
  title: string
  background: string
  goal: string
  tools: string[]
  use_reasoning: boolean
}

export interface TaskResult {
  status: string
  output: string
  error: string
  human_feedback: string
  metadata?: Record<string, unknown>
}

export type CollaborationMode = 'sequential' | 'debate' | 'voting'

export interface CollaborationModeOption {
  id: CollaborationMode
  label: string
}

export interface WorkflowStatus {
  crew_id: string
  scenario: string
  collaboration_mode?: CollaborationMode
  status: string
  user_input: string
  results: Record<string, TaskResult>
  tasks?: Array<{
    id: string
    name: string
    agent_id: string
    depends_on: string[]
    requires_human_review?: boolean
  }>
}

export interface HistoryRecord {
  id: string
  topic_id?: string
  version_number?: number
  title: string
  scenario: string
  user_input: string
  created_at: string
  task_count: number
}

export interface TopicRecord {
  id: string
  title: string
  scenario: string
  user_input: string
  version_count: number
  best_record_id: string | null
  created_at: string
  updated_at: string
}

export interface VersionRecord {
  id: string
  topic_id: string
  version_number: number
  title: string
  scenario: string
  created_at: string
  task_count: number
  is_best: boolean
}

export interface CompareLineDiff {
  type: 'equal' | 'remove' | 'add' | 'change'
  lines_a: string[]
  lines_b: string[]
}

export interface CompareTaskDiff {
  task_id: string
  task_name: string
  status_a: string
  status_b: string
  output_a: string
  output_b: string
  output_length_a: number
  output_length_b: number
  similarity: number
  line_diff: CompareLineDiff[]
}

export interface CompareResult {
  record_a: {
    id: string
    title: string
    version_number: number
    created_at: string
    scenario: string
    pros: string[]
    cons: string[]
  }
  record_b: {
    id: string
    title: string
    version_number: number
    created_at: string
    scenario: string
    pros: string[]
    cons: string[]
  }
  advantages_a: string[]
  advantages_b: string[]
  task_diffs: CompareTaskDiff[]
}

export interface WorkflowTemplate {
  id: string
  name: string
  description: string
  scenario: string
  user_input: string
  selected_agents: string[]
  is_builtin: boolean
  variables: string[]
  created_at?: string
}

export interface TemplateListResponse {
  recommended: WorkflowTemplate[]
  mine: WorkflowTemplate[]
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
}

export function isAuthenticated(): boolean {
  return !!getToken()
}

async function authFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const token = getToken()
  const headers = new Headers(init.headers)
  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }
  const res = await fetch(input, { ...init, headers })
  if (res.status === 401 && token) {
    clearToken()
    window.dispatchEvent(new Event('auth:logout'))
  }
  return res
}

async function parseError(res: Response, fallback: string): Promise<string> {
  try {
    const data = await res.json()
    const detail = data.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      const messages = detail.map((item: { loc?: unknown[]; msg?: string }) => {
        if (typeof item === 'string') return item
        const field = item.loc?.filter((part) => part !== 'body').join('.') || ''
        return field ? `${field}: ${item.msg}` : (item.msg || '')
      }).filter(Boolean)
      return messages.length > 0 ? messages.join('；') : fallback
    }
    if (detail && typeof detail === 'object') {
      return (detail as { msg?: string }).msg || fallback
    }
    return fallback
  } catch {
    return fallback
  }
}

export async function register(username: string, password: string): Promise<AuthResponse> {
  const res = await fetch(`${API_BASE}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  if (!res.ok) throw new Error(await parseError(res, '注册失败'))
  const data: AuthResponse = await res.json()
  setToken(data.token)
  return data
}

export async function login(username: string, password: string): Promise<AuthResponse> {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  if (!res.ok) throw new Error(await parseError(res, '登录失败'))
  const data: AuthResponse = await res.json()
  setToken(data.token)
  return data
}

export function logout() {
  clearToken()
}

export async function fetchMe(): Promise<UserInfo> {
  const res = await authFetch(`${API_BASE}/auth/me`)
  if (!res.ok) throw new Error(await parseError(res, '获取用户信息失败'))
  return res.json()
}

export async function fetchScenarios(): Promise<Scenario[]> {
  const res = await authFetch(`${API_BASE}/scenarios`)
  if (!res.ok) throw new Error(await parseError(res, '加载场景失败'))
  return res.json()
}

export async function fetchAgents(): Promise<Agent[]> {
  const res = await authFetch(`${API_BASE}/agents`)
  if (!res.ok) throw new Error(await parseError(res, '加载角色失败'))
  return res.json()
}

export async function fetchAvailableTools(): Promise<ToolOption[]> {
  const res = await authFetch(`${API_BASE}/tools`)
  if (!res.ok) throw new Error(await parseError(res, '加载工具失败'))
  return res.json()
}

export async function createAgent(data: AgentFormData): Promise<Agent> {
  const res = await authFetch(`${API_BASE}/agents`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(await parseError(res, '创建失败'))
  return res.json()
}

export async function updateAgent(id: string, data: Omit<AgentFormData, 'id'>): Promise<Agent> {
  const res = await authFetch(`${API_BASE}/agents/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(await parseError(res, '更新失败'))
  return res.json()
}

export async function deleteAgent(id: string): Promise<void> {
  const res = await authFetch(`${API_BASE}/agents/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await parseError(res, '删除失败'))
}

export async function uploadReferenceFile(file: File) {
  const form = new FormData()
  form.append('file', file)
  const res = await authFetch(`${API_BASE}/uploads`, {
    method: 'POST',
    body: form,
  })
  if (!res.ok) throw new Error(await parseError(res, '文件上传失败'))
  return res.json() as Promise<{ id: string; filename: string; size: number }>
}

export async function fetchCollaborationModes(): Promise<CollaborationModeOption[]> {
  const res = await authFetch(`${API_BASE}/collaboration-modes`)
  if (!res.ok) throw new Error(await parseError(res, '加载协作模式失败'))
  return res.json()
}

export async function startWorkflow(
  scenario: string,
  userInput: string,
  referenceFileIds?: string[],
  selectedAgents?: string[],
  topicId?: string,
  collaborationMode: CollaborationMode = 'sequential',
) {
  const res = await authFetch(`${API_BASE}/workflow/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      scenario,
      user_input: userInput,
      reference_file_ids: referenceFileIds ?? [],
      selected_agents: selectedAgents ?? [],
      topic_id: topicId ?? null,
      collaboration_mode: collaborationMode,
    }),
  })
  if (!res.ok) throw new Error(await parseError(res, '启动失败'))
  return res.json()
}

export async function getWorkflowStatus(crewId: string): Promise<WorkflowStatus> {
  const res = await authFetch(`${API_BASE}/workflow/${crewId}`)
  if (!res.ok) throw new Error(await parseError(res, '获取工作流状态失败'))
  return res.json()
}

export async function submitFeedback(
  crewId: string,
  taskId: string,
  feedback: string,
  approved: boolean,
) {
  const res = await authFetch(`${API_BASE}/workflow/${crewId}/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task_id: taskId, feedback, approved }),
  })
  if (!res.ok) throw new Error(await parseError(res, '提交失败'))
  return res.json()
}

export async function fetchHistory(scenario?: string, search?: string): Promise<HistoryRecord[]> {
  const params = new URLSearchParams()
  if (scenario) params.set('scenario', scenario)
  if (search) params.set('search', search)
  const query = params.toString()
  const res = await authFetch(`${API_BASE}/results${query ? `?${query}` : ''}`)
  if (!res.ok) throw new Error(await parseError(res, '加载历史失败'))
  return res.json()
}

export async function fetchTopics(scenario?: string, search?: string): Promise<TopicRecord[]> {
  const params = new URLSearchParams()
  if (scenario) params.set('scenario', scenario)
  if (search) params.set('search', search)
  const query = params.toString()
  const res = await authFetch(`${API_BASE}/topics${query ? `?${query}` : ''}`)
  if (!res.ok) throw new Error(await parseError(res, '加载课题失败'))
  return res.json()
}

export async function fetchTopicVersions(topicId: string): Promise<VersionRecord[]> {
  const res = await authFetch(`${API_BASE}/topics/${topicId}/versions`)
  if (!res.ok) throw new Error(await parseError(res, '加载版本失败'))
  return res.json()
}

export async function setBestVersion(topicId: string, recordId: string): Promise<TopicRecord> {
  const res = await authFetch(`${API_BASE}/topics/${topicId}/best`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ record_id: recordId }),
  })
  if (!res.ok) throw new Error(await parseError(res, '设置失败'))
  return res.json()
}

export async function compareResults(recordIdA: string, recordIdB: string): Promise<CompareResult> {
  const res = await authFetch(`${API_BASE}/results/compare`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ record_id_a: recordIdA, record_id_b: recordIdB }),
  })
  if (!res.ok) throw new Error(await parseError(res, '对比失败'))
  return res.json()
}

export async function fetchResult(recordId: string) {
  const res = await authFetch(`${API_BASE}/results/${recordId}`)
  if (!res.ok) throw new Error(await parseError(res, '加载记录失败'))
  return res.json()
}

export async function downloadExport(options: {
  format: 'md' | 'docx' | 'tex'
  recordId?: string
  crewId?: string
  scope?: 'full' | 'proposal'
}) {
  const { format, recordId, crewId, scope = 'full' } = options
  if (!recordId && !crewId) {
    throw new Error('缺少导出目标')
  }

  const params = new URLSearchParams({ format, scope })
  const path = recordId
    ? `${API_BASE}/results/${recordId}/export?${params}`
    : `${API_BASE}/workflow/${crewId}/export?${params}`

  const res = await authFetch(path)
  if (!res.ok) throw new Error(await parseError(res, '导出失败'))

  const blob = await res.blob()
  const disposition = res.headers.get('Content-Disposition') || ''
  const utf8Match = disposition.match(/filename\*=UTF-8''([^;]+)/i)
  const asciiMatch = disposition.match(/filename="([^"]+)"/)
  const filename = utf8Match?.[1]
    ? decodeURIComponent(utf8Match[1])
    : (asciiMatch?.[1] || `export.${format}`)

  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

export async function suspendWorkflow(crewId: string) {
  const res = await authFetch(`${API_BASE}/workflow/${crewId}/suspend`, { method: 'POST' })
  if (!res.ok) throw new Error(await parseError(res, '中止失败'))
  return res.json()
}

export async function resumeWorkflow(crewId: string) {
  const res = await authFetch(`${API_BASE}/workflow/${crewId}/resume`, { method: 'POST' })
  if (!res.ok) throw new Error(await parseError(res, '继续失败'))
  return res.json()
}

export async function fetchTemplates(): Promise<TemplateListResponse> {
  const res = await authFetch(`${API_BASE}/templates`)
  if (!res.ok) throw new Error(await parseError(res, '加载模板失败'))
  return res.json()
}

export async function createTemplate(data: {
  name: string
  description?: string
  scenario: string
  user_input: string
  selected_agents: string[]
}): Promise<WorkflowTemplate> {
  const res = await authFetch(`${API_BASE}/templates`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(await parseError(res, '保存模板失败'))
  return res.json()
}

export async function deleteTemplate(templateId: string): Promise<void> {
  const res = await authFetch(`${API_BASE}/templates/${templateId}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await parseError(res, '删除模板失败'))
}

export function connectWebSocket(crewId: string, onMessage: (data: any) => void) {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = window.location.host
  const token = getToken() || ''
  const ws = new WebSocket(`${protocol}//${host}/ws/${crewId}?token=${encodeURIComponent(token)}`)

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data)
    onMessage(data)
  }

  ws.onopen = () => {
    const ping = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'ping' }))
      } else {
        clearInterval(ping)
      }
    }, 30000)
  }

  return ws
}

// ── 智能文献阅读助手 ──────────────────────────────────────────

export interface Workspace {
  id: string
  name: string
  description: string
  literature_count: number
  created_at: string
  updated_at: string
}

export interface LiteratureFormula {
  name: string
  latex: string
  variables?: string[]
  explanation: string
  context?: string
}

export interface LiteratureAnalysis {
  id?: string
  tags: string[]
  contribution_summary: string
  relevance_score: number | null
  recommendation_score: number | null
  key_findings: string[]
  limitations: string[]
  citation_templates: { zh?: string; en?: string }[]
  formulas?: LiteratureFormula[]
  research_background: string
  research_goal: string
  methods_summary: string
  conclusion: string
}

export interface Literature {
  id: string
  workspace_id: string
  title: string
  authors: string[]
  journal: string
  year: number | null
  doi: string
  abstract: string
  status: 'pending' | 'processing' | 'done' | 'failed'
  uploaded_at: string
  analysis?: LiteratureAnalysis
}

export interface AnalysisProgress {
  workspace_id: string
  total: number
  completed: number
  current_literature: string | null
  status: string
}

export type DataSourceMode = 'only_library' | 'library_first' | 'web_first'

export async function fetchWorkspaces(): Promise<Workspace[]> {
  const res = await authFetch(`${API_BASE}/workspaces`)
  if (!res.ok) throw new Error(await parseError(res, '加载工作空间失败'))
  return res.json()
}

export async function createWorkspace(name: string, description = ''): Promise<Workspace> {
  const res = await authFetch(`${API_BASE}/workspaces`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, description }),
  })
  if (!res.ok) throw new Error(await parseError(res, '创建工作空间失败'))
  return res.json()
}

export async function updateWorkspace(id: string, name: string, description: string): Promise<Workspace> {
  const res = await authFetch(`${API_BASE}/workspaces/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, description }),
  })
  if (!res.ok) throw new Error(await parseError(res, '更新工作空间失败'))
  return res.json()
}

export async function deleteWorkspace(id: string): Promise<void> {
  const res = await authFetch(`${API_BASE}/workspaces/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await parseError(res, '删除工作空间失败'))
}

export async function fetchLiteratures(workspaceId: string): Promise<Literature[]> {
  const res = await authFetch(`${API_BASE}/workspaces/${workspaceId}/literatures`)
  if (!res.ok) throw new Error(await parseError(res, '加载文献失败'))
  return res.json()
}

export async function uploadLiteratures(workspaceId: string, files: File[]): Promise<{ uploaded: Literature[] }> {
  const form = new FormData()
  files.forEach(f => form.append('files', f))
  const res = await authFetch(`${API_BASE}/workspaces/${workspaceId}/literatures`, {
    method: 'POST',
    body: form,
  })
  if (!res.ok) throw new Error(await parseError(res, '上传失败'))
  return res.json()
}

export async function deleteLiterature(workspaceId: string, literatureId: string): Promise<void> {
  const res = await authFetch(`${API_BASE}/workspaces/${workspaceId}/literatures/${literatureId}`, {
    method: 'DELETE',
  })
  if (!res.ok) throw new Error(await parseError(res, '删除失败'))
}

export async function analyzeLiteratures(
  workspaceId: string,
  literatureIds: string[] = [],
  userTopic?: string,
): Promise<{ status: string; total: number }> {
  const res = await authFetch(`${API_BASE}/workspaces/${workspaceId}/literatures/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ literature_ids: literatureIds, user_topic: userTopic }),
  })
  if (!res.ok) throw new Error(await parseError(res, '启动分析失败'))
  return res.json()
}

export async function fetchAnalysisProgress(workspaceId: string): Promise<AnalysisProgress> {
  const res = await authFetch(`${API_BASE}/workspaces/${workspaceId}/literatures/analysis/progress`)
  if (!res.ok) throw new Error(await parseError(res, '获取进度失败'))
  return res.json()
}

export async function filterLiteratures(
  workspaceId: string,
  params: Record<string, string | number | undefined>,
): Promise<Literature[]> {
  const qs = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== '') qs.set(k, String(v))
  })
  const res = await authFetch(`${API_BASE}/workspaces/${workspaceId}/literatures/filter?${qs}`)
  if (!res.ok) throw new Error(await parseError(res, '筛选失败'))
  return res.json()
}

export async function selectLiteratures(workspaceId: string, literatureIds: string[]): Promise<string[]> {
  const res = await authFetch(`${API_BASE}/workspaces/${workspaceId}/literatures/select`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ literature_ids: literatureIds }),
  })
  if (!res.ok) throw new Error(await parseError(res, '选定失败'))
  const data = await res.json()
  return data.selected_literature_ids
}

export async function fetchSelectedLiteratures(workspaceId: string) {
  const res = await authFetch(`${API_BASE}/workspaces/${workspaceId}/literatures/selected`)
  if (!res.ok) throw new Error(await parseError(res, '获取选定文献失败'))
  return res.json() as Promise<{ selected_literature_ids: string[]; literatures: Literature[] }>
}

export async function saveSelectionTemplate(
  workspaceId: string,
  selectionName: string,
  literatureIds: string[] = [],
) {
  const res = await authFetch(`${API_BASE}/workspaces/${workspaceId}/selections/save`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ selection_name: selectionName, literature_ids: literatureIds }),
  })
  if (!res.ok) throw new Error(await parseError(res, '保存模板失败'))
  return res.json()
}

export async function updateLiteratureAnalysis(
  workspaceId: string,
  literatureId: string,
  updates: Partial<LiteratureAnalysis>,
): Promise<Literature> {
  const res = await authFetch(
    `${API_BASE}/workspaces/${workspaceId}/literatures/${literatureId}/analysis`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates),
    },
  )
  if (!res.ok) throw new Error(await parseError(res, '更新分析结果失败'))
  return res.json()
}

export async function exportLiteratureCitations(
  workspaceId: string,
  format: 'bibtex' | 'endnote' | 'gbt7714' | 'apa',
  literatureIds?: string[],
): Promise<string> {
  const params = new URLSearchParams({ format })
  if (literatureIds?.length) params.set('literature_ids', literatureIds.join(','))
  const res = await authFetch(`${API_BASE}/workspaces/${workspaceId}/literatures/export?${params}`)
  if (!res.ok) throw new Error(await parseError(res, '导出失败'))
  const data = await res.json()
  return data.content
}

export async function startProposalFromLiterature(data: {
  workspace_id: string
  literature_ids: string[]
  mode: DataSourceMode
  topic: string
  additional_requirements?: string
  selected_agents: string[]
}) {
  const res = await authFetch(`${API_BASE}/reports/proposal/from-literature`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(await parseError(res, '启动开题报告生成失败'))
  return res.json() as Promise<{
    crew_id: string
    status: string
    scenario: string
    tasks: Array<{
      id: string
      name: string
      agent_id: string
      depends_on: string[]
      requires_human_review?: boolean
    }>
  }>
}

export function connectLiteratureWebSocket(
  workspaceId: string,
  onMessage: (data: AnalysisProgress & { type?: string }) => void,
) {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = window.location.host
  const token = getToken() || ''
  const ws = new WebSocket(
    `${protocol}//${host}/ws/literature/${workspaceId}?token=${encodeURIComponent(token)}`,
  )

  ws.onmessage = (event) => {
    onMessage(JSON.parse(event.data))
  }

  ws.onopen = () => {
    const ping = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'ping' }))
      } else {
        clearInterval(ping)
      }
    }, 30000)
  }

  return ws
}

// ── 学术写作辅助 ──────────────────────────────────────────────

export type PaperType = 'journal' | 'conference' | 'thesis'
export type CitationFormat = 'gb7714' | 'apa' | 'mla' | 'chicago'
export type SectionType = 'abstract' | 'abstract_en' | 'intro' | 'methods' | 'results' | 'discussion' | 'conclusion' | 'related_work' | 'acknowledgments' | 'custom'

export interface WritingSection {
  id: string
  project_id: string
  section_type: SectionType | string
  title: string
  sort_order: number
  is_custom: boolean
  display_title?: string
  content: string
  word_count: number
  version: number
  created_at: string
  updated_at: string
}

export interface WritingProject {
  id: string
  title: string
  topic: string
  paper_type: PaperType
  target_journal: string
  source_workflow_id: string | null
  workspace_id: string | null
  outline: OutlineSection[]
  citation_format: CitationFormat
  created_at: string
  updated_at: string
  sections: WritingSection[]
}

export interface WritingProjectSummary {
  id: string
  title: string
  topic: string
  paper_type: PaperType
  target_journal: string
  source_workflow_id: string | null
  workspace_id: string | null
  citation_format: CitationFormat
  created_at: string
  updated_at: string
}

export interface OutlineSubsection {
  level: 2 | 3 | 4
  title: string
  outline_points?: string[]
}

export interface OutlineSection {
  section_type: SectionType
  title: string
  outline_points: string[]
  subsections?: OutlineSubsection[]
  writing_hints: string
  word_target?: string
}

export interface SectionVersion {
  id: string
  section_id: string
  content: string
  word_count: number
  version: number
  note: string
  created_at: string
}

const SECTION_LABELS: Record<string, string> = {
  abstract: '摘要', abstract_en: 'Abstract', intro: '引言', methods: '方法', results: '结果',
  discussion: '讨论', conclusion: '结论', related_work: '相关工作', acknowledgments: '致谢',
}

export function isAbstractSection(type: string): boolean {
  return type === 'abstract' || type === 'abstract_en'
}

export function getSectionLabel(type: string): string {
  return SECTION_LABELS[type] || type
}

export function getSectionDisplayName(section: Pick<WritingSection, 'section_type' | 'title' | 'display_title'>): string {
  if (section.display_title) return section.display_title
  if (section.title) return section.title
  return getSectionLabel(section.section_type)
}

export async function fetchWritingProjects(): Promise<WritingProjectSummary[]> {
  const res = await authFetch(`${API_BASE}/writing/projects`)
  if (!res.ok) throw new Error(await parseError(res, '获取写作项目失败'))
  return res.json()
}

export async function fetchWritingProject(id: string): Promise<WritingProject> {
  const res = await authFetch(`${API_BASE}/writing/projects/${id}`)
  if (!res.ok) throw new Error(await parseError(res, '获取写作项目失败'))
  return res.json()
}

export async function createWritingProject(data: {
  title: string
  topic?: string
  paper_type?: PaperType
  target_journal?: string
  workspace_id?: string
}): Promise<WritingProject> {
  const res = await authFetch(`${API_BASE}/writing/projects`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(await parseError(res, '创建写作项目失败'))
  return res.json()
}

export async function updateWritingProject(id: string, data: Partial<{
  title: string; topic: string; paper_type: PaperType
  target_journal: string; workspace_id: string; outline: OutlineSection[]
  citation_format: CitationFormat
}>): Promise<WritingProject> {
  const res = await authFetch(`${API_BASE}/writing/projects/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(await parseError(res, '更新写作项目失败'))
  return res.json()
}

export async function deleteWritingProject(id: string): Promise<void> {
  const res = await authFetch(`${API_BASE}/writing/projects/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await parseError(res, '删除写作项目失败'))
}

export async function updateWritingSection(sectionId: string, data: {
  content: string; save_version?: boolean; version_note?: string
}): Promise<WritingSection> {
  const res = await authFetch(`${API_BASE}/writing/sections/${sectionId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(await parseError(res, '保存章节失败'))
  return res.json()
}

export async function createWritingSection(projectId: string, data: {
  title: string; after_section_id?: string
}): Promise<WritingSection> {
  const res = await authFetch(`${API_BASE}/writing/projects/${projectId}/sections`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(await parseError(res, '创建章节失败'))
  return res.json()
}

export async function updateWritingSectionMeta(sectionId: string, title: string): Promise<WritingSection> {
  const res = await authFetch(`${API_BASE}/writing/sections/${sectionId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  })
  if (!res.ok) throw new Error(await parseError(res, '更新章节失败'))
  return res.json()
}

export async function deleteWritingSection(sectionId: string): Promise<void> {
  const res = await authFetch(`${API_BASE}/writing/sections/${sectionId}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await parseError(res, '删除章节失败'))
}

export async function reorderWritingSections(projectId: string, sectionIds: string[]): Promise<WritingProject> {
  const res = await authFetch(`${API_BASE}/writing/projects/${projectId}/sections/reorder`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ section_ids: sectionIds }),
  })
  if (!res.ok) throw new Error(await parseError(res, '章节排序失败'))
  return res.json()
}

export async function generateWritingOutline(data: {
  topic: string; paper_type?: PaperType; target_journal?: string
  source_workflow_id?: string
}): Promise<{ title_suggestion: string; sections: OutlineSection[] }> {
  const res = await authFetch(`${API_BASE}/writing/outline/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(await parseError(res, '大纲生成失败'))
  return res.json()
}

export interface ExpandSubsectionItem {
  title: string
  level: 2 | 3 | 4
  word_target: number
  requirements?: string
  existing_content?: string
  outline_points?: string[]
  enabled?: boolean
}

export async function expandWriting(data: {
  text: string
  section_type?: string
  topic?: string
  length?: 'short' | 'medium' | 'long'
  mode?: 'free' | 'structured'
  global_requirements?: string
  items?: ExpandSubsectionItem[]
}): Promise<{ expanded_text: string; original_text: string; mode?: string }> {
  const res = await authFetch(`${API_BASE}/writing/expand`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(await parseError(res, '扩写失败'))
  return res.json()
}

export interface CompleteOutlineResult {
  summary: string
  completed_count: number
  skipped_count: number
  results: Array<{
    section_id: string
    section_type: string
    display_title: string
    status: 'completed' | 'skipped'
    word_count: number
  }>
  project: WritingProject
}

export async function completeWritingFromOutline(
  projectId: string,
  data?: {
    global_requirements?: string
    skip_filled?: boolean
    min_existing_words?: number
  },
): Promise<CompleteOutlineResult> {
  const res = await authFetch(`${API_BASE}/writing/projects/${projectId}/complete-outline`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data || {}),
  })
  if (!res.ok) throw new Error(await parseError(res, '全文补全失败'))
  return res.json()
}

/** @deprecated 使用 expandWriting */
export async function continueWriting(data: {
  prefix: string; section_type?: string; context?: string; length?: 'short' | 'medium' | 'long'
}): Promise<{ continued_text: string }> {
  const res = await authFetch(`${API_BASE}/writing/continue`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(await parseError(res, '扩写失败'))
  return res.json()
}

export async function polishWriting(data: {
  text: string
  section_type?: string
  topic?: string
  style?: 'conservative' | 'moderate' | 'deep'
  mode?: 'free' | 'structured'
  global_requirements?: string
  items?: ExpandSubsectionItem[]
}): Promise<{ polished_text: string; changes_summary: string[]; mode?: string }> {
  const res = await authFetch(`${API_BASE}/writing/polish`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(await parseError(res, '润色失败'))
  return res.json()
}

export async function checkTerminology(projectId: string) {
  const res = await authFetch(`${API_BASE}/writing/check/terminology`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_id: projectId }),
  })
  if (!res.ok) throw new Error(await parseError(res, '术语检查失败'))
  return res.json()
}

export async function checkCoherence(projectId: string) {
  const res = await authFetch(`${API_BASE}/writing/check/coherence`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_id: projectId }),
  })
  if (!res.ok) throw new Error(await parseError(res, '连贯性检查失败'))
  return res.json()
}

export async function checkStyle(text: string, sectionType?: string) {
  const res = await authFetch(`${API_BASE}/writing/check/style`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, section_type: sectionType }),
  })
  if (!res.ok) throw new Error(await parseError(res, '规范性检查失败'))
  return res.json()
}

export async function checkBlankLines(text: string): Promise<{
  cleaned_text: string
  removed_count: number
  summary: string
  changed: boolean
}> {
  const res = await authFetch(`${API_BASE}/writing/check/blank-lines`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })
  if (!res.ok) throw new Error(await parseError(res, '空行检查失败'))
  return res.json()
}

export async function recommendCitations(data: {
  selected_text: string; context?: string; project_id: string
}) {
  const res = await authFetch(`${API_BASE}/writing/citations/recommend`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(await parseError(res, '引用推荐失败'))
  return res.json()
}

export async function generateCitationSentences(literatureId: string, purpose?: string) {
  const res = await authFetch(`${API_BASE}/writing/citations/sentences`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ literature_id: literatureId, purpose }),
  })
  if (!res.ok) throw new Error(await parseError(res, '引用句式生成失败'))
  return res.json()
}

export async function checkCitationCompleteness(projectId: string) {
  const res = await authFetch(`${API_BASE}/writing/citations/completeness`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_id: projectId }),
  })
  if (!res.ok) throw new Error(await parseError(res, '引用完整性检查失败'))
  return res.json()
}

export async function fetchSectionVersions(sectionId: string): Promise<SectionVersion[]> {
  const res = await authFetch(`${API_BASE}/writing/sections/${sectionId}/versions`)
  if (!res.ok) throw new Error(await parseError(res, '获取版本历史失败'))
  return res.json()
}

export async function compareSectionVersions(sectionId: string, versionA: number, versionB: number) {
  const res = await authFetch(`${API_BASE}/writing/sections/${sectionId}/compare`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ version_a: versionA, version_b: versionB }),
  })
  if (!res.ok) throw new Error(await parseError(res, '版本对比失败'))
  return res.json()
}

export async function rollbackSection(sectionId: string, targetVersion: number): Promise<WritingSection> {
  const res = await authFetch(`${API_BASE}/writing/sections/${sectionId}/rollback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ target_version: targetVersion }),
  })
  if (!res.ok) throw new Error(await parseError(res, '版本回滚失败'))
  return res.json()
}

export async function createWritingFromWorkflow(data: {
  workflow_record_id: string; title?: string; paper_type?: PaperType
  target_journal?: string; workspace_id?: string
}): Promise<WritingProject> {
  const res = await authFetch(`${API_BASE}/writing/projects/from-workflow`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(await parseError(res, '从工作方案创建失败'))
  return res.json()
}

export async function fillMethodsFromWorkflow(projectId: string, workflowRecordId: string): Promise<WritingSection> {
  const res = await authFetch(`${API_BASE}/writing/projects/${projectId}/fill-methods`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workflow_record_id: workflowRecordId }),
  })
  if (!res.ok) throw new Error(await parseError(res, '填充 Methods 失败'))
  return res.json()
}

export async function fetchWritingBibliography(projectId: string) {
  const res = await authFetch(`${API_BASE}/writing/projects/${projectId}/bibliography`)
  if (!res.ok) throw new Error(await parseError(res, '获取参考文献失败'))
  return res.json()
}

export async function downloadWritingExport(
  projectId: string,
  format: 'md' | 'docx' = 'md',
  includeBibliography = true,
) {
  const params = new URLSearchParams({ format, include_bibliography: String(includeBibliography) })
  const res = await authFetch(`${API_BASE}/writing/projects/${projectId}/export?${params}`)
  if (!res.ok) throw new Error(await parseError(res, '导出失败'))

  const blob = await res.blob()
  const disposition = res.headers.get('Content-Disposition') || ''
  const utf8Match = disposition.match(/filename\*=UTF-8''([^;]+)/i)
  const asciiMatch = disposition.match(/filename="([^"]+)"/)
  const filename = utf8Match?.[1]
    ? decodeURIComponent(utf8Match[1])
    : (asciiMatch?.[1] || `paper.${format}`)

  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

// ── 实验数据管理 ──────────────────────────────────────────────

export interface ExpectedMetric {
  type: string
  label: string
  expected_value?: number
  tolerance?: number
  unit?: string
  name?: string
  source_text?: string
}

export interface ExperimentAttachment {
  id: string
  entry_id: string
  filename: string
  mime_type: string
  file_size: number
  attachment_type: string
  uploaded_at: string
  url: string
}

export interface ExperimentEntry {
  id: string
  experiment_id: string
  title: string
  step_name: string
  notes: string
  instrument_params: Record<string, unknown>
  raw_data: Record<string, unknown>
  entry_type: 'observation' | 'measurement' | 'note'
  created_at: string
  updated_at: string
  attachments: ExperimentAttachment[]
}

export interface ExperimentDataset {
  id: string
  experiment_id: string
  entry_id: string | null
  filename: string
  file_type: string
  columns: { name: string; dtype: string; is_numeric: boolean; unique_count: number }[]
  row_count: number
  preview: Record<string, unknown>[]
  uploaded_at: string
}

export interface ExperimentAnalysis {
  id: string
  dataset_id: string
  config: Record<string, unknown>
  summary: Record<string, unknown>
  charts: { type: string; title: string; image_base64: string }[]
  stats: Record<string, unknown>[]
  created_at: string
}

export interface ExperimentSummary {
  id: string
  title: string
  description: string
  source_workflow_id: string | null
  expected_metrics: ExpectedMetric[]
  status: string
  entry_count: number
  dataset_count: number
  created_at: string
  updated_at: string
}

export interface Experiment extends ExperimentSummary {
  entries: ExperimentEntry[]
  datasets: ExperimentDataset[]
}

export interface ComparisonItem {
  metric: ExpectedMetric
  status: string
  actual_value?: number
  expected_value?: number
  deviation?: number
  deviation_percent?: number
  column?: string
  interpretation?: string
}

export interface ComparisonResult {
  experiment_id: string
  dataset_id?: string
  has_expected: boolean
  has_actual: boolean
  expected_metrics?: ExpectedMetric[]
  comparisons: ComparisonItem[]
  summary: string
}

export async function fetchExperiments(): Promise<ExperimentSummary[]> {
  const res = await authFetch(`${API_BASE}/experiment/experiments`)
  if (!res.ok) throw new Error(await parseError(res, '获取实验列表失败'))
  return res.json()
}

export async function fetchExperiment(id: string): Promise<Experiment> {
  const res = await authFetch(`${API_BASE}/experiment/experiments/${id}`)
  if (!res.ok) throw new Error(await parseError(res, '获取实验详情失败'))
  return res.json()
}

export async function createExperiment(data: {
  title: string
  description?: string
  source_workflow_id?: string
  expected_metrics?: ExpectedMetric[]
}): Promise<Experiment> {
  const res = await authFetch(`${API_BASE}/experiment/experiments`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(await parseError(res, '创建实验失败'))
  return res.json()
}

export async function updateExperiment(
  id: string,
  data: Partial<{ title: string; description: string; status: string; expected_metrics: ExpectedMetric[] }>,
): Promise<Experiment> {
  const res = await authFetch(`${API_BASE}/experiment/experiments/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(await parseError(res, '更新实验失败'))
  return res.json()
}

export async function deleteExperiment(id: string): Promise<void> {
  const res = await authFetch(`${API_BASE}/experiment/experiments/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await parseError(res, '删除实验失败'))
}

export async function createExperimentEntry(
  experimentId: string,
  data: {
    title?: string
    step_name?: string
    notes?: string
    instrument_params?: Record<string, unknown>
    raw_data?: Record<string, unknown>
    entry_type?: string
  },
): Promise<ExperimentEntry> {
  const res = await authFetch(`${API_BASE}/experiment/experiments/${experimentId}/entries`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(await parseError(res, '创建实验记录失败'))
  return res.json()
}

export async function updateExperimentEntry(
  entryId: string,
  data: Partial<{
    title: string
    step_name: string
    notes: string
    instrument_params: Record<string, unknown>
    raw_data: Record<string, unknown>
    entry_type: string
  }>,
): Promise<ExperimentEntry> {
  const res = await authFetch(`${API_BASE}/experiment/entries/${entryId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(await parseError(res, '更新实验记录失败'))
  return res.json()
}

export async function deleteExperimentEntry(entryId: string): Promise<void> {
  const res = await authFetch(`${API_BASE}/experiment/entries/${entryId}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await parseError(res, '删除实验记录失败'))
}

export async function uploadExperimentAttachment(
  entryId: string,
  file: File,
  attachmentType: 'photo' | 'document' = 'photo',
): Promise<ExperimentAttachment> {
  const form = new FormData()
  form.append('file', file)
  const res = await authFetch(
    `${API_BASE}/experiment/entries/${entryId}/attachments?attachment_type=${attachmentType}`,
    { method: 'POST', body: form },
  )
  if (!res.ok) throw new Error(await parseError(res, '上传附件失败'))
  return res.json()
}

export async function uploadExperimentDataset(
  experimentId: string,
  file: File,
  entryId?: string,
): Promise<ExperimentDataset> {
  const form = new FormData()
  form.append('file', file)
  const params = entryId ? `?entry_id=${entryId}` : ''
  const res = await authFetch(
    `${API_BASE}/experiment/experiments/${experimentId}/datasets${params}`,
    { method: 'POST', body: form },
  )
  if (!res.ok) throw new Error(await parseError(res, '上传数据集失败'))
  return res.json()
}

export async function analyzeExperimentDataset(
  datasetId: string,
  options?: { value_column?: string; group_column?: string },
): Promise<ExperimentAnalysis> {
  const res = await authFetch(`${API_BASE}/experiment/datasets/${datasetId}/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(options || {}),
  })
  if (!res.ok) throw new Error(await parseError(res, '数据分析失败'))
  return res.json()
}

export async function compareExperimentData(
  experimentId: string,
  options?: { dataset_id?: string; value_column?: string },
): Promise<ComparisonResult> {
  const res = await authFetch(`${API_BASE}/experiment/experiments/${experimentId}/compare`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(options || {}),
  })
  if (!res.ok) throw new Error(await parseError(res, '数据对比失败'))
  return res.json()
}

export async function createExperimentFromWorkflow(data: {
  workflow_record_id: string
  title?: string
  description?: string
}): Promise<Experiment> {
  const res = await authFetch(`${API_BASE}/experiment/from-workflow`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(await parseError(res, '从方案创建实验失败'))
  return res.json()
}

export async function fetchWorkflowExpectedMetrics(workflowId: string) {
  const res = await authFetch(`${API_BASE}/experiment/workflow/${workflowId}/expected`)
  if (!res.ok) throw new Error(await parseError(res, '获取方案预期指标失败'))
  return res.json()
}
