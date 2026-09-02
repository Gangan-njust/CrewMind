import { useState, useEffect, useRef } from 'react'
import {
  Play, Users, History, Bot, LayoutDashboard,
  CheckCircle, Clock, AlertTriangle, XCircle, Loader,
  Sun, Moon, Pause, FileText, FileDown, FileCode, Upload, X,
  Plus, Pencil, Trash2, Settings, LogOut, User, Search,
  GitCompare, Star, LayoutTemplate, Bookmark, CircleHelp, BookOpen, PenLine, FlaskConical, ClipboardPaste, Wrench,
  RefreshCw,
} from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { WorkflowVisualization } from './components/WorkflowVisualization'
import { LiteratureAssistant } from './components/LiteratureAssistant'
import { WritingAssistant } from './components/WritingAssistant'
import { ExperimentManager } from './components/ExperimentManager'
import { ToolboxPage } from './components/Toolbox'
import {
  fetchScenarios, fetchAgents, startWorkflow, getWorkflowStatus,
  submitFeedback, suspendWorkflow, resumeWorkflow, retryTask,
  fetchResult, connectWebSocket, downloadExport,
  uploadReferenceFile, createAgent, updateAgent, deleteAgent, fetchAvailableTools, extractAgentFromPrompt,
  login, register, logout, fetchMe, isAuthenticated,
  fetchTopics, fetchTopicVersions, setBestVersion, compareResults,
  fetchTemplates, createTemplate, deleteTemplate, fetchCollaborationModes,
  type Scenario, type Agent, type WorkflowStatus,
  type TopicRecord, type VersionRecord, type CompareResult,
  type AgentFormData, type ToolOption, type UserInfo,
  type WorkflowTemplate, type TemplateListResponse,
  type CollaborationMode, type CollaborationModeOption,
} from './api'
import {
  applyTemplateVariables,
  areTemplateVariablesFilled,
  buildEmptyVariableValues,
  getTemplateVariables,
  getVariablePlaceholder,
} from './templateUtils'
import { HELP_SECTIONS } from './helpContent'

type Page = 'dashboard' | 'workflow' | 'agents' | 'history' | 'literature' | 'writing' | 'experiment' | 'toolbox' | 'help'
type Theme = 'dark' | 'light'

const THEME_KEY = 'crewmind-theme'

function getInitialTheme(): Theme {
  const saved = localStorage.getItem(THEME_KEY)
  if (saved === 'light' || saved === 'dark') return saved
  return 'dark'
}

type WorkflowWsSetters = {
  setWorkflowStatus: React.Dispatch<React.SetStateAction<WorkflowStatus | null>>
  setReviewTaskId: React.Dispatch<React.SetStateAction<string>>
  setIsRunning: React.Dispatch<React.SetStateAction<boolean>>
  setToolEvents: React.Dispatch<React.SetStateAction<{ tool: string; status: string; detail: string }[]>>
}

function syncReviewFromStatus(
  status: WorkflowStatus,
  setReviewTaskId: WorkflowWsSetters['setReviewTaskId'],
  setIsRunning: WorkflowWsSetters['setIsRunning'],
) {
  if (status.status !== 'paused') return
  const waiting = Object.entries(status.results).find(([, r]) => r.status === 'waiting_human')
  if (waiting) {
    setReviewTaskId(waiting[0])
    setIsRunning(false)
  }
}

function handleWorkflowWebSocketMessage(
  crewId: string,
  msg: Record<string, unknown>,
  setters: WorkflowWsSetters,
) {
  const { setWorkflowStatus, setReviewTaskId, setIsRunning, setToolEvents } = setters

  if (msg.type === 'task_output_chunk') {
    setWorkflowStatus(prev => {
      if (!prev) return prev
      const taskId = msg.task_id as string
      const prevResult = prev.results[taskId] || { status: 'running', output: '', error: '', human_feedback: '' }
      if (prevResult.status === 'waiting_human') return prev
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
    return
  }

  if (msg.type === 'tool_invoked') {
    setToolEvents(prev => [
      ...prev,
      {
        tool: msg.tool as string,
        status: msg.status as string,
        detail: (msg.detail as string) || '',
      },
    ])
    return
  }

  if (msg.type === 'task_started') {
    setWorkflowStatus(prev => {
      if (!prev) return prev
      const taskId = msg.task_id as string
      return {
        ...prev,
        results: {
          ...prev.results,
          [taskId]: { status: 'running', output: '', error: '', human_feedback: '' },
        },
      }
    })
    return
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
            output: (msg.output as string) ?? prevResult.output,
          },
        },
      }
    })
    return
  }

  if (msg.type === 'human_review_required') {
    const taskId = msg.task_id as string
    setReviewTaskId(taskId)
    setIsRunning(false)
    setWorkflowStatus(prev => {
      if (!prev) return prev
      const prevResult = prev.results[taskId] || { status: 'waiting_human', output: '', error: '', human_feedback: '' }
      return {
        ...prev,
        status: 'paused',
        results: {
          ...prev.results,
          [taskId]: {
            ...prevResult,
            status: 'waiting_human',
            output: (msg.output as string) || prevResult.output,
          },
        },
      }
    })
    getWorkflowStatus(crewId).then(status => {
      setWorkflowStatus(status)
      syncReviewFromStatus(status, setReviewTaskId, setIsRunning)
    })
    return
  }

  if (msg.type === 'task_completed' || msg.type === 'status') {
    getWorkflowStatus(crewId).then(status => {
      setWorkflowStatus(status)
      syncReviewFromStatus(status, setReviewTaskId, setIsRunning)
    })
    return
  }

  if (msg.type === 'crew_completed') {
    setIsRunning(false)
    getWorkflowStatus(crewId).then(setWorkflowStatus)
    return
  }

  if (msg.type === 'crew_failed') {
    setIsRunning(false)
    setWorkflowStatus(prev => prev ? { ...prev, status: 'failed' } : prev)
    return
  }

  if (msg.type === 'crew_suspended') {
    setIsRunning(false)
    getWorkflowStatus(crewId).then(setWorkflowStatus)
    return
  }

  if (msg.type === 'crew_resumed') {
    setIsRunning(true)
    setReviewTaskId('')
    setWorkflowStatus(prev => prev ? { ...prev, status: 'running' } : prev)
  }
}

