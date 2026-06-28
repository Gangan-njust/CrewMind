import { useState, useEffect, useMemo, useRef } from 'react'
import {
  CheckCircle, Clock, AlertTriangle, XCircle, Loader, Pause,
  ChevronDown, ChevronUp, GitBranch, List,
} from 'lucide-react'
import ReactMarkdown from 'react-markdown'

export interface VizTask {
  id: string
  name: string
  agent_id: string
  depends_on: string[]
  requires_human_review?: boolean
}

export interface VizAgent {
  id: string
  name: string
}

export interface VizTaskResult {
  status: string
  output: string
  error: string
  human_feedback?: string
  metadata?: Record<string, unknown>
}

const STATUS_LABEL: Record<string, string> = {
  pending: '等待中',
  running: '执行中',
  completed: '已完成',
  waiting_human: '待审核',
  suspended: '已中止',
  failed: '失败',
  skipped: '已跳过',
}

const AGENT_COLORS: Record<string, string> = {
  planner: '#6c5ce7',
  literature_researcher: '#0984e3',
  experiment_designer: '#00b894',
  resource_analyst: '#e6a817',
  review_specialist: '#e17055',
  cs_journal_reviewer: '#fd79a8',
  bio_journal_reviewer: '#55efc4',
  material_journal_reviewer: '#74b9ff',
}

function agentColor(agentId: string): string {
  return AGENT_COLORS[agentId] || '#a29bfe'
}

function getActiveTaskId(tasks: VizTask[], results: Record<string, VizTaskResult>): string | null {
  for (const s of ['running', 'waiting_human', 'suspended'] as const) {
    const found = tasks.find(t => results[t.id]?.status === s)
    if (found) return found.id
  }
  return null
}

function StatusIcon({ status, size = 16 }: { status: string; size?: number }) {
  switch (status) {
    case 'running': return <Loader size={size} className="spinner" />
    case 'completed': return <CheckCircle size={size} color="#00b894" />
    case 'waiting_human': return <AlertTriangle size={size} color="#fdcb6e" />
    case 'suspended': return <Pause size={size} color="#e17055" />
    case 'failed': return <XCircle size={size} color="#e17055" />
    default: return <Clock size={size} color="#6b7194" />
  }
}

/* ── DAG Layout ─────────────────────────────────────────────── */

const NODE_W = 148
const NODE_H = 72
const COL_GAP = 56
const ROW_GAP = 20
const PAD = 24

interface DagLayout {
  positions: Map<string, { x: number; y: number }>
  width: number
  height: number
}

function computeDagLayout(tasks: VizTask[]): DagLayout {
  const layers = new Map<string, number>()

  function layerOf(id: string): number {
    if (layers.has(id)) return layers.get(id)!
    const task = tasks.find(t => t.id === id)
    if (!task || task.depends_on.length === 0) {
      layers.set(id, 0)
      return 0
    }
    const maxDep = Math.max(...task.depends_on.map(layerOf))
    layers.set(id, maxDep + 1)
    return maxDep + 1
  }

  tasks.forEach(t => layerOf(t.id))

  const byLayer: string[][] = []
  tasks.forEach(t => {
    const l = layers.get(t.id)!
    while (byLayer.length <= l) byLayer.push([])
    byLayer[l].push(t.id)
  })

  const positions = new Map<string, { x: number; y: number }>()
  let maxH = 0

  byLayer.forEach((ids, col) => {
    const colH = ids.length * NODE_H + (ids.length - 1) * ROW_GAP
    maxH = Math.max(maxH, colH)
  })

  byLayer.forEach((ids, col) => {
    const colH = ids.length * NODE_H + (ids.length - 1) * ROW_GAP
    const startY = PAD + (maxH - colH) / 2
    ids.forEach((id, row) => {
      positions.set(id, {
        x: PAD + col * (NODE_W + COL_GAP),
        y: startY + row * (NODE_H + ROW_GAP),
      })
    })
  })

  const width = PAD * 2 + byLayer.length * NODE_W + Math.max(0, byLayer.length - 1) * COL_GAP
  const height = PAD * 2 + maxH

  return { positions, width, height }
}

/* ── Task DAG Graph ─────────────────────────────────────────── */

