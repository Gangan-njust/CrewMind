const API_BASE = '/api'
const TOKEN_KEY = 'agentcrew-token'

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
  agents: { id: string; name: string; title: string }[]
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
}

export interface WorkflowStatus {
  crew_id: string
  scenario: string
  status: string
  user_input: string
  results: Record<string, TaskResult>
}

export interface HistoryRecord {
  id: string
  title: string
  scenario: string
  user_input: string
  created_at: string
  task_count: number
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
    return data.detail || fallback
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

export async function startWorkflow(
  scenario: string,
  userInput: string,
  referenceFileIds?: string[],
  selectedAgents?: string[],
) {
  const res = await authFetch(`${API_BASE}/workflow/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      scenario,
      user_input: userInput,
      reference_file_ids: referenceFileIds ?? [],
      selected_agents: selectedAgents ?? [],
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

export async function fetchResult(recordId: string) {
  const res = await authFetch(`${API_BASE}/results/${recordId}`)
  if (!res.ok) throw new Error(await parseError(res, '加载记录失败'))
  return res.json()
}

export async function downloadExport(options: {
  format: 'md' | 'docx'
  recordId?: string
  crewId?: string
}) {
  const { format, recordId, crewId } = options
  if (!recordId && !crewId) {
    throw new Error('缺少导出目标')
  }

  const path = recordId
    ? `${API_BASE}/results/${recordId}/export?format=${format}`
    : `${API_BASE}/workflow/${crewId}/export?format=${format}`

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