function startWorkflowStatusPoll(crewId: string, setters: WorkflowWsSetters) {
  const { setWorkflowStatus, setReviewTaskId, setIsRunning } = setters
  const poll = setInterval(async () => {
    try {
      const status = await getWorkflowStatus(crewId)
      setWorkflowStatus(status)
      if (status.status === 'completed' || status.status === 'failed' || status.status === 'suspended') {
        clearInterval(poll)
        setIsRunning(false)
      }
      syncReviewFromStatus(status, setReviewTaskId, setIsRunning)
    } catch {
      clearInterval(poll)
    }
  }, 2000)
  return poll
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
  const [selectedScenario, setSelectedScenario] = useState('')
  const [selectedAgents, setSelectedAgents] = useState<string[]>([])
  const [collaborationMode, setCollaborationMode] = useState<CollaborationMode>('sequential')
  const [collaborationModes, setCollaborationModes] = useState<CollaborationModeOption[]>([])
  const [activeWorkflowScenario, setActiveWorkflowScenario] = useState<Scenario | null>(null)
  const [activeCollaborationMode, setActiveCollaborationMode] = useState<CollaborationMode>('sequential')
  const [userInput, setUserInput] = useState('')
  const [referenceFiles, setReferenceFiles] = useState<{ id: string; filename: string }[]>([])
  const [uploadingFile, setUploadingFile] = useState(false)
  const [toolEvents, setToolEvents] = useState<{ tool: string; status: string; detail: string }[]>([])
  const [crewId, setCrewId] = useState('')
  const [workflowStatus, setWorkflowStatus] = useState<WorkflowStatus | null>(null)
  const [isRunning, setIsRunning] = useState(false)
  const [reviewTaskId, setReviewTaskId] = useState('')
  const [reviewFeedback, setReviewFeedback] = useState('')
  const [regenerateTopic, setRegenerateTopic] = useState<TopicRecord | null>(null)
  const [templates, setTemplates] = useState<TemplateListResponse>({ recommended: [], mine: [] })
  const [activeTemplate, setActiveTemplate] = useState<WorkflowTemplate | null>(null)
  const [templateVariableValues, setTemplateVariableValues] = useState<Record<string, string>>({})
  const [showSaveTemplate, setShowSaveTemplate] = useState(false)
  const [writingFromRecordId, setWritingFromRecordId] = useState<string | null>(null)
  const [writingFromWorkspace, setWritingFromWorkspace] = useState<{ id: string; name: string } | null>(null)
  const [experimentFromRecordId, setExperimentFromRecordId] = useState<string | null>(null)

  const loadAppData = () => {
    fetchScenarios().then(setScenarios).catch(() => {})
    fetchAgents().then(setAgents).catch(() => {})
    fetchTemplates().then(setTemplates).catch(() => {})
    fetchCollaborationModes().then(setCollaborationModes).catch(() => {})
  }

  const reloadTemplates = () => fetchTemplates().then(setTemplates).catch(() => {})

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
    }
    window.addEventListener('auth:logout', onLogout)
    return () => window.removeEventListener('auth:logout', onLogout)
  }, [])

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem(THEME_KEY, theme)
  }, [theme])

  useEffect(() => {
    if (!workflowStatus) return
    syncReviewFromStatus(workflowStatus, setReviewTaskId, setIsRunning)
  }, [workflowStatus])

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
    if (activeTemplate && activeTemplate.scenario !== scenarioId) {
      setActiveTemplate(null)
      setTemplateVariableValues({})
    }
    setSelectedScenario(scenarioId)
    const scenario = scenarios.find(s => s.id === scenarioId)
    if (scenario) {
      setSelectedAgents(
        scenario.agents.filter(a => a.category !== 'domain_review').map(a => a.id)
      )
    }
  }

  const activeTemplateVariables = activeTemplate ? getTemplateVariables(activeTemplate) : []
  const composedUserInput = activeTemplate
    ? applyTemplateVariables(activeTemplate.user_input, templateVariableValues)
    : userInput
  const templateVariablesFilled = !activeTemplate
    || areTemplateVariablesFilled(activeTemplateVariables, templateVariableValues)
  const canStartWorkflow = !!selectedScenario
    && selectedAgents.length > 0
    && composedUserInput.length >= 10
    && templateVariablesFilled

  const handleRegenerateVersion = (topic: TopicRecord) => {
    setRegenerateTopic(topic)
    setActiveTemplate(null)
    setTemplateVariableValues({})
    setSelectedScenario(topic.scenario)
    const scenario = scenarios.find(s => s.id === topic.scenario)
    if (scenario) {
      setSelectedAgents(
        scenario.agents.filter(a => a.category !== 'domain_review').map(a => a.id)
      )
    }
    setUserInput(topic.user_input)
    setReferenceFiles([])
    setPage('dashboard')
  }

  const handleApplyTemplate = (template: WorkflowTemplate) => {
    setRegenerateTopic(null)
    setActiveTemplate(template)
    setTemplateVariableValues(buildEmptyVariableValues(getTemplateVariables(template)))
    setSelectedScenario(template.scenario)
    setSelectedAgents(template.selected_agents)
    setUserInput('')
    setReferenceFiles([])
  }

  const handleClearTemplate = () => {
    setActiveTemplate(null)
    setTemplateVariableValues({})
    setUserInput('')
  }

  const handleTemplateVariableChange = (name: string, value: string) => {
    setTemplateVariableValues(prev => ({ ...prev, [name]: value }))
  }

  const handleSaveTemplate = async (name: string, description: string) => {
    await createTemplate({
      name,
      description,
      scenario: selectedScenario,
      user_input: activeTemplate ? activeTemplate.user_input : userInput,
      selected_agents: selectedAgents,
    })
    reloadTemplates()
    setShowSaveTemplate(false)
  }

  const handleDeleteTemplate = async (templateId: string) => {
    if (!confirm('确定删除该模板？')) return
    try {
      await deleteTemplate(templateId)
      if (activeTemplate?.id === templateId) {
        setActiveTemplate(null)
        setTemplateVariableValues({})
      }
      reloadTemplates()
    } catch (e: any) {
      alert(e.message)
    }
  }

  const reloadAgents = () => fetchAgents().then(setAgents)

  const toggleTheme = () => setTheme(t => t === 'dark' ? 'light' : 'dark')

  const handleStart = async () => {
    if (!canStartWorkflow) return
    setIsRunning(true)
    setToolEvents([])
    try {
      const data = await startWorkflow(
        selectedScenario,
        composedUserInput,
        referenceFiles.map(f => f.id),
        selectedAgents,
        regenerateTopic?.id,
        collaborationMode,
      )
      setRegenerateTopic(null)
      setCrewId(data.crew_id)
      setActiveCollaborationMode(data.collaboration_mode || collaborationMode)
      setActiveWorkflowScenario({
        id: data.scenario,
        label: scenarios.find(s => s.id === data.scenario)?.label || data.scenario,
        agents: agents.filter(a => data.tasks.some((t: { agent_id: string }) => t.agent_id === a.id)),
        tasks: data.tasks,
      })
      setWorkflowStatus({
        crew_id: data.crew_id,
        scenario: data.scenario,
        collaboration_mode: data.collaboration_mode || collaborationMode,
        status: 'running',
        user_input: composedUserInput,
        results: {},
      })
      setPage('workflow')

      const wsSetters: WorkflowWsSetters = {
        setWorkflowStatus,
        setReviewTaskId,
        setIsRunning,
        setToolEvents,
      }
      connectWebSocket(data.crew_id, (msg) => handleWorkflowWebSocketMessage(data.crew_id, msg, wsSetters))
      startWorkflowStatusPoll(data.crew_id, wsSetters)
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

  const handleRetryTask = async (taskId: string) => {
    if (!crewId) return
    setIsRunning(true)
    setToolEvents([])
    setReviewTaskId('')
    try {
      await retryTask(crewId, taskId)
      setWorkflowStatus(prev => prev ? { ...prev, status: 'running' } : prev)
      const wsSetters: WorkflowWsSetters = {
        setWorkflowStatus,
        setReviewTaskId,
        setIsRunning,
        setToolEvents,
      }
      // WebSocket 保持连接，重新拉起状态轮询跟踪重试进度
      startWorkflowStatusPoll(crewId, wsSetters)
    } catch (e: any) {
      alert(e.message)
      setWorkflowStatus(prev => prev ? { ...prev, status: 'failed' } : prev)
      setIsRunning(false)
    }
  }

  const currentScenario = activeWorkflowScenario || scenarios.find(s => s.id === selectedScenario)

  const handleLiteratureWorkflowStart = async (newCrewId: string) => {
    setIsRunning(true)
    setToolEvents([])
    setCrewId(newCrewId)
    try {
      const status = await getWorkflowStatus(newCrewId)
      setWorkflowStatus(status)
      setActiveCollaborationMode(status.collaboration_mode || 'sequential')
      const tasks = (status.tasks || []).map(t => ({
        id: t.id,
        name: t.name,
        agent_id: t.agent_id,
        depends_on: t.depends_on,
        requires_human_review: t.requires_human_review ?? false,
      }))
      setActiveWorkflowScenario({
        id: status.scenario,
        label: scenarios.find(s => s.id === status.scenario)?.label || status.scenario,
        agents: agents.filter(a => tasks.some(t => t.agent_id === a.id)),
        tasks,
      })
      setPage('workflow')
      const wsSetters: WorkflowWsSetters = {
        setWorkflowStatus,
        setReviewTaskId,
        setIsRunning,
        setToolEvents,
      }
      connectWebSocket(newCrewId, (msg) => handleWorkflowWebSocketMessage(newCrewId, msg, wsSetters))
      startWorkflowStatusPoll(newCrewId, wsSetters)
      syncReviewFromStatus(status, setReviewTaskId, setIsRunning)
    } catch (e: any) {
      alert(e.message)
      setIsRunning(false)
    }
  }

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
            <h1>CrewMind</h1>
            <div className="subtitle">智能科研协作平台</div>
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
          onClick={() => setPage('history')}>
          <History size={18} /> 历史方案
        </button>
        <button className={`nav-item ${page === 'literature' ? 'active' : ''}`}
          onClick={() => setPage('literature')}>
          <BookOpen size={18} /> 文献助手
        </button>
        <button className={`nav-item ${page === 'writing' ? 'active' : ''}`}
          onClick={() => setPage('writing')}>
          <PenLine size={18} /> 学术写作
        </button>
        <button className={`nav-item ${page === 'experiment' ? 'active' : ''}`}
          onClick={() => setPage('experiment')}>
          <FlaskConical size={18} /> 实验数据
        </button>
        <button className={`nav-item ${page === 'toolbox' ? 'active' : ''}`}
          onClick={() => setPage('toolbox')}>
          <Wrench size={18} /> 工具箱
        </button>
        <button className={`nav-item ${page === 'help' ? 'active' : ''}`}
          onClick={() => setPage('help')}>
          <CircleHelp size={18} /> 使用帮助
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
        <div key={page} className="page-content">
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
            composedUserInput={composedUserInput}
            canStartWorkflow={canStartWorkflow}
            templateVariableValues={templateVariableValues}
            onTemplateVariableChange={handleTemplateVariableChange}
            templateVariablesFilled={templateVariablesFilled}
            activeTemplateVariables={activeTemplateVariables}
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
            regenerateTopic={regenerateTopic}
            onClearRegenerate={() => setRegenerateTopic(null)}
            templates={templates}
            activeTemplate={activeTemplate}
            onApplyTemplate={handleApplyTemplate}
            onClearTemplate={handleClearTemplate}
            onSaveTemplate={() => setShowSaveTemplate(true)}
            onDeleteTemplate={handleDeleteTemplate}
            showSaveTemplate={showSaveTemplate}
            onCloseSaveTemplate={() => setShowSaveTemplate(false)}
            onConfirmSaveTemplate={handleSaveTemplate}
            collaborationMode={collaborationMode}
            onCollaborationModeChange={setCollaborationMode}
            collaborationModes={collaborationModes}
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
            onRetryTask={handleRetryTask}
            toolEvents={toolEvents}
            crewId={crewId}
            collaborationMode={activeCollaborationMode}
          />
        )}

        {page === 'agents' && (
          <AgentsPage agents={agents} onAgentsChange={reloadAgents} />
        )}

        {page === 'history' && (
          <HistoryPage
            onRegenerateVersion={handleRegenerateVersion}
            onCreateWriting={(recordId) => {
              setWritingFromRecordId(recordId)
              setPage('writing')
            }}
            onCreateExperiment={(recordId) => {
              setExperimentFromRecordId(recordId)
              setPage('experiment')
            }}
            onSaveAsTemplate={async (topic: TopicRecord, agents: string[]) => {
              const name = prompt('模板名称', topic.title || '我的方案模板')
              if (!name?.trim()) return
              try {
                await createTemplate({
                  name: name.trim(),
                  description: `来自历史课题「${topic.title}」`,
                  scenario: topic.scenario,
                  user_input: topic.user_input,
                  selected_agents: agents,
                })
                reloadTemplates()
                alert('模板已保存，可在工作台「我的模板」中使用')
              } catch (e: any) {
                alert(e.message)
              }
            }}
            scenarios={scenarios}
          />
        )}

        {page === 'help' && <HelpPage />}

        {page === 'literature' && (
          <LiteratureAssistant
            onStartWorkflow={handleLiteratureWorkflowStart}
            onStartWriting={(ws) => {
              setWritingFromWorkspace({ id: ws.id, name: ws.name })
              setPage('writing')
            }}
          />
        )}

        {page === 'writing' && (
          <WritingAssistant
            workflowRecordId={writingFromRecordId}
            workspaceLink={writingFromWorkspace}
            onProjectReady={() => setWritingFromRecordId(null)}
            onWorkspaceLinkReady={() => setWritingFromWorkspace(null)}
          />
        )}

        {page === 'experiment' && (
          <ExperimentManager
            workflowRecordId={experimentFromRecordId}
          />
        )}

        {page === 'toolbox' && <ToolboxPage />}
        </div>
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
          <h1>CrewMind</h1>
          <p>智能科研协作平台</p>
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