function TaskDAGGraph({
  tasks,
  agents,
  results,
  activeTaskId,
  onNodeClick,
}: {
  tasks: VizTask[]
  agents: VizAgent[]
  results: Record<string, VizTaskResult>
  activeTaskId: string | null
  onNodeClick?: (taskId: string) => void
}) {
  const layout = useMemo(() => computeDagLayout(tasks), [tasks])
  const agentName = (id: string) => agents.find(a => a.id === id)?.name || id

  const edges = useMemo(() => {
    const list: { from: string; to: string }[] = []
    tasks.forEach(t => {
      t.depends_on.forEach(dep => {
        if (tasks.some(x => x.id === dep)) {
          list.push({ from: dep, to: t.id })
        }
      })
    })
    return list
  }, [tasks])

  function edgePath(fromId: string, toId: string): string {
    const from = layout.positions.get(fromId)
    const to = layout.positions.get(toId)
    if (!from || !to) return ''
    const x1 = from.x + NODE_W
    const y1 = from.y + NODE_H / 2
    const x2 = to.x
    const y2 = to.y + NODE_H / 2
    const midX = (x1 + x2) / 2
    return `M ${x1} ${y1} C ${midX} ${y1}, ${midX} ${y2}, ${x2} ${y2}`
  }

  if (tasks.length === 0) return null

  return (
    <div className="dag-container">
      <svg
        className="dag-svg"
        width={layout.width}
        height={layout.height}
        viewBox={`0 0 ${layout.width} ${layout.height}`}
      >
        <defs>
          <marker
            id="dag-arrow"
            markerWidth="8"
            markerHeight="8"
            refX="6"
            refY="4"
            orient="auto"
          >
            <path d="M0,0 L8,4 L0,8 Z" fill="var(--text-muted)" />
          </marker>
        </defs>

        {edges.map(({ from, to }) => {
          const toStatus = results[to]?.status || 'pending'
          const isActiveEdge = activeTaskId === to || (results[from]?.status === 'completed' && toStatus === 'running')
          return (
            <path
              key={`${from}-${to}`}
              d={edgePath(from, to)}
              className={`dag-edge ${isActiveEdge ? 'active' : ''}`}
              fill="none"
              markerEnd="url(#dag-arrow)"
            />
          )
        })}

        {tasks.map(task => {
          const pos = layout.positions.get(task.id)
          if (!pos) return null
          const status = results[task.id]?.status || 'pending'
          const isActive = task.id === activeTaskId
          const color = agentColor(task.agent_id)

          return (
            <g
              key={task.id}
              className={`dag-node-group ${isActive ? 'active' : ''} ${status}`}
              transform={`translate(${pos.x}, ${pos.y})`}
              onClick={() => onNodeClick?.(task.id)}
              style={{ cursor: onNodeClick ? 'pointer' : undefined }}
            >
              <rect
                className="dag-node-bg"
                width={NODE_W}
                height={NODE_H}
                rx={10}
                style={{ stroke: isActive ? color : undefined }}
              />
              <circle cx={14} cy={14} r={5} fill={color} />
              <text x={26} y={18} className="dag-node-agent">{agentName(task.agent_id)}</text>
              <text x={14} y={40} className="dag-node-title">{task.name}</text>
              <foreignObject x={NODE_W - 28} y={8} width={20} height={20}>
                <div className="dag-node-icon">
                  <StatusIcon status={status} size={14} />
                </div>
              </foreignObject>
              <text x={14} y={58} className={`dag-node-status status-${status}`}>
                {STATUS_LABEL[status] || status}
              </text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}

/* ── Collapsible Task Output Card ───────────────────────────── */

function TaskOutputCard({
  task,
  agentName,
  result,
  isActive,
  expanded,
  onToggle,
  reviewPanel,
}: {
  task: VizTask
  agentName: string
  result?: VizTaskResult
  isActive: boolean
  expanded: boolean
  onToggle: () => void
  reviewPanel?: React.ReactNode
}) {
  const status = result?.status || 'pending'
  const hasContent = !!(result?.output || result?.error || status === 'running' || status === 'suspended')
  const color = agentColor(task.agent_id)

  return (
    <div
      id={`task-card-${task.id}`}
      className={`task-output-card ${status} ${isActive ? 'active' : ''}`}
      style={{ '--agent-color': color } as React.CSSProperties}
    >
      <button
        type="button"
        className="task-output-header"
        onClick={onToggle}
        aria-expanded={expanded ? 'true' : 'false'}
      >
        <div className="task-output-header-left">
          <div className={`task-output-dot ${status}`}>
            <StatusIcon status={status} size={14} />
          </div>
          <div>
            <div className="task-output-title">
              {task.name}
              {isActive && <span className="active-agent-badge">当前活跃</span>}
            </div>
            <div className="task-output-meta">
              <span className="task-output-agent" style={{ color }}>{agentName}</span>
              {task.requires_human_review && <span> · 需人工审核</span>}
            </div>
          </div>
        </div>
        <div className="task-output-header-right">
          <span className={`status-badge ${status}`}>{STATUS_LABEL[status] || status}</span>
          {hasContent && (
            expanded ? <ChevronUp size={18} /> : <ChevronDown size={18} />
          )}
        </div>
      </button>

      {expanded && (
        <div className="task-output-body">
          {result?.output ? (
            <div className="markdown-output">
              <ReactMarkdown>{result.output}</ReactMarkdown>
            </div>
          ) : (status === 'running' || status === 'suspended') ? (
            <div className="task-output-placeholder">
              {status === 'suspended' ? '任务已中止，输出保留如下' : '正在生成...'}
            </div>
          ) : status === 'pending' ? (
            <div className="task-output-placeholder">等待前序任务完成...</div>
          ) : null}

          {result?.error && (
            <div className="task-output-error">错误: {result.error}</div>
          )}

          {reviewPanel}
        </div>
      )}
    </div>
  )
}

/* ── Main Export ────────────────────────────────────────────── */

type ViewMode = 'all' | 'dag' | 'timeline'

export function WorkflowVisualization({
  tasks,
  agents,
  results,
  collaborationMode = 'sequential',
  reviewTaskId,
  reviewFeedback,
  onReviewFeedbackChange,
  onReview,
}: {
  tasks: VizTask[]
  agents: VizAgent[]
  results: Record<string, VizTaskResult>
  collaborationMode?: 'sequential' | 'debate' | 'voting'
  reviewTaskId?: string
  reviewFeedback?: string
  onReviewFeedbackChange?: (v: string) => void
  onReview?: (approved: boolean) => void
}) {
  const [viewMode, setViewMode] = useState<ViewMode>('all')
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [userToggled, setUserToggled] = useState<Record<string, boolean>>({})
  const timelineRef = useRef<HTMLDivElement>(null)

  const activeTaskId = useMemo(() => getActiveTaskId(tasks, results), [tasks, results])
  const agentName = (id: string) => agents.find(a => a.id === id)?.name || id

  useEffect(() => {
    setExpanded(prev => {
      const next = { ...prev }
      tasks.forEach(task => {
        if (userToggled[task.id]) return
        const status = results[task.id]?.status || 'pending'
        next[task.id] = ['running', 'waiting_human', 'suspended'].includes(status)
      })
      return next
    })
  }, [tasks, results, userToggled])

  const toggleExpand = (taskId: string) => {
    setUserToggled(prev => ({ ...prev, [taskId]: true }))
    setExpanded(prev => ({ ...prev, [taskId]: !prev[taskId] }))
  }

  const scrollToTask = (taskId: string) => {
    setExpanded(prev => ({ ...prev, [taskId]: true }))
    setTimeout(() => {
      document.getElementById(`task-card-${taskId}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }, 50)
  }

  const modeDesc: Record<string, string> = {
    sequential: '各 Agent 按依赖顺序依次执行',
    debate: '正方提出方案 → 反方质疑 → 正方修订 → 裁判评估，多轮迭代',
    voting: '多个求解者并行独立生成方案，聚合者评审选出最优',
  }

  return (
    <div className="workflow-viz">
      {collaborationMode !== 'sequential' && (
        <div className={`collaboration-mode-info ${collaborationMode}`}>
          {collaborationMode === 'debate' ? '辩论模式' : '投票模式'}：{modeDesc[collaborationMode]}
        </div>
      )}
      <div className="workflow-viz-toolbar">
        <div className="view-mode-toggle">
          <button
            type="button"
            className={`view-mode-btn ${viewMode === 'all' ? 'active' : ''}`}
            onClick={() => setViewMode('all')}
          >
            全部
          </button>
          <button
            type="button"
            className={`view-mode-btn ${viewMode === 'dag' ? 'active' : ''}`}
            onClick={() => setViewMode('dag')}
          >
            <GitBranch size={14} /> 依赖图
          </button>
          <button
            type="button"
            className={`view-mode-btn ${viewMode === 'timeline' ? 'active' : ''}`}
            onClick={() => setViewMode('timeline')}
          >
            <List size={14} /> 时间线
          </button>
        </div>
      </div>

      {(viewMode === 'all' || viewMode === 'dag') && (
        <section className="viz-section">
          <h3 className="viz-section-title">任务依赖关系 (DAG)</h3>
          <p className="viz-section-desc">箭头指向下游任务；点击节点可定位到对应输出卡片</p>
          <TaskDAGGraph
            tasks={tasks}
            agents={agents}
            results={results}
            activeTaskId={activeTaskId}
            onNodeClick={scrollToTask}
          />
        </section>
      )}

      {(viewMode === 'all' || viewMode === 'timeline') && (
        <section className="viz-section" ref={timelineRef}>
          <h3 className="viz-section-title">Agent 输出</h3>
          <div className="task-output-list">
            {tasks.map(task => {
              const result = results[task.id]
              const status = result?.status || 'pending'
              const isReview = status === 'waiting_human' && task.id === reviewTaskId

              return (
                <TaskOutputCard
                  key={task.id}
                  task={task}
                  agentName={agentName(task.agent_id)}
                  result={result}
                  isActive={task.id === activeTaskId}
                  expanded={expanded[task.id] ?? false}
                  onToggle={() => toggleExpand(task.id)}
                  reviewPanel={isReview && onReview ? (
                    <div className="review-panel">
                      <h4>人工审核</h4>
                      <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 8 }}>
                        请审核上述输出，可以输入修改意见后批准，或直接驳回。
                      </p>
                      <textarea
                        className="form-textarea"
                        placeholder="输入审核意见或修改建议（可选）..."
                        value={reviewFeedback || ''}
                        onChange={e => onReviewFeedbackChange?.(e.target.value)}
                        rows={3}
                      />
                      <div className="review-actions">
                        <button type="button" className="btn btn-success" onClick={() => onReview(true)}>
                          <CheckCircle size={16} /> 批准并继续
                        </button>
                        <button type="button" className="btn btn-danger" onClick={() => onReview(false)}>
                          <XCircle size={16} /> 驳回
                        </button>
                      </div>
                    </div>
                  ) : undefined}
                />
              )
            })}
          </div>
        </section>
      )}
    </div>
  )
}
