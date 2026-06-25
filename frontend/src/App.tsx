import { useState, useEffect, useRef } from 'react'
import {
  Play, Users, History, Bot, LayoutDashboard,
  CheckCircle, Clock, AlertTriangle, XCircle, Loader,
  Sun, Moon, Pause, FileText, FileDown, Upload, X,
  Plus, Pencil, Trash2, Settings, LogOut, User, Search,
} from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import {
  fetchScenarios, fetchAgents, startWorkflow, getWorkflowStatus,
  submitFeedback, suspendWorkflow, resumeWorkflow,
  fetchHistory, fetchResult, connectWebSocket, downloadExport,
  uploadReferenceFile, createAgent, updateAgent, deleteAgent, fetchAvailableTools,
  login, register, logout, fetchMe, isAuthenticated,
  type Scenario, type Agent, type WorkflowStatus, type HistoryRecord,
  type AgentFormData, type ToolOption, type UserInfo,
} from './api'

type Page = 'dashboard' | 'workflow' | 'agents' | 'history'
type Theme = 'dark' | 'light'

const THEME_KEY = 'agentcrew-theme'

function getInitialTheme(): Theme {
  const saved = localStorage.getItem(THEME_KEY)
  if (saved === 'light' || saved === 'dark') return saved
  return 'dark'
}