function SaveTemplateModal({
  onClose,
  onSave,
}: {
  onClose: () => void
  onSave: (name: string, description: string) => Promise<void>
}) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [saving, setSaving] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return
    setSaving(true)
    try {
      await onSave(name.trim(), description.trim())
    } catch (err: any) {
      alert(err.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h3>保存为模板</h3>
          <button className="icon-btn" onClick={onClose} title="关闭"><X size={16} /></button>
        </div>
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label className="form-label">模板名称</label>
            <input
              className="form-input"
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="例如：课题组常用文献综述"
              required
              autoFocus
            />
          </div>
          <div className="form-group">
            <label className="form-label">说明（可选）</label>
            <input
              className="form-input"
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="简要描述适用场景"
            />
          </div>
          <p className="form-hint">
            将保存当前场景、勾选的 Agent 与需求描述。使用模板时保存的是带占位符的模板结构，而非已填写的具体内容。
          </p>
          <div className="form-actions">
            <button className="btn btn-primary" type="submit" disabled={saving || !name.trim()}>
              {saving ? <Loader size={16} className="spinner" /> : <Bookmark size={16} />}
              保存模板
            </button>
            <button className="btn btn-outline" type="button" onClick={onClose}>取消</button>
          </div>
        </form>
      </div>
    </div>
  )
}

function DashboardPage({
  scenarios, agents, selectedScenario, onSelectScenario,
  selectedAgents, onToggleAgent,
  userInput, onInputChange, composedUserInput, canStartWorkflow,
  templateVariableValues, onTemplateVariableChange,
  templateVariablesFilled, activeTemplateVariables,
  referenceFiles, onUploadFile, onRemoveFile, uploadingFile, onStart, isRunning,
  regenerateTopic, onClearRegenerate,
  templates, activeTemplate, onApplyTemplate, onClearTemplate,
  onSaveTemplate, onDeleteTemplate,
  showSaveTemplate, onCloseSaveTemplate, onConfirmSaveTemplate,
  collaborationMode, onCollaborationModeChange, collaborationModes,
}: any) {
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) onUploadFile(file)
    e.target.value = ''
  }

  const scenario = scenarios.find((s: Scenario) => s.id === selectedScenario)
  const scenarioAgentIds = new Set(scenario?.agents.map((a: { id: string }) => a.id) || [])
  const canSaveTemplate = selectedScenario && selectedAgents.length > 0
    && (activeTemplate ? activeTemplate.user_input.length >= 10 : userInput.length >= 10)
  const filledVariableCount = activeTemplateVariables.filter(
    (v: string) => (templateVariableValues[v] || '').trim().length > 0
  ).length

  return (
    <>
      <h2 className="page-title">创建工作方案</h2>
      <p className="page-desc">选择场景类型，挑选协作角色，描述您的研究需求，多智能体团队将协作为您制定方案。</p>

      <div className="form-group">
        <div className="template-section-header">
          <label className="form-label" style={{ margin: 0 }}>
            <LayoutTemplate size={16} style={{ verticalAlign: 'middle', marginRight: 6 }} />
            从模板快速开始
          </label>
        </div>
        <p className="form-hint">选用推荐或已保存的模板，预填场景与 Agent 配置，通过下方输入框填写关键参数即可。</p>

        {templates.recommended?.length > 0 && (
          <>
            <div className="template-subtitle">常用推荐</div>
            <div className="template-grid">
              {templates.recommended.map((tpl: WorkflowTemplate) => (
                <div
                  key={tpl.id}
                  className={`template-card recommended ${activeTemplate?.id === tpl.id ? 'active' : ''}`}
                  onClick={() => onApplyTemplate(tpl)}
                >
                  <div className="template-card-name">{tpl.name}</div>
                  <div className="template-card-desc">{tpl.description}</div>
                  <div className="template-card-meta">
                    {scenarios.find((s: Scenario) => s.id === tpl.scenario)?.label || tpl.scenario}
                    · {tpl.selected_agents.length} 个 Agent
                  </div>
                </div>
              ))}
            </div>
          </>
        )}

        {templates.mine?.length > 0 && (
          <>
            <div className="template-subtitle">我的模板</div>
            <div className="template-grid">
              {templates.mine.map((tpl: WorkflowTemplate) => (
                <div
                  key={tpl.id}
                  className={`template-card ${activeTemplate?.id === tpl.id ? 'active' : ''}`}
                  onClick={() => onApplyTemplate(tpl)}
                >
                  <div className="template-card-header">
                    <div className="template-card-name">{tpl.name}</div>
                    <button
                      className="icon-btn danger"
                      title="删除模板"
                      onClick={(e) => { e.stopPropagation(); onDeleteTemplate(tpl.id) }}
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                  {tpl.description && <div className="template-card-desc">{tpl.description}</div>}
                  <div className="template-card-meta">
                    {scenarios.find((s: Scenario) => s.id === tpl.scenario)?.label || tpl.scenario}
                    · {tpl.selected_agents.length} 个 Agent
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      {activeTemplate && (
        <div className="template-active-banner">
          <div>
            <strong>已加载模板：{activeTemplate.name}</strong>
            {activeTemplateVariables.length > 0 && (
              <div className="template-variables">
                填写进度：{filledVariableCount}/{activeTemplateVariables.length}
                {!templateVariablesFilled && (
                  <span className="template-progress-hint"> · 请完成下方所有参数后再启动</span>
                )}
              </div>
            )}
          </div>
          <button className="btn btn-outline btn-sm" onClick={onClearTemplate}>清除模板</button>
        </div>
      )}

      {regenerateTopic && (
        <div className="regenerate-banner">
          <span>正在为课题「{regenerateTopic.title}」生成新版本（将自动归入同一课题）</span>
          <button className="btn btn-outline btn-sm" onClick={onClearRegenerate}>取消</button>
        </div>
      )}

      <div className="form-group">
        <label className="form-label">协作模式</label>
        <p className="form-hint">
          串行模式按固定流程依次执行；辩论模式通过正反方多轮答辩完善方案；投票模式由多个求解者并行生成方案后聚合选出最优。
        </p>
        <select
          className="form-input"
          value={collaborationMode}
          onChange={e => onCollaborationModeChange(e.target.value)}
          disabled={isRunning}
          aria-label="协作模式"
        >
          {(collaborationModes.length > 0 ? collaborationModes : [
            { id: 'sequential', label: '串行模式' },
            { id: 'debate', label: '辩论模式' },
            { id: 'voting', label: '投票模式' },
          ]).map((mode: CollaborationModeOption) => (
            <option key={mode.id} value={mode.id}>{mode.label}</option>
          ))}
        </select>
      </div>

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

      {selectedScenario && collaborationMode === 'sequential' && (
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
                      {agent.is_builtin && agent.category === 'domain_review' && (
                        <span className="domain-badge">领域审稿</span>
                      )}
                      {agent.is_builtin && agent.category !== 'domain_review' && (
                        <span className="builtin-badge">内置</span>
                      )}
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

      {activeTemplate && activeTemplateVariables.length > 0 && (
        <div className="form-group">
          <label className="form-label">填写模板参数</label>
          <p className="form-hint">在输入框中填写各项关键信息，系统将自动生成完整需求描述。</p>
          <div className="template-variable-grid">
            {activeTemplateVariables.map((variable: string) => (
              <div key={variable} className="form-group template-variable-field">
                <label className="form-label">{variable}</label>
                <input
                  className="form-input"
                  value={templateVariableValues[variable] || ''}
                  onChange={e => onTemplateVariableChange(variable, e.target.value)}
                  placeholder={getVariablePlaceholder(variable)}
                  disabled={isRunning}
                />
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="form-group">
        <label className="form-label">
          {activeTemplate ? '需求描述预览' : '研究需求描述'}
        </label>
        {activeTemplate ? (
          <>
            <p className="form-hint">根据上方参数自动生成的完整描述，启动时将使用此内容。</p>
            <textarea
              className="form-textarea template-preview"
              value={composedUserInput}
              readOnly
              rows={8}
              aria-label="根据模板参数生成的需求描述预览"
            />
          </>
        ) : (
          <textarea
            className="form-textarea"
            placeholder="请详细描述您的研究课题，包括研究背景、目标、约束条件等。例如：我们课题组计划研究深度学习在医学影像诊断中的应用，需要设计一套完整的实验方案..."
            value={userInput}
            onChange={e => onInputChange(e.target.value)}
            rows={6}
          />
        )}
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

      <div className="dashboard-actions">
        <button className="btn btn-primary" onClick={onStart}
          disabled={!canStartWorkflow || isRunning}>
          {isRunning ? <><Loader size={16} className="spinner" /> 启动中...</> :
            <><Play size={16} /> 启动多智能体工作流</>}
        </button>
        <button
          className="btn btn-outline"
          onClick={onSaveTemplate}
          disabled={!canSaveTemplate || isRunning}
          title="将当前配置保存为可复用模板"
        >
          <Bookmark size={16} /> 保存为模板
        </button>
      </div>

      {showSaveTemplate && (
        <SaveTemplateModal
          onClose={onCloseSaveTemplate}
          onSave={onConfirmSaveTemplate}
        />
      )}
    </>
  )
}

/* ── Export Buttons ─────────────────────────────────────────── */

function ExportButtons({
  crewId, recordId, scenario,
}: { crewId?: string; recordId?: string; scenario?: string }) {
  type ExportScope = 'full' | 'proposal' | 'pure'
  type ExportKey = `${ExportScope}-${'md' | 'docx' | 'tex'}`
  const [exporting, setExporting] = useState<ExportKey | null>(null)

  const isReviewRun = !!scenario && scenario.includes('review')
  // 兼容旧调用（未传 scenario 时按原有逻辑全部展示）
  const showProposalScope = scenario
    ? ['literature_based_proposal', 'full_proposal', 'experiment_design', 'proposal'].includes(scenario)
    : true

  const handleExport = async (format: 'md' | 'docx' | 'tex', scope: ExportScope = 'full') => {
    const key: ExportKey = `${scope}-${format}`
    setExporting(key)
    try {
      await downloadExport({ format, crewId, recordId, scope })
    } catch (e: any) {
      alert(e.message || '导出失败')
    } finally {
      setExporting(null)
    }
  }

  const renderFormatButtons = (scope: ExportScope, labels: { md: string; docx: string; tex: string }) => (
    <>
      <button
        className="btn btn-outline"
        onClick={() => handleExport('md', scope)}
        disabled={!!exporting}
      >
        {exporting === `${scope}-md` ? <Loader size={16} className="spinner" /> : <FileText size={16} />}
        {labels.md}
      </button>
      <button
        className="btn btn-outline"
        onClick={() => handleExport('docx', scope)}
        disabled={!!exporting}
      >
        {exporting === `${scope}-docx` ? <Loader size={16} className="spinner" /> : <FileDown size={16} />}
        {labels.docx}
      </button>
      <button
        className="btn btn-outline"
        onClick={() => handleExport('tex', scope)}
        disabled={!!exporting}
      >
        {exporting === `${scope}-tex` ? <Loader size={16} className="spinner" /> : <FileCode size={16} />}
        {labels.tex}
      </button>
    </>
  )

  const formatLabels = {
    md: 'Markdown',
    docx: 'Word',
    tex: 'LaTeX',
  }

  return (
    <div className="export-toolbar">
      <span className="export-label">导出方案</span>
      {renderFormatButtons('full', formatLabels)}
      {showProposalScope && (
        <>
          <span className="export-divider" />
          <span className="export-label">仅开题报告</span>
          {renderFormatButtons('proposal', formatLabels)}
        </>
      )}
      <span className="export-divider" />
      <span className="export-label">{isReviewRun ? '纯综述' : '纯文章'}</span>
      {renderFormatButtons('pure', formatLabels)}
    </div>
  )
}

/* ── Workflow Page ──────────────────────────────────────────── */

function WorkflowPage({
  scenario, workflowStatus, isRunning, reviewTaskId, reviewFeedback,
  onReviewFeedbackChange, onReview, onSuspend, onResume, onRetryTask, crewId, toolEvents,
  collaborationMode,
}: any) {
  if (!workflowStatus) {
    return (
      <div className="empty-state">
        <Play size={48} />
        <p>请先从工作台启动一个工作流</p>
      </div>
    )
  }

  const crewStatusLabel: Record<string, string> = {
    running: '运行中', paused: '待审核', suspended: '已中止',
    completed: '已完成', failed: '失败',
  }

  const canSuspend = workflowStatus.status === 'running' && isRunning
  const canResume = workflowStatus.status === 'suspended'
  const canExport = workflowStatus.status === 'completed' || workflowStatus.status === 'failed'
  const taskList = (workflowStatus.tasks && workflowStatus.tasks.length)
    ? workflowStatus.tasks
    : (scenario?.tasks || [])
  const failedTasks = taskList.filter(
    (t: { id: string }) => workflowStatus.results?.[t.id]?.status === 'failed',
  )

  const modeLabel: Record<string, string> = {
    sequential: '串行模式',
    debate: '辩论模式',
    voting: '投票模式',
  }
  return (
    <>
      <h2 className="page-title">工作流执行</h2>
      <p className="page-desc">
        协作模式: <span className="collaboration-mode-badge">{modeLabel[collaborationMode] || collaborationMode}</span>
        {' · '}
        状态: <span className={`status-badge ${workflowStatus.status}`}>
          {crewStatusLabel[workflowStatus.status] || workflowStatus.status}
        </span>
        {isRunning && ' · 智能体正在协作中...'}
        {canResume && ' · 工作流已中止，可点击继续恢复执行'}
        {workflowStatus.status === 'failed' && ' · 部分结果已保存，可直接导出或重试失败任务'}
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
            <ExportButtons
              crewId={crewId}
              scenario={workflowStatus?.scenario || scenario?.id}
            />
          )}
        </div>
      )}

      {workflowStatus.status === 'failed' && failedTasks.length > 0 && (
        <div className="retry-panel">
          <div className="retry-panel-title">
            <RefreshCw size={14} /> 失败任务重试
          </div>
          <p className="retry-panel-desc">
            已完成子任务的结果已自动保存到历史方案，可随时导出，已消耗的 token 不会白费。
            重试只会重跑失败任务及其下游任务，其余已完成任务保持不动：
          </p>
          <div className="retry-task-list">
            {failedTasks.map((t: { id: string; name: string }) => (
              <button
                key={t.id}
                className="btn btn-warning"
                disabled={isRunning}
                onClick={() => onRetryTask?.(t.id)}
                title={`从「${t.name}」继续执行`}
              >
                <RefreshCw size={14} /> 重试「{t.name}」
              </button>
            ))}
          </div>
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

      <WorkflowVisualization
        tasks={scenario?.tasks || []}
        agents={scenario?.agents || []}
        results={workflowStatus.results || {}}
        collaborationMode={collaborationMode}
        reviewTaskId={reviewTaskId}
        reviewFeedback={reviewFeedback}
        onReviewFeedbackChange={onReviewFeedbackChange}
        onReview={onReview}
      />
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

function AgentCard({
  agent,
  onEdit,
  onDelete,
}: {
  agent: Agent
  onEdit: (agent: Agent) => void
  onDelete: (agent: Agent) => void
}) {
  return (
    <div className={`agent-card ${agent.is_builtin ? '' : 'custom'}`}>
      <div className="agent-card-header">
        <h3>{agent.name}</h3>
        {!agent.is_builtin && (
          <div className="agent-card-actions">
            <button className="icon-btn" onClick={() => onEdit(agent)} title="编辑">
              <Pencil size={14} />
            </button>
            <button className="icon-btn danger" onClick={() => onDelete(agent)} title="删除">
              <Trash2 size={14} />
            </button>
          </div>
        )}
      </div>
      <div className="agent-title">
        {agent.title}
        {agent.is_builtin && agent.category === 'domain_review' && (
          <span className="domain-badge">领域审稿</span>
        )}
        {agent.is_builtin && agent.category !== 'domain_review' && (
          <span className="builtin-badge">内置</span>
        )}
        {!agent.is_builtin && <span className="custom-badge">自定义</span>}
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
  )
}

function AgentsPage({ agents, onAgentsChange }: { agents: Agent[]; onAgentsChange: () => void }) {
  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [formMode, setFormMode] = useState<'manual' | 'paste'>('manual')
  const [promptText, setPromptText] = useState('')
  const [form, setForm] = useState<AgentFormData>(EMPTY_AGENT_FORM)
  const [tools, setTools] = useState<ToolOption[]>([])
  const [saving, setSaving] = useState(false)
  const [extracting, setExtracting] = useState(false)

  useEffect(() => {
    fetchAvailableTools().then(setTools)
  }, [])

  const openCreate = () => {
    setEditingId(null)
    setFormMode('manual')
    setPromptText('')
    setForm(EMPTY_AGENT_FORM)
    setShowForm(true)
  }

  const openEdit = (agent: Agent) => {
    setEditingId(agent.id)
    setFormMode('manual')
    setPromptText('')
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
    setFormMode('manual')
    setPromptText('')
    setForm(EMPTY_AGENT_FORM)
  }

  const handleExtractPrompt = async () => {
    if (!promptText.trim()) return
    setExtracting(true)
    try {
      const data = await extractAgentFromPrompt(promptText)
      setForm(prev => ({
        ...prev,
        id: data.id ?? prev.id,
        name: data.name ?? prev.name,
        title: data.title ?? prev.title,
        background: data.background ?? prev.background,
        goal: data.goal ?? prev.goal,
        tools: data.tools?.length ? data.tools : prev.tools,
        use_reasoning: data.use_reasoning ?? prev.use_reasoning,
      }))
      setFormMode('manual')
    } catch (e: any) {
      alert(e.message)
    } finally {
      setExtracting(false)
    }
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
            系统内置 {agents.filter(a => a.is_builtin).length} 个角色（含 {agents.filter(a => a.is_builtin && a.category === 'domain_review').length} 个学科领域审稿专家），已自定义 {agents.filter(a => !a.is_builtin).length} 个。
          </p>
        </div>
        <button className="btn btn-primary" onClick={openCreate}>
          <Plus size={16} /> 添加角色
        </button>
      </div>

      {showForm && (
        <div className="card agent-form-card">
          <div className="card-title">{editingId ? '编辑角色' : '添加自定义角色'}</div>

          {!editingId && (
            <>
              <div className="agent-form-tabs">
                <button
                  type="button"
                  className={`agent-form-tab ${formMode === 'manual' ? 'active' : ''}`}
                  onClick={() => setFormMode('manual')}
                >
                  表单填写
                </button>
                <button
                  type="button"
                  className={`agent-form-tab ${formMode === 'paste' ? 'active' : ''}`}
                  onClick={() => setFormMode('paste')}
                >
                  <ClipboardPaste size={14} /> 粘贴提示词
                </button>
              </div>

              {formMode === 'paste' && (
                <div className="agent-prompt-panel">
                  <p className="form-hint">
                    支持直接粘贴 Markdown 格式提示词（标题、小节、列表、粗体等），也支持普通文本或 JSON。
                    若整段包在 <code>```markdown</code> 代码块中亦可识别。提取完成后可在「表单填写」中核对修改。
                  </p>
                  <div className="form-group">
                    <label className="form-label">粘贴 Markdown 提示词</label>
                    <textarea
                      className="form-textarea agent-prompt-textarea"
                      value={promptText}
                      onChange={e => setPromptText(e.target.value)}
                      placeholder={'支持 Markdown，例如：\n\n# 文献调研专家\n\n你是一位专业的学术文献调研分析师。\n\n## 专业背景\n- 精通文献检索策略\n- 熟悉 RAG 与网络检索\n\n## 核心目标\n输出文献综述并识别研究空白。'}
                      rows={12}
                    />
                  </div>
                  <div className="form-actions">
                    <button
                      type="button"
                      className="btn btn-primary"
                      onClick={handleExtractPrompt}
                      disabled={!promptText.trim() || extracting}
                    >
                      {extracting ? <Loader size={16} className="spinner" /> : <ClipboardPaste size={16} />}
                      {extracting ? '正在提取…' : '智能提取'}
                    </button>
                  </div>
                </div>
              )}
            </>
          )}

          {(editingId || formMode === 'manual') && (
            <>
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
            </>
          )}
        </div>
      )}

      <div className="agent-grid">
        {agents.filter(a => a.is_builtin && a.category !== 'domain_review').length > 0 && (
          <>
            <h3 className="agent-section-title">核心协作角色</h3>
            {agents.filter(a => a.is_builtin && a.category !== 'domain_review').map(agent => (
              <AgentCard key={agent.id} agent={agent} onEdit={openEdit} onDelete={handleDelete} />
            ))}
          </>
        )}
        {agents.filter(a => a.is_builtin && a.category === 'domain_review').length > 0 && (
          <>
            <h3 className="agent-section-title">学科领域审稿专家</h3>
            {agents.filter(a => a.is_builtin && a.category === 'domain_review').map(agent => (
              <AgentCard key={agent.id} agent={agent} onEdit={openEdit} onDelete={handleDelete} />
            ))}
          </>
        )}
        {agents.filter(a => !a.is_builtin).length > 0 && (
          <>
            <h3 className="agent-section-title">自定义角色</h3>
            {agents.filter(a => !a.is_builtin).map(agent => (
              <AgentCard key={agent.id} agent={agent} onEdit={openEdit} onDelete={handleDelete} />
            ))}
          </>
        )}
      </div>
    </>
  )
}

/* ── Help Page ──────────────────────────────────────────────── */

function HelpPage() {
  const [activeSection, setActiveSection] = useState(HELP_SECTIONS[0].id)

  const current = HELP_SECTIONS.find(s => s.id === activeSection) || HELP_SECTIONS[0]

  return (
    <div className="help-layout">
      <nav className="help-nav">
        <h2 className="help-nav-title">使用帮助</h2>
        <p className="help-nav-desc">快速了解 CrewMind 的使用方法</p>
        <ul className="help-nav-list">
          {HELP_SECTIONS.map(section => (
            <li key={section.id}>
              <button
                className={`help-nav-item ${activeSection === section.id ? 'active' : ''}`}
                onClick={() => setActiveSection(section.id)}
              >
                {section.title}
              </button>
            </li>
          ))}
        </ul>
      </nav>
      <div className="help-content">
        <h2 className="page-title">{current.title}</h2>
        <div className="help-markdown">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{current.content}</ReactMarkdown>
        </div>
      </div>
    </div>
  )
}

/* ── History Page ───────────────────────────────────────────── */

type HistoryView = 'topics' | 'versions' | 'detail' | 'compare'

function DiffPanel({ diff, side }: { diff: CompareResult['task_diffs'][0]['line_diff']; side: 'a' | 'b' }) {
  return (
    <div className="diff-panel">
      {diff.map((hunk, i) => {
        const lines = side === 'a' ? hunk.lines_a : hunk.lines_b
        if (hunk.type === 'equal') {
          return lines.map((line, j) => (
            <div key={`${i}-${j}`} className="diff-line equal">{line || ' '}</div>
          ))
        }
        if (side === 'a' && hunk.type === 'add') return null
        if (side === 'b' && hunk.type === 'remove') return null
        const cls = hunk.type === 'remove' ? 'remove' : hunk.type === 'add' ? 'add' : 'change'
        return lines.map((line, j) => (
          <div key={`${i}-${j}`} className={`diff-line ${cls}`}>{line || ' '}</div>
        ))
      })}
    </div>
  )
}

function CompareView({
  comparison,
  onBack,
}: {
  comparison: CompareResult
  onBack: () => void
}) {
  const [activeTask, setActiveTask] = useState(comparison.task_diffs[0]?.task_id || '')

  return (
    <>
      <div className="page-header-row">
        <button className="btn btn-outline" onClick={onBack}>← 返回版本列表</button>
        <h2 className="page-title" style={{ margin: 0 }}>版本对比</h2>
      </div>
      <p className="page-desc">
        v{comparison.record_a.version_number} vs v{comparison.record_b.version_number}
        · 相似度参考各任务输出
      </p>

      <div className="compare-summary-grid">
        <div className="compare-summary-card">
          <div className="compare-summary-header">
            <span className="version-label">版本 A · v{comparison.record_a.version_number}</span>
            <span className="compare-date">{new Date(comparison.record_a.created_at).toLocaleString('zh-CN')}</span>
          </div>
          {comparison.advantages_a.length > 0 && (
            <div className="compare-advantages">
              <strong>相对优势</strong>
              <ul>{comparison.advantages_a.map((a, i) => <li key={i}>{a}</li>)}</ul>
            </div>
          )}
          {comparison.record_a.pros.length > 0 && (
            <div className="compare-pros">
              <strong>终审优点</strong>
              <ul>{comparison.record_a.pros.map((p, i) => <li key={i}>{p}</li>)}</ul>
            </div>
          )}
          {comparison.record_a.cons.length > 0 && (
            <div className="compare-cons">
              <strong>终审不足</strong>
              <ul>{comparison.record_a.cons.map((c, i) => <li key={i}>{c}</li>)}</ul>
            </div>
          )}
        </div>
        <div className="compare-summary-card">
          <div className="compare-summary-header">
            <span className="version-label">版本 B · v{comparison.record_b.version_number}</span>
            <span className="compare-date">{new Date(comparison.record_b.created_at).toLocaleString('zh-CN')}</span>
          </div>
          {comparison.advantages_b.length > 0 && (
            <div className="compare-advantages">
              <strong>相对优势</strong>
              <ul>{comparison.advantages_b.map((a, i) => <li key={i}>{a}</li>)}</ul>
            </div>
          )}
          {comparison.record_b.pros.length > 0 && (
            <div className="compare-pros">
              <strong>终审优点</strong>
              <ul>{comparison.record_b.pros.map((p, i) => <li key={i}>{p}</li>)}</ul>
            </div>
          )}
          {comparison.record_b.cons.length > 0 && (
            <div className="compare-cons">
              <strong>终审不足</strong>
              <ul>{comparison.record_b.cons.map((c, i) => <li key={i}>{c}</li>)}</ul>
            </div>
          )}
        </div>
      </div>

      <div className="compare-task-tabs">
        {comparison.task_diffs.map(task => (
          <button
            key={task.task_id}
            className={`compare-task-tab ${activeTask === task.task_id ? 'active' : ''}`}
            onClick={() => setActiveTask(task.task_id)}
          >
            {task.task_name}
            <span className="similarity-badge">{(task.similarity * 100).toFixed(0)}%</span>
          </button>
        ))}
      </div>

      {comparison.task_diffs.filter(t => t.task_id === activeTask).map(task => (
        <div key={task.task_id} className="compare-diff-container">
          <div className="compare-diff-header">
            <span>版本 A · v{comparison.record_a.version_number}（{task.output_length_a} 字）</span>
            <span>版本 B · v{comparison.record_b.version_number}（{task.output_length_b} 字）</span>
          </div>
          <div className="compare-diff-columns">
            <DiffPanel diff={task.line_diff} side="a" />
            <DiffPanel diff={task.line_diff} side="b" />
          </div>
        </div>
      ))}
    </>
  )
}

function HistoryPage({
  onRegenerateVersion,
  onSaveAsTemplate,
  onCreateWriting,
  onCreateExperiment,
  scenarios,
}: {
  onRegenerateVersion: (topic: TopicRecord) => void
  onSaveAsTemplate: (topic: TopicRecord, agents: string[]) => void
  onCreateWriting: (recordId: string) => void
  onCreateExperiment: (recordId: string) => void
  scenarios: Scenario[]
}) {
  const [view, setView] = useState<HistoryView>('topics')
  const [searchQuery, setSearchQuery] = useState('')
  const [topics, setTopics] = useState<TopicRecord[]>([])
  const [versions, setVersions] = useState<VersionRecord[]>([])
  const [selectedTopic, setSelectedTopic] = useState<TopicRecord | null>(null)
  const [selectedRecord, setSelectedRecord] = useState<any>(null)
  const [compareSelection, setCompareSelection] = useState<string[]>([])
  const [comparison, setComparison] = useState<CompareResult | null>(null)
  const [searching, setSearching] = useState(false)
  const [loading, setLoading] = useState(false)
  const [creatingWriting, setCreatingWriting] = useState(false)
  const [creatingExperiment, setCreatingExperiment] = useState(false)

  const loadTopics = async (search?: string) => {
    setSearching(true)
    try {
      const data = await fetchTopics(undefined, search)
      setTopics(data)
    } catch {
      setTopics([])
    } finally {
      setSearching(false)
    }
  }

  useEffect(() => {
    loadTopics()
  }, [])

  useEffect(() => {
    const keyword = searchQuery.trim()
    const timer = setTimeout(() => {
      loadTopics(keyword || undefined)
    }, 300)
    return () => clearTimeout(timer)
  }, [searchQuery])

  const openTopic = async (topic: TopicRecord) => {
    setLoading(true)
    try {
      const vers = await fetchTopicVersions(topic.id)
      setSelectedTopic(topic)
      setVersions(vers)
      setCompareSelection([])
      setView('versions')
    } catch (e: any) {
      alert(e.message)
    } finally {
      setLoading(false)
    }
  }

  const openRecord = async (recordId: string) => {
    setLoading(true)
    try {
      const record = await fetchResult(recordId)
      setSelectedRecord(record)
      setView('detail')
    } catch (e: any) {
      alert(e.message)
    } finally {
      setLoading(false)
    }
  }

  const handleMarkBest = async (recordId: string) => {
    if (!selectedTopic) return
    try {
      const updated = await setBestVersion(selectedTopic.id, recordId)
      setSelectedTopic(updated)
      const vers = await fetchTopicVersions(selectedTopic.id)
      setVersions(vers)
    } catch (e: any) {
      alert(e.message)
    }
  }

  const toggleCompareSelect = (recordId: string) => {
    setCompareSelection(prev => {
      if (prev.includes(recordId)) return prev.filter(id => id !== recordId)
      if (prev.length >= 2) return [prev[1], recordId]
      return [...prev, recordId]
    })
  }

  const handleCompare = async () => {
    if (compareSelection.length !== 2) return
    setLoading(true)
    try {
      const result = await compareResults(compareSelection[0], compareSelection[1])
      setComparison(result)
      setView('compare')
    } catch (e: any) {
      alert(e.message)
    } finally {
      setLoading(false)
    }
  }

  if (view === 'compare' && comparison) {
    return <CompareView comparison={comparison} onBack={() => setView('versions')} />
  }

  if (view === 'detail' && selectedRecord) {
    return (
      <>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 24 }}>
          <button className="btn btn-outline" onClick={() => setView('versions')}>← 返回</button>
          <h2 className="page-title" style={{ margin: 0 }}>方案详情</h2>
          {selectedRecord.version_number && (
            <span className="version-badge">v{selectedRecord.version_number}</span>
          )}
          {selectedRecord.metadata?.partial && (
            <span className="partial-badge"><AlertTriangle size={12} /> 部分结果</span>
          )}
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
            <button
              className="btn btn-primary"
              disabled={creatingWriting}
              onClick={async () => {
                setCreatingWriting(true)
                try {
                  onCreateWriting(selectedRecord.id)
                } finally {
                  setCreatingWriting(false)
                }
              }}
            >
              {creatingWriting ? <Loader size={16} className="spinner" /> : <PenLine size={16} />}
              创建写作项目
            </button>
            <button
              className="btn btn-secondary"
              disabled={creatingExperiment}
              onClick={async () => {
                setCreatingExperiment(true)
                try {
                  onCreateExperiment(selectedRecord.id)
                } finally {
                  setCreatingExperiment(false)
                }
              }}
            >
              {creatingExperiment ? <Loader size={16} className="spinner" /> : <FlaskConical size={16} />}
              创建实验项目
            </button>
            <ExportButtons recordId={selectedRecord.id} scenario={selectedRecord.scenario} />
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

  if (view === 'versions' && selectedTopic) {
    return (
      <>
        <div className="page-header-row">
          <button className="btn btn-outline" onClick={() => { setView('topics'); setSelectedTopic(null) }}>
            ← 返回课题列表
          </button>
          <h2 className="page-title" style={{ margin: 0 }}>{selectedTopic.title}</h2>
        </div>
        <p className="page-desc">
          {selectedTopic.scenario} · {selectedTopic.version_count} 个版本
          · 更新于 {new Date(selectedTopic.updated_at).toLocaleString('zh-CN')}
        </p>

        <div className="version-toolbar">
          <button className="btn btn-primary" onClick={() => onRegenerateVersion(selectedTopic)}>
            <Plus size={16} /> 再生成一版
          </button>
          <button
            className="btn btn-outline"
            onClick={() => {
              const scenario = scenarios.find(s => s.id === selectedTopic.scenario)
              onSaveAsTemplate(selectedTopic, scenario?.agents.map(a => a.id) || [])
            }}
          >
            <Bookmark size={16} /> 保存为模板
          </button>
          <button
            className="btn btn-outline"
            onClick={handleCompare}
            disabled={compareSelection.length !== 2 || loading}
          >
            <GitCompare size={16} /> 对比所选版本
            {compareSelection.length > 0 && ` (${compareSelection.length}/2)`}
          </button>
        </div>

        <div className="card" style={{ marginBottom: 16 }}>
          <div className="card-title">课题需求</div>
          <p style={{ fontSize: 14, color: 'var(--text-secondary)' }}>{selectedTopic.user_input}</p>
        </div>

        {loading ? (
          <div className="empty-state"><Loader size={32} className="spinner" /></div>
        ) : versions.length === 0 ? (
          <div className="empty-state"><History size={48} /><p>暂无版本</p></div>
        ) : (
          <div className="version-list">
            {versions.map((ver: VersionRecord) => (
              <div key={ver.id} className={`version-item ${ver.is_best ? 'is-best' : ''}`}>
                <label className="version-checkbox" onClick={e => e.stopPropagation()}>
                  <input
                    type="checkbox"
                    checked={compareSelection.includes(ver.id)}
                    onChange={() => toggleCompareSelect(ver.id)}
                  />
                </label>
                <div className="version-info" onClick={() => openRecord(ver.id)}>
                  <div className="version-title-row">
                    <span className="version-number">v{ver.version_number}</span>
                    <span>{ver.title}</span>
                    {ver.is_best && (
                      <span className="best-badge"><Star size={12} /> 当前最佳</span>
                    )}
                    {ver.partial && (
                      <span className="partial-badge"><AlertTriangle size={12} /> 部分结果</span>
                    )}
                  </div>
                  <div className="history-meta">
                    {ver.task_count} 个任务 · {new Date(ver.created_at).toLocaleString('zh-CN')}
                  </div>
                </div>
                <div className="version-actions">
                  {!ver.is_best && (
                    <button
                      className="btn btn-outline btn-sm"
                      onClick={() => handleMarkBest(ver.id)}
                      title="标记为当前最佳版本"
                    >
                      <Star size={14} /> 设为最佳
                    </button>
                  )}
                  <button className="btn btn-outline btn-sm" onClick={() => openRecord(ver.id)}>
                    查看
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </>
    )
  }

  return (
    <>
      <h2 className="page-title">历史方案</h2>
      <p className="page-desc">按课题管理多个方案版本，支持对比差异与标记最佳版本。</p>

      <div className="history-search">
        <Search size={18} className="history-search-icon" />
        <input
          className="form-input history-search-input"
          type="search"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="搜索课题标题或需求描述..."
        />
        {searching && <Loader size={16} className="history-search-loading" />}
      </div>

      {topics.length === 0 ? (
        <div className="empty-state">
          <History size={48} />
          <p>{searchQuery.trim() ? '未找到匹配的课题' : '暂无历史记录'}</p>
        </div>
      ) : (
        <div className="history-list">
          {topics.map((topic: TopicRecord) => (
            <div key={topic.id} className="history-item topic-item" onClick={() => openTopic(topic)}>
              <div>
                <div style={{ fontWeight: 500, fontSize: 14, display: 'flex', alignItems: 'center', gap: 8 }}>
                  {topic.title}
                  <span className="version-count-badge">{topic.version_count} 版</span>
                  {topic.best_record_id && (
                    <span className="best-badge small"><Star size={10} /> 已标记最佳</span>
                  )}
                </div>
                <div className="history-meta">
                  {topic.scenario} · 更新于 {new Date(topic.updated_at).toLocaleString('zh-CN')}
                </div>
                {topic.user_input && (
                  <div className="history-preview">{topic.user_input}</div>
                )}
              </div>
              <span className="status-badge completed">查看版本</span>
            </div>
          ))}
        </div>
      )}
    </>
  )
}