export default function App() {
  const [authUser, setAuthUser] = useState<UserInfo | null>(null)
  const [authLoading, setAuthLoading] = useState(true)
  const [page, setPage] = useState<Page>('dashboard')
  const [theme, setTheme] = useState<Theme>(getInitialTheme)
  const [showSettings, setShowSettings] = useState(false)
  const settingsRef = useRef<HTMLDivElement>(null)
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [agents, setAgents] = useState<Agent[]>([])
  const [history, setHistory] = useState<HistoryRecord[]>([])
  const [selectedScenario, setSelectedScenario] = useState('')
  const [selectedAgents, setSelectedAgents] = useState<string[]>([])
  const [activeWorkflowScenario, setActiveWorkflowScenario] = useState<Scenario | null>(null)
  const [userInput, setUserInput] = useState('')
  const [referenceFiles, setReferenceFiles] = useState<{ id: string; filename: string }[]>([])
  const [uploadingFile, setUploadingFile] = useState(false)
  const [toolEvents, setToolEvents] = useState<{ tool: string; status: string; detail: string }[]>([])
  const [crewId, setCrewId] = useState('')
  const [workflowStatus, setWorkflowStatus] = useState<WorkflowStatus | null>(null)
  const [isRunning, setIsRunning] = useState(false)
  const [reviewTaskId, setReviewTaskId] = useState('')
  const [reviewFeedback, setReviewFeedback] = useState('')
  const [selectedRecord, setSelectedRecord] = useState<any>(null)

  const loadAppData = () => {
    fetchScenarios().then(setScenarios).catch(() => {})
    fetchAgents().then(setAgents).catch(() => {})
    fetchHistory().then(setHistory).catch(() => {})
  }

  useEffect(() => {
    const initAuth = async () => {
      if (!isAuthenticated()) {
        setAuthLoading(false)
        return
      }
      try {
        const user = await fetchMe()
        setAuthUser(user)
        loadAppData()
      } catch {
        logout()
      } finally {
        setAuthLoading(false)
      }
    }
    initAuth()

    const onLogout = () => {
      setAuthUser(null)
      setScenarios([])
      setAgents([])
      setHistory([])
    }
    window.addEventListener('auth:logout', onLogout)
    return () => window.removeEventListener('auth:logout', onLogout)
  }, [])

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem(THEME_KEY, theme)
  }, [theme])

  useEffect(() => {
    if (!showSettings) return
    const handleClickOutside = (e: MouseEvent) => {
      if (settingsRef.current && !settingsRef.current.contains(e.target as Node)) {
        setShowSettings(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [showSettings])

  const handleLogin = async (username: string, password: string) => {
    const data = await login(username, password)
    setAuthUser(data.user)
    loadAppData()
  }

  const handleRegister = async (username: string, password: string) => {
    const data = await register(username, password)
    setAuthUser(data.user)
    loadAppData()
  }

  const handleLogout = () => {
    logout()
    setAuthUser(null)
    setShowSettings(false)
    setPage('dashboard')
    setCrewId('')
    setWorkflowStatus(null)
    setSelectedRecord(null)
  }

  if (authLoading) {
    return (
      <div className="auth-page">
        <Loader size={32} className="spinner" />
      </div>
    )
  }

  if (!authUser) {
    return <LoginPage onLogin={handleLogin} onRegister={handleRegister} theme={theme} />
  }

  const handleScenarioSelect = (scenarioId: string) => {
    setSelectedScenario(scenarioId)
    const scenario = scenarios.find(s => s.id === scenarioId)
    if (scenario) {
      setSelectedAgents(scenario.agents.map(a => a.id))
    }
  }

  const reloadAgents = () => fetchAgents().then(setAgents)

  const toggleTheme = () => setTheme(t => t === 'dark' ? 'light' : 'dark')

  const handleStart = async () => {
    if (!selectedScenario || userInput.length < 10) return
    setIsRunning(true)
    setToolEvents([])
    try {
      const data = await startWorkflow(
        selectedScenario,
        userInput,
        referenceFiles.map(f => f.id),
        selectedAgents,
      )
      setCrewId(data.crew_id)
      setActiveWorkflowScenario({
        id: data.scenario,
        label: scenarios.find(s => s.id === data.scenario)?.label || data.scenario,
        agents: agents.filter(a => data.tasks.some((t: { agent_id: string }) => t.agent_id === a.id)),
        tasks: data.tasks,
      })
      setWorkflowStatus({
        crew_id: data.crew_id,
        scenario: data.scenario,
        status: 'running',
        user_input: userInput,
        results: {},
      })
      setPage('workflow')

      connectWebSocket(data.crew_id, (msg) => {
        if (msg.type === 'task_output_chunk') {
          setWorkflowStatus(prev => {
            if (!prev) return prev
            const taskId = msg.task_id as string
            const prevResult = prev.results[taskId] || { status: 'running', output: '', error: '', human_feedback: '' }
            return {
              ...prev,
              results: {
                ...prev.results,
                [taskId]: {
                  ...prevResult,
                  status: 'running',
                  output: (prevResult.output || '') + (msg.chunk || ''),
                },
              },
            }
          })
        }
        if (msg.type === 'tool_invoked') {
          setToolEvents(prev => [
            ...prev,
            {
              tool: msg.tool as string,
              status: msg.status as string,
              detail: msg.detail as string,
            },
          ])
        }
        if (msg.type === 'task_started') {
          setWorkflowStatus(prev => {
            if (!prev) return prev
            const taskId = msg.task_id as string
            return {
              ...prev,
              results: {
                ...prev.results,
                [taskId]: {
                  status: 'running',
                  output: '',
                  error: '',
                  human_feedback: '',
                },
              },
            }
          })
        }
        if (msg.type === 'task_resumed') {
          setWorkflowStatus(prev => {
            if (!prev) return prev
            const taskId = msg.task_id as string
            const prevResult = prev.results[taskId] || { status: 'running', output: '', error: '', human_feedback: '' }
            return {
              ...prev,
              status: 'running',
              results: {
                ...prev.results,
                [taskId]: {
                  ...prevResult,
                  status: 'running',
                  output: msg.output ?? prevResult.output,
                },
              },
            }
          })
        }
        if (msg.type === 'task_completed' || msg.type === 'human_review_required' ||
            msg.type === 'crew_completed' || msg.type === 'status') {
          getWorkflowStatus(data.crew_id).then(setWorkflowStatus)
        }
        if (msg.type === 'human_review_required') {
          setReviewTaskId(msg.task_id)
        }
        if (msg.type === 'crew_completed' || msg.type === 'crew_failed') {
          setIsRunning(false)
          fetchHistory().then(setHistory)
        }
        if (msg.type === 'crew_suspended') {
          setIsRunning(false)
          getWorkflowStatus(data.crew_id).then(setWorkflowStatus)
        }
        if (msg.type === 'crew_resumed') {
          setIsRunning(true)
          setWorkflowStatus(prev => prev ? { ...prev, status: 'running' } : prev)
        }
      })

      // Poll status as fallback
      const poll = setInterval(async () => {
        const status = await getWorkflowStatus(data.crew_id)
        setWorkflowStatus(status)
        if (status.status === 'completed' || status.status === 'failed' || status.status === 'suspended') {
          clearInterval(poll)
          setIsRunning(false)
        }
        if (status.status === 'paused') {
          const waiting = Object.entries(status.results).find(
            ([, r]) => r.status === 'waiting_human'
          )
          if (waiting) setReviewTaskId(waiting[0])
        }
      }, 2000)
    } catch (e: any) {
      alert(e.message)
      setIsRunning(false)
    }
  }

  const handleReview = async (approved: boolean) => {
    if (!crewId || !reviewTaskId) return
    setIsRunning(true)
    try {
      await submitFeedback(crewId, reviewTaskId, reviewFeedback, approved)
      setReviewTaskId('')
      setReviewFeedback('')
      setWorkflowStatus(prev => prev ? { ...prev, status: 'running' } : prev)
    } catch (e: any) {
      alert(e.message)
      setIsRunning(false)
    }
  }

  const handleSuspend = async () => {
    if (!crewId) return
    try {
      await suspendWorkflow(crewId)
    } catch (e: any) {
      alert(e.message)
    }
  }

  const handleResume = async () => {
    if (!crewId) return
    setIsRunning(true)
    try {
      await resumeWorkflow(crewId)
      setWorkflowStatus(prev => prev ? { ...prev, status: 'running' } : prev)
    } catch (e: any) {
      alert(e.message)
      setIsRunning(false)
    }
  }

  const currentScenario = activeWorkflowScenario || scenarios.find(s => s.id === selectedScenario)

  const toggleAgent = (agentId: string) => {
    setSelectedAgents(prev =>
      prev.includes(agentId)
        ? prev.filter(id => id !== agentId)
        : [...prev, agentId]
    )
  }

  return (
    <div className="app-layout">
      <aside className="sidebar">
        <div className="app-header">
          <Bot size={28} color="#a29bfe" />
          <div>
            <h1>AgentCrew</h1>
            <div className="subtitle">多智能体工作方案系统</div>
          </div>
        </div>

        <button className={`nav-item ${page === 'dashboard' ? 'active' : ''}`}
          onClick={() => setPage('dashboard')}>
          <LayoutDashboard size={18} /> 工作台
        </button>
        <button className={`nav-item ${page === 'workflow' ? 'active' : ''}`}
          onClick={() => setPage('workflow')}>
          <Play size={18} /> 工作流
        </button>
        <button className={`nav-item ${page === 'agents' ? 'active' : ''}`}
          onClick={() => setPage('agents')}>
          <Users size={18} /> Agent 角色
        </button>
        <button className={`nav-item ${page === 'history' ? 'active' : ''}`}
          onClick={() => { setPage('history'); fetchHistory().then(setHistory) }}>
          <History size={18} /> 历史方案
        </button>

        <div className="sidebar-spacer" />

        <div className="settings-anchor" ref={settingsRef}>
          {showSettings && (
            <SettingsPopover
              theme={theme}
              onToggleTheme={toggleTheme}
              user={authUser}
              onLogout={handleLogout}
              onClose={() => setShowSettings(false)}
            />
          )}
          <button
            className={`theme-toggle ${showSettings ? 'active' : ''}`}
            onClick={() => setShowSettings(s => !s)}
            title="设置"
          >
            <Settings size={18} />
            设置
          </button>
        </div>
      </aside>

      <main className="main-content">
        {page === 'dashboard' && (
          <DashboardPage
            scenarios={scenarios}
            agents={agents}
            selectedScenario={selectedScenario}
            onSelectScenario={handleScenarioSelect}
            selectedAgents={selectedAgents}
            onToggleAgent={toggleAgent}
            userInput={userInput}
            onInputChange={setUserInput}
            referenceFiles={referenceFiles}
            onUploadFile={async (file: File) => {
              setUploadingFile(true)
              try {
                const meta = await uploadReferenceFile(file)
                setReferenceFiles(prev => [...prev, { id: meta.id, filename: meta.filename }])
              } catch (e: any) {
                alert(e.message)
              } finally {
                setUploadingFile(false)
              }
            }}
            onRemoveFile={(id: string) => setReferenceFiles(prev => prev.filter(f => f.id !== id))}
            uploadingFile={uploadingFile}
            onStart={handleStart}
            isRunning={isRunning}
          />
        )}

        {page === 'workflow' && (
          <WorkflowPage
            scenario={currentScenario}
            workflowStatus={workflowStatus}
            isRunning={isRunning}
            reviewTaskId={reviewTaskId}
            reviewFeedback={reviewFeedback}
            onReviewFeedbackChange={setReviewFeedback}
            onReview={handleReview}
            onSuspend={handleSuspend}
            onResume={handleResume}
            toolEvents={toolEvents}
            crewId={crewId}
          />
        )}

        {page === 'agents' && (
          <AgentsPage agents={agents} onAgentsChange={reloadAgents} />
        )}

        {page === 'history' && (
          <HistoryPage
            history={history}
            selectedRecord={selectedRecord}
            onSelect={async (id: string) => {
              const record = await fetchResult(id)
              setSelectedRecord(record)
            }}
            onClose={() => setSelectedRecord(null)}
          />
        )}
      </main>
    </div>
  )
}

/* ── Login Page ─────────────────────────────────────────────── */

function LoginPage({
  onLogin,
  onRegister,
  theme,
}: {
  onLogin: (username: string, password: string) => Promise<void>
  onRegister: (username: string, password: string) => Promise<void>
  theme: Theme
}) {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
  }, [theme])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    if (mode === 'register' && password !== confirmPassword) {
      setError('两次输入的密码不一致')
      return
    }
    setLoading(true)
    try {
      if (mode === 'login') {
        await onLogin(username, password)
      } else {
        await onRegister(username, password)
      }
    } catch (err: any) {
      setError(err.message || '操作失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-header">
          <Bot size={36} color="#a29bfe" />
          <h1>AgentCrew</h1>
          <p>多智能体工作方案系统</p>
        </div>

        <div className="auth-tabs">
          <button
            className={`auth-tab ${mode === 'login' ? 'active' : ''}`}
            onClick={() => { setMode('login'); setError('') }}
          >
            登录
          </button>
          <button
            className={`auth-tab ${mode === 'register' ? 'active' : ''}`}
            onClick={() => { setMode('register'); setError('') }}
          >
            注册
          </button>
        </div>

        <form onSubmit={handleSubmit} className="auth-form">
          <div className="form-group">
            <label className="form-label">用户名</label>
            <input
              className="form-input"
              value={username}
              onChange={e => setUsername(e.target.value)}
              placeholder="至少 3 个字符"
              required
              minLength={3}
              autoComplete="username"
            />
          </div>
          <div className="form-group">
            <label className="form-label">密码</label>
            <input
              className="form-input"
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="至少 6 个字符"
              required
              minLength={6}
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            />
          </div>
          {mode === 'register' && (
            <div className="form-group">
              <label className="form-label">确认密码</label>
              <input
                className="form-input"
                type="password"
                value={confirmPassword}
                onChange={e => setConfirmPassword(e.target.value)}
                placeholder="再次输入密码"
                required
                minLength={6}
                autoComplete="new-password"
              />
            </div>
          )}
          {error && <div className="auth-error">{error}</div>}
          <button className="btn btn-primary auth-submit" type="submit" disabled={loading}>
            {loading ? <Loader size={16} className="spinner" /> : null}
            {mode === 'login' ? '登录' : '注册并登录'}
          </button>
        </form>

        {mode === 'login' && (
          <p className="auth-hint">默认管理员账号：admin / admin123</p>
        )}
      </div>
    </div>
  )
}

/* ── Settings Popover ─────────────────────────────────────────── */

function SettingsPopover({
  theme,
  onToggleTheme,
  user,
  onLogout,
  onClose,
}: {
  theme: Theme
  onToggleTheme: () => void
  user: UserInfo
  onLogout: () => void
  onClose: () => void
}) {
  return (
    <div className="settings-popover">
      <div className="settings-popover-header">
        <h3>设置</h3>
        <button className="icon-btn" onClick={onClose} title="关闭">
          <X size={16} />
        </button>
      </div>

      <div className="settings-section">
        <div className="settings-section-title">外观</div>
        <button className="settings-item" onClick={onToggleTheme}>
          {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
          <span>{theme === 'dark' ? '切换为浅色模式' : '切换为深色模式'}</span>
        </button>
      </div>

      <div className="settings-section">
        <div className="settings-section-title">账户</div>
        <div className="settings-user-info">
          <User size={18} />
          <span>{user.username}</span>
        </div>
        <button className="settings-item danger" onClick={onLogout}>
          <LogOut size={18} />
          <span>退出登录</span>
        </button>
      </div>
    </div>
  )
}

/* ── Dashboard Page ─────────────────────────────────────────── */

function DashboardPage({
  scenarios, agents, selectedScenario, onSelectScenario,
  selectedAgents, onToggleAgent,
  userInput, onInputChange,
  referenceFiles, onUploadFile, onRemoveFile, uploadingFile, onStart, isRunning,
}: any) {
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) onUploadFile(file)
    e.target.value = ''
  }

  const scenario = scenarios.find((s: Scenario) => s.id === selectedScenario)
  const scenarioAgentIds = new Set(scenario?.agents.map((a: { id: string }) => a.id) || [])

  return (
    <>
      <h2 className="page-title">创建工作方案</h2>
      <p className="page-desc">选择场景类型，挑选协作角色，描述您的研究需求，多智能体团队将协作为您制定方案。</p>

      <div className="form-group">
        <label className="form-label">选择场景</label>
        <div className="scenario-grid">
          {scenarios.map((s: Scenario) => (
            <div key={s.id}
              className={`scenario-card ${selectedScenario === s.id ? 'selected' : ''}`}
              onClick={() => onSelectScenario(s.id)}>
              <h3>{s.label}</h3>
              <p>{s.tasks.length} 个子任务 · {s.agents.length} 个 Agent 协作</p>
              <div className="scenario-agents">
                {s.agents.map(a => (
                  <span key={a.id} className="agent-tag">{a.name}</span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      {selectedScenario && (
        <div className="form-group">
          <label className="form-label">选择协作角色</label>
          <p className="form-hint">
            勾选参与本次工作流的 Agent 角色。取消某角色将跳过其对应任务；可在「Agent 角色」页添加自定义角色。
          </p>
          <div className="agent-select-grid">
            {agents.map((agent: Agent) => {
              const inScenario = scenarioAgentIds.has(agent.id)
              const checked = selectedAgents.includes(agent.id)
              return (
                <label
                  key={agent.id}
                  className={`agent-select-card ${checked ? 'selected' : ''} ${!inScenario ? 'extra' : ''}`}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => onToggleAgent(agent.id)}
                    disabled={isRunning}
                  />
                  <div className="agent-select-info">
                    <div className="agent-select-name">
                      {agent.name}
                      {agent.is_builtin && <span className="builtin-badge">内置</span>}
                      {!agent.is_builtin && <span className="custom-badge">自定义</span>}
                      {!inScenario && checked && <span className="extra-badge">额外加入</span>}
                    </div>
                    <div className="agent-select-title">{agent.title}</div>
                  </div>
                </label>
              )
            })}
          </div>
        </div>
      )}

      <div className="form-group">
        <label className="form-label">研究需求描述</label>
        <textarea
          className="form-textarea"
          placeholder="请详细描述您的研究课题，包括研究背景、目标、约束条件等。例如：我们课题组计划研究深度学习在医学影像诊断中的应用，需要设计一套完整的实验方案..."
          value={userInput}
          onChange={e => onInputChange(e.target.value)}
          rows={6}
        />
      </div>

      <div className="form-group">
        <label className="form-label">参考文件（可选）</label>
        <p className="form-hint">上传文献笔记、需求文档等（txt / md / csv / json，最大 2MB），规划师与文献 Agent 将读取内容。</p>
        <div className="upload-row">
          <label className="btn btn-outline upload-btn">
            {uploadingFile ? <Loader size={16} className="spinner" /> : <Upload size={16} />}
            {uploadingFile ? '上传中...' : '选择文件'}
            <input
              type="file"
              accept=".txt,.md,.markdown,.csv,.json"
              onChange={handleFileChange}
              disabled={uploadingFile || isRunning}
              hidden
            />
          </label>
        </div>
        {referenceFiles.length > 0 && (
          <ul className="file-list">
            {referenceFiles.map((f: { id: string; filename: string }) => (
              <li key={f.id} className="file-list-item">
                <FileText size={14} />
                <span>{f.filename}</span>
                <button
                  type="button"
                  className="file-remove"
                  onClick={() => onRemoveFile(f.id)}
                  disabled={isRunning}
                  title="移除"
                >
                  <X size={14} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <button className="btn btn-primary" onClick={onStart}
        disabled={!selectedScenario || selectedAgents.length === 0 || userInput.length < 10 || isRunning}>
        {isRunning ? <><Loader size={16} className="spinner" /> 启动中...</> :
          <><Play size={16} /> 启动多智能体工作流</>}
      </button>
    </>
  )
}

/* ── Export Buttons ─────────────────────────────────────────── */

function ExportButtons({ crewId, recordId }: { crewId?: string; recordId?: string }) {
  const [exporting, setExporting] = useState<'md' | 'docx' | null>(null)

  const handleExport = async (format: 'md' | 'docx') => {
    setExporting(format)
    try {
      await downloadExport({ format, crewId, recordId })
    } catch (e: any) {
      alert(e.message || '导出失败')
    } finally {
      setExporting(null)
    }
  }

  return (
    <div className="export-toolbar">
      <span className="export-label">导出方案</span>
      <button
        className="btn btn-outline"
        onClick={() => handleExport('md')}
        disabled={!!exporting}
      >
        {exporting === 'md' ? <Loader size={16} className="spinner" /> : <FileText size={16} />}
        导出 Markdown
      </button>
      <button
        className="btn btn-outline"
        onClick={() => handleExport('docx')}
        disabled={!!exporting}
      >
        {exporting === 'docx' ? <Loader size={16} className="spinner" /> : <FileDown size={16} />}
        导出 Word
      </button>
    </div>
  )
}

/* ── Workflow Page ──────────────────────────────────────────── */

function WorkflowPage({
  scenario, workflowStatus, isRunning, reviewTaskId, reviewFeedback,
  onReviewFeedbackChange, onReview, onSuspend, onResume, crewId, toolEvents,
}: any) {
  if (!workflowStatus) {
    return (
      <div className="empty-state">
        <Play size={48} />
        <p>请先从工作台启动一个工作流</p>
      </div>
    )
  }

  const statusIcon = (status: string) => {
    switch (status) {
      case 'running': return <Loader size={16} className="spinner" />
      case 'completed': return <CheckCircle size={16} color="#00b894" />
      case 'waiting_human': return <AlertTriangle size={16} color="#fdcb6e" />
      case 'suspended': return <Pause size={16} color="#e17055" />
      case 'failed': return <XCircle size={16} color="#e17055" />
      default: return <Clock size={16} color="#6b7194" />
    }
  }

  const statusLabel: Record<string, string> = {
    pending: '等待中', running: '执行中', completed: '已完成',
    waiting_human: '待审核', suspended: '已中止', failed: '失败',
  }

  const crewStatusLabel: Record<string, string> = {
    running: '运行中', paused: '待审核', suspended: '已中止',
    completed: '已完成', failed: '失败',
  }

  const canSuspend = workflowStatus.status === 'running' && isRunning
  const canResume = workflowStatus.status === 'suspended'
  const canExport = workflowStatus.status === 'completed' || workflowStatus.status === 'failed'

  return (
    <>
      <h2 className="page-title">工作流执行</h2>
      <p className="page-desc">
        状态: <span className={`status-badge ${workflowStatus.status}`}>
          {crewStatusLabel[workflowStatus.status] || workflowStatus.status}
        </span>
        {isRunning && ' · 智能体正在协作中...'}
        {canResume && ' · 工作流已中止，可点击继续恢复执行'}
      </p>

      {(canSuspend || canResume || canExport) && (
        <div className="workflow-toolbar">
          {canSuspend && (
            <button className="btn btn-danger" onClick={onSuspend}>
              <Pause size={16} /> 中止
            </button>
          )}
          {canResume && (
            <button className="btn btn-primary" onClick={onResume}>
              <Play size={16} /> 继续
            </button>
          )}
          {canExport && crewId && (
            <ExportButtons crewId={crewId} />
          )}
        </div>
      )}

      {toolEvents && toolEvents.length > 0 && (
        <div className="tool-events-panel">
          <div className="tool-events-title">工具调用</div>
          <ul className="tool-events-list">
            {toolEvents.map((ev: { tool: string; status: string; detail: string }, i: number) => (
              <li key={i} className={`tool-event tool-event-${ev.status}`}>
                <span className="tool-event-name">{ev.tool}</span>
                <span className="tool-event-detail">{ev.detail}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="workflow-timeline">
        {(scenario?.tasks || []).map((task: any) => {
          const result = workflowStatus.results?.[task.id]
          const status = result?.status || 'pending'

          return (
            <div key={task.id} className="timeline-item">
              <div className={`timeline-dot ${status}`}>
                {statusIcon(status)}
              </div>
              <div className="timeline-content">
                <div className="timeline-header">
                  <div>
                    <div className="timeline-title">{task.name}</div>
                    <div className="timeline-agent">
                      负责: {scenario?.agents?.find((a: any) => a.id === task.agent_id)?.name || task.agent_id}
                      {task.requires_human_review && ' · 需人工审核'}
                    </div>
                  </div>
                  <span className={`status-badge ${status}`}>{statusLabel[status] || status}</span>
                </div>

                {(result?.output || status === 'running' || status === 'suspended') && (
                  <div className="markdown-output">
                    {result?.output ? (
                      <ReactMarkdown>{result.output}</ReactMarkdown>
                    ) : (
                      <span style={{ color: 'var(--text-secondary)', fontSize: 13 }}>
                        正在生成...
                      </span>
                    )}
                  </div>
                )}

                {result?.error && (
                  <div style={{ color: 'var(--danger)', fontSize: 13, marginTop: 8 }}>
                    错误: {result.error}
                  </div>
                )}

                {status === 'waiting_human' && task.id === reviewTaskId && (
                  <div className="review-panel">
                    <h4>人工审核</h4>
                    <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 8 }}>
                      请审核上述输出，可以输入修改意见后批准，或直接驳回。
                    </p>
                    <textarea
                      className="form-textarea"
                      placeholder="输入审核意见或修改建议（可选）..."
                      value={reviewFeedback}
                      onChange={e => onReviewFeedbackChange(e.target.value)}
                      rows={3}
                    />
                    <div className="review-actions">
                      <button className="btn btn-success" onClick={() => onReview(true)}>
                        <CheckCircle size={16} /> 批准并继续
                      </button>
                      <button className="btn btn-danger" onClick={() => onReview(false)}>
                        <XCircle size={16} /> 驳回
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </>
  )
}

/* ── Agents Page ────────────────────────────────────────────── */

const EMPTY_AGENT_FORM: AgentFormData = {
  name: '',
  title: '',
  background: '',
  goal: '',
  tools: [],
  use_reasoning: false,
}

function AgentsPage({ agents, onAgentsChange }: { agents: Agent[]; onAgentsChange: () => void }) {
  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState<AgentFormData>(EMPTY_AGENT_FORM)
  const [tools, setTools] = useState<ToolOption[]>([])
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    fetchAvailableTools().then(setTools)
  }, [])

  const openCreate = () => {
    setEditingId(null)
    setForm(EMPTY_AGENT_FORM)
    setShowForm(true)
  }

  const openEdit = (agent: Agent) => {
    setEditingId(agent.id)
    setForm({
      id: agent.id,
      name: agent.name,
      title: agent.title,
      background: agent.background,
      goal: agent.goal,
      tools: agent.tools,
      use_reasoning: agent.use_reasoning ?? false,
    })
    setShowForm(true)
  }

  const closeForm = () => {
    setShowForm(false)
    setEditingId(null)
    setForm(EMPTY_AGENT_FORM)
  }

  const handleSave = async () => {
    if (!form.name || !form.title || form.background.length < 10 || form.goal.length < 10) {
      alert('请填写完整的角色信息（背景与目标至少 10 字）')
      return
    }
    setSaving(true)
    try {
      if (editingId) {
        await updateAgent(editingId, form)
      } else {
        await createAgent(form)
      }
      onAgentsChange()
      closeForm()
    } catch (e: any) {
      alert(e.message)
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (agent: Agent) => {
    if (!confirm(`确定删除自定义角色「${agent.name}」？`)) return
    try {
      await deleteAgent(agent.id)
      onAgentsChange()
    } catch (e: any) {
      alert(e.message)
    }
  }

  const toggleTool = (toolId: string) => {
    setForm(prev => ({
      ...prev,
      tools: prev.tools.includes(toolId)
        ? prev.tools.filter(t => t !== toolId)
        : [...prev.tools, toolId],
    }))
  }

  return (
    <>
      <div className="page-header-row">
        <div>
          <h2 className="page-title">Agent 角色</h2>
          <p className="page-desc">
            系统内置 {agents.filter(a => a.is_builtin).length} 个核心角色，已自定义 {agents.filter(a => !a.is_builtin).length} 个。
          </p>
        </div>
        <button className="btn btn-primary" onClick={openCreate}>
          <Plus size={16} /> 添加角色
        </button>
      </div>

      {showForm && (
        <div className="card agent-form-card">
          <div className="card-title">{editingId ? '编辑角色' : '添加自定义角色'}</div>
          <div className="two-col">
            <div className="form-group">
              <label className="form-label">角色名称</label>
              <input
                className="form-input"
                value={form.name}
                onChange={e => setForm({ ...form, name: e.target.value })}
                placeholder="例如：数据分析专家"
              />
            </div>
            <div className="form-group">
              <label className="form-label">职称/头衔</label>
              <input
                className="form-input"
                value={form.title}
                onChange={e => setForm({ ...form, title: e.target.value })}
                placeholder="例如：统计分析与数据挖掘专家"
              />
            </div>
          </div>
          {!editingId && (
            <div className="form-group">
              <label className="form-label">角色 ID（可选）</label>
              <input
                className="form-input"
                value={form.id || ''}
                onChange={e => setForm({ ...form, id: e.target.value || undefined })}
                placeholder="小写字母开头，如 data_analyst（留空则自动生成）"
              />
            </div>
          )}
          <div className="form-group">
            <label className="form-label">专业背景</label>
            <textarea
              className="form-textarea"
              value={form.background}
              onChange={e => setForm({ ...form, background: e.target.value })}
              placeholder="描述该角色的专业背景、经验领域..."
              rows={3}
            />
          </div>
          <div className="form-group">
            <label className="form-label">核心目标</label>
            <textarea
              className="form-textarea"
              value={form.goal}
              onChange={e => setForm({ ...form, goal: e.target.value })}
              placeholder="描述该角色在工作流中的职责与输出目标..."
              rows={3}
            />
          </div>
          <div className="form-group">
            <label className="form-label">可用工具</label>
            <div className="tool-checkboxes">
              {tools.map(tool => (
                <label key={tool.id} className="tool-checkbox">
                  <input
                    type="checkbox"
                    checked={form.tools.includes(tool.id)}
                    onChange={() => toggleTool(tool.id)}
                  />
                  {tool.label}
                </label>
              ))}
            </div>
          </div>
          <label className="tool-checkbox" style={{ marginBottom: 16 }}>
            <input
              type="checkbox"
              checked={form.use_reasoning}
              onChange={e => setForm({ ...form, use_reasoning: e.target.checked })}
            />
            启用推理增强模型（deepseek-reasoner）
          </label>
          <div className="form-actions">
            <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
              {saving ? <Loader size={16} className="spinner" /> : <CheckCircle size={16} />}
              {editingId ? '保存修改' : '创建角色'}
            </button>
            <button className="btn btn-outline" onClick={closeForm}>取消</button>
          </div>
        </div>
      )}

      <div className="agent-grid">
        {agents.map(agent => (
          <div key={agent.id} className={`agent-card ${agent.is_builtin ? '' : 'custom'}`}>
            <div className="agent-card-header">
              <h3>{agent.name}</h3>
              {!agent.is_builtin && (
                <div className="agent-card-actions">
                  <button className="icon-btn" onClick={() => openEdit(agent)} title="编辑">
                    <Pencil size={14} />
                  </button>
                  <button className="icon-btn danger" onClick={() => handleDelete(agent)} title="删除">
                    <Trash2 size={14} />
                  </button>
                </div>
              )}
            </div>
            <div className="agent-title">
              {agent.title}
              {agent.is_builtin
                ? <span className="builtin-badge">内置</span>
                : <span className="custom-badge">自定义</span>}
            </div>
            <p><strong>背景：</strong>{agent.background}</p>
            <p><strong>目标：</strong>{agent.goal}</p>
            {agent.tools.length > 0 && (
              <div className="scenario-agents">
                {agent.tools.map(t => (
                  <span key={t} className="agent-tag">{t}</span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </>
  )
}

/* ── History Page ───────────────────────────────────────────── */

function HistoryPage({ history, selectedRecord, onSelect, onClose }: any) {
  const [searchQuery, setSearchQuery] = useState('')
  const [displayHistory, setDisplayHistory] = useState<HistoryRecord[]>(history)
  const [searching, setSearching] = useState(false)

  useEffect(() => {
    if (!searchQuery.trim()) {
      setDisplayHistory(history)
    }
  }, [history, searchQuery])

  useEffect(() => {
    const keyword = searchQuery.trim()
    if (!keyword) return

    const timer = setTimeout(async () => {
      setSearching(true)
      try {
        const records = await fetchHistory(undefined, keyword)
        setDisplayHistory(records)
      } catch {
        setDisplayHistory([])
      } finally {
        setSearching(false)
      }
    }, 300)

    return () => clearTimeout(timer)
  }, [searchQuery])

  if (selectedRecord) {
    return (
      <>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 24 }}>
          <button className="btn btn-outline" onClick={onClose}>← 返回</button>
          <h2 className="page-title" style={{ margin: 0 }}>方案详情</h2>
          <div style={{ marginLeft: 'auto' }}>
            <ExportButtons recordId={selectedRecord.id} />
          </div>
        </div>
        <p className="page-desc">
          {selectedRecord.title || selectedRecord.scenario} · {new Date(selectedRecord.created_at).toLocaleString('zh-CN')}
        </p>
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="card-title">用户需求</div>
          <p style={{ fontSize: 14, color: 'var(--text-secondary)' }}>{selectedRecord.user_input}</p>
        </div>
        {Object.entries(selectedRecord.tasks || {}).map(([tid, task]: [string, any]) => (
          <div key={tid} className="card" style={{ marginBottom: 12 }}>
            <div className="card-title">
              {tid}
              <span className={`status-badge ${task.status}`}>{task.status}</span>
            </div>
            {task.output && (
              <div className="markdown-output">
                <ReactMarkdown>{task.output}</ReactMarkdown>
              </div>
            )}
          </div>
        ))}
      </>
    )
  }

  return (
    <>
      <h2 className="page-title">历史方案</h2>
      <p className="page-desc">查看和管理过往的工作方案记录。</p>

      <div className="history-search">
        <Search size={18} className="history-search-icon" />
        <input
          className="form-input history-search-input"
          type="search"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="搜索方案标题或需求描述..."
        />
        {searching && <Loader size={16} className="history-search-loading" />}
      </div>

      {displayHistory.length === 0 ? (
        <div className="empty-state">
          <History size={48} />
          <p>{searchQuery.trim() ? '未找到匹配的方案' : '暂无历史记录'}</p>
        </div>
      ) : (
        <div className="history-list">
          {displayHistory.map((record: HistoryRecord) => (
            <div key={record.id} className="history-item" onClick={() => onSelect(record.id)}>
              <div>
                <div style={{ fontWeight: 500, fontSize: 14 }}>{record.title}</div>
                <div className="history-meta">
                  {record.scenario} · {record.task_count} 个任务 · {new Date(record.created_at).toLocaleString('zh-CN')}
                </div>
                {record.user_input && (
                  <div className="history-preview">{record.user_input}</div>
                )}
              </div>
              <span className="status-badge completed">查看</span>
            </div>
          ))}
        </div>
      )}
    </>
  )
}
