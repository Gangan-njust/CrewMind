import { useCallback, useEffect, useRef, useState } from 'react'
import {
  BookOpen, Plus, Trash2, Upload, Search, CheckSquare, Square,
  Loader, X, Copy, FileText, Sparkles, ChevronRight, Bookmark, Check,
} from 'lucide-react'
import {
  fetchWorkspaces, createWorkspace, updateWorkspace, deleteWorkspace,
  fetchLiteratures, uploadLiteratures, deleteLiterature,
  analyzeLiteratures, filterLiteratures, selectLiteratures,
  fetchSelectedLiteratures, saveSelectionTemplate,
  connectLiteratureWebSocket, startProposalFromLiterature,
  updateLiteratureAnalysis, fetchAgents, fetchScenarios,
  type Workspace, type Literature, type AnalysisProgress, type DataSourceMode,
  type Agent, type Scenario,
} from '../api'
import { FormulaBlock } from './FormulaBlock'

const STATUS_LABELS: Record<string, string> = {
  pending: '待分析',
  processing: '分析中',
  done: '已完成',
  failed: '失败',
}

const PROPOSAL_SCENARIO_ID = 'literature_based_proposal'

function defaultProposalAgents(scenario: Scenario | null, agents: Agent[]): string[] {
  if (!scenario) return []
  const inScenario = new Set(scenario.agents.map(a => a.id))
  return agents
    .filter(a => inScenario.has(a.id) && a.category !== 'domain_review')
    .map(a => a.id)
}

interface Props {
  onStartWorkflow: (crewId: string) => void
}

export function LiteratureAssistant({ onStartWorkflow }: Props) {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [activeWorkspace, setActiveWorkspace] = useState<Workspace | null>(null)
  const [literatures, setLiteratures] = useState<Literature[]>([])
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [checkedIds, setCheckedIds] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [progress, setProgress] = useState<AnalysisProgress | null>(null)
  const [keyword, setKeyword] = useState('')
  const [sortBy, setSortBy] = useState('uploaded_at')
  const [detailLit, setDetailLit] = useState<Literature | null>(null)
  const [showCreateWs, setShowCreateWs] = useState(false)
  const [showProposal, setShowProposal] = useState(false)
  const [wsForm, setWsForm] = useState({ name: '', description: '' })
  const [proposalForm, setProposalForm] = useState({
    mode: 'library_first' as DataSourceMode,
    topic: '',
    additional: '',
  })
  const [agents, setAgents] = useState<Agent[]>([])
  const [proposalScenario, setProposalScenario] = useState<Scenario | null>(null)
  const [proposalSelectedAgents, setProposalSelectedAgents] = useState<string[]>([])
  const [error, setError] = useState('')
  const [dragOver, setDragOver] = useState(false)
  const [toast, setToast] = useState('')
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null)
  const [debouncedKeyword, setDebouncedKeyword] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const toastTimer = useRef<ReturnType<typeof setTimeout>>()

  const showToast = useCallback((msg: string) => {
    setToast(msg)
    if (toastTimer.current) clearTimeout(toastTimer.current)
    toastTimer.current = setTimeout(() => setToast(''), 2200)
  }, [])

  const loadWorkspaces = useCallback(async () => {
    try {
      const data = await fetchWorkspaces()
      setWorkspaces(data)
    } catch (e: any) {
      setError(e.message)
    }
  }, [])

  const loadLiteratures = useCallback(async (wsId: string, kw?: string) => {
    setLoading(true)
    try {
      const data = kw
        ? await filterLiteratures(wsId, { keyword: kw, sort_by: sortBy })
        : await fetchLiteratures(wsId)
      setLiteratures(data)
      const sel = await fetchSelectedLiteratures(wsId)
      setSelectedIds(sel.selected_literature_ids)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [sortBy])

  useEffect(() => { loadWorkspaces() }, [loadWorkspaces])

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedKeyword(keyword), 300)
    return () => clearTimeout(timer)
  }, [keyword])

  useEffect(() => {
    if (!activeWorkspace) return
    loadLiteratures(activeWorkspace.id, debouncedKeyword || undefined)
    wsRef.current?.close()
    wsRef.current = connectLiteratureWebSocket(activeWorkspace.id, (msg) => {
      if (msg.type === 'literature_analysis_progress' || msg.total !== undefined) {
        setProgress(msg as AnalysisProgress)
        if (msg.status === 'completed') {
          loadLiteratures(activeWorkspace.id, debouncedKeyword || undefined)
          showToast('文献分析已完成')
        }
      }
    })
    return () => { wsRef.current?.close() }
  }, [activeWorkspace, loadLiteratures, debouncedKeyword, showToast])

  useEffect(() => {
    if (!activeWorkspace) return
    fetchAgents().then(setAgents).catch(() => {})
    fetchScenarios()
      .then(scenarios => setProposalScenario(
        scenarios.find(s => s.id === PROPOSAL_SCENARIO_ID) || null
      ))
      .catch(() => {})
  }, [activeWorkspace])

  useEffect(() => {
    if (!detailLit) return
    const updated = literatures.find(l => l.id === detailLit.id)
    if (updated) setDetailLit(updated)
  }, [literatures]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (detailLit) setDetailLit(null)
        else if (showProposal) setShowProposal(false)
        else if (showCreateWs) setShowCreateWs(false)
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [detailLit, showProposal, showCreateWs])

  const handleCreateWorkspace = async () => {
    if (!wsForm.name.trim()) return
    try {
      const ws = await createWorkspace(wsForm.name, wsForm.description)
      setWorkspaces(prev => [ws, ...prev])
      setActiveWorkspace(ws)
      setShowCreateWs(false)
      setWsForm({ name: '', description: '' })
    } catch (e: any) {
      setError(e.message)
    }
  }

  const handleUpload = async (files: FileList | null) => {
    if (!activeWorkspace || !files?.length) return
    setUploading(true)
    try {
      await uploadLiteratures(activeWorkspace.id, Array.from(files))
      await loadLiteratures(activeWorkspace.id)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setUploading(false)
    }
  }

  const handleAnalyze = async (ids?: string[]) => {
    if (!activeWorkspace) return
    const target = ids ?? Array.from(checkedIds)
    try {
      await analyzeLiteratures(activeWorkspace.id, target.length ? target : [], activeWorkspace.name)
    } catch (e: any) {
      setError(e.message)
    }
  }

  const toggleCheck = (id: string) => {
    setCheckedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleSelect = async (id: string) => {
    if (!activeWorkspace) return
    const next = selectedIds.includes(id)
      ? selectedIds.filter(i => i !== id)
      : [...selectedIds, id]
    try {
      const ids = await selectLiteratures(activeWorkspace.id, next)
      setSelectedIds(ids)
    } catch (e: any) {
      setError(e.message)
    }
  }

  const selectAllVisible = async () => {
    if (!activeWorkspace) return
    const ids = literatures.map(l => l.id)
    const merged = Array.from(new Set([...selectedIds, ...ids]))
    const result = await selectLiteratures(activeWorkspace.id, merged)
    setSelectedIds(result)
  }

  const clearAllSelected = async () => {
    if (!activeWorkspace) return
    const result = await selectLiteratures(activeWorkspace.id, [])
    setSelectedIds(result)
  }

  const proposalTopic = (proposalForm.topic || activeWorkspace?.name || '').trim()
  const proposalTopicValid = proposalTopic.length >= 5
  const proposalScenarioAgentIds = new Set(proposalScenario?.agents.map(a => a.id) || [])
  const canStartProposal = proposalSelectedAgents.length > 0 && selectedIds.length > 0 && proposalTopicValid

  const toggleProposalAgent = (agentId: string) => {
    setProposalSelectedAgents(prev =>
      prev.includes(agentId)
        ? prev.filter(id => id !== agentId)
        : [...prev, agentId]
    )
  }

  const handleProposal = async () => {
    if (!activeWorkspace || !canStartProposal) return
    if (!proposalTopicValid) {
      setError('研究主题至少需要 5 个字符，请填写完整后再提交')
      return
    }
    setError('')
    try {
      const res = await startProposalFromLiterature({
        workspace_id: activeWorkspace.id,
        literature_ids: selectedIds,
        mode: proposalForm.mode,
        topic: proposalTopic,
        additional_requirements: proposalForm.additional.trim(),
        selected_agents: proposalSelectedAgents,
      })
      setShowProposal(false)
      onStartWorkflow(res.crew_id)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '启动开题报告生成失败')
    }
  }

  const copyText = async (text: string, idx?: number) => {
    try {
      await navigator.clipboard.writeText(text)
      showToast('已复制到剪贴板')
      if (idx !== undefined) {
        setCopiedIdx(idx)
        setTimeout(() => setCopiedIdx(null), 1500)
      }
    } catch {
      showToast('复制失败，请手动复制')
    }
  }

  const statusClass = (status: string) => {
    if (status === 'done') return 'status-done'
    if (status === 'processing') return 'status-running'
    if (status === 'failed') return 'status-failed'
    return 'status-pending'
  }

  const openProposalModal = async () => {
    setProposalForm(f => ({ ...f, topic: activeWorkspace?.name || '' }))
    try {
      let agentList = agents
      let scenario = proposalScenario
      if (!agentList.length) {
        agentList = await fetchAgents()
        setAgents(agentList)
      }
      if (!scenario) {
        const scenarios = await fetchScenarios()
        scenario = scenarios.find(s => s.id === PROPOSAL_SCENARIO_ID) || null
        setProposalScenario(scenario)
      }
      setProposalSelectedAgents(defaultProposalAgents(scenario, agentList))
    } catch {
      setProposalSelectedAgents([])
    }
    setShowProposal(true)
  }

  const renderAnalysisDetail = (lit: Literature) => (
    <>
      <div className="meta-section">
        <p><strong>作者：</strong>{lit.authors.join(', ') || '未知'}</p>
        <p><strong>期刊：</strong>{lit.journal || '—'} · {lit.year || '—'}</p>
        <p><strong>DOI：</strong>{lit.doi || '—'}</p>
        {lit.abstract && <p><strong>摘要：</strong>{lit.abstract}</p>}
      </div>

      {lit.analysis ? (
        <>
          <div className="analysis-card">
            <h4>标签</h4>
            <div className="tag-list">
              {lit.analysis.tags.map((t, i) => (
                <span key={i} className="tag">{t}</span>
              ))}
            </div>
          </div>
          <div className="analysis-card">
            <h4>核心贡献</h4>
            <p>{lit.analysis.contribution_summary}</p>
          </div>
          <div className="analysis-card">
            <h4>研究背景与目标</h4>
            <p>{lit.analysis.research_background}</p>
            <p>{lit.analysis.research_goal}</p>
          </div>
          <div className="analysis-card">
            <h4>方法与主要发现</h4>
            <p>{lit.analysis.methods_summary}</p>
            <ul>{lit.analysis.key_findings.map((f, i) => <li key={i}>{f}</li>)}</ul>
          </div>
          <div className="analysis-card">
            <h4>关键公式</h4>
            {lit.analysis.formulas && lit.analysis.formulas.length > 0 ? (
              <div className="formula-list">
                {lit.analysis.formulas.map((f, i) => (
                  <FormulaBlock key={i} formula={f} />
                ))}
              </div>
            ) : (
              <p className="text-muted">
                暂无公式提取结果。请重新执行「批量分析」以获取公式及详细解释。
              </p>
            )}
          </div>
          <div className="analysis-card">
            <h4>局限性</h4>
            <ul>{lit.analysis.limitations.map((l, i) => <li key={i}>{l}</li>)}</ul>
          </div>
          <div className="analysis-card">
            <h4>待引语句式</h4>
            {lit.analysis.citation_templates.map((c, i) => (
              <div key={i} className="citation-item">
                <p>{c.zh}</p>
                <p className="text-muted">{c.en}</p>
                <button
                  className={`btn btn-sm btn-outline${copiedIdx === i ? ' btn-copied' : ''}`}
                  onClick={() => copyText(c.zh || c.en || '', i)}
                >
                  {copiedIdx === i ? <Check size={12} /> : <Copy size={12} />}
                  {copiedIdx === i ? '已复制' : '复制'}
                </button>
              </div>
            ))}
          </div>
        </>
      ) : (
        <div className="empty-state">
          <p>尚未分析</p>
          <button className="btn btn-primary btn-sm"
            onClick={() => handleAnalyze([lit.id])}>开始分析</button>
        </div>
      )}
    </>
  )

  const progressPct = progress && progress.total
    ? Math.round((progress.completed / progress.total) * 100)
    : 0

  const toastEl = toast ? (
    <div className="toast-container"><div className="toast">{toast}</div></div>
  ) : null

  if (!activeWorkspace) {
    return (
      <div className="literature-page">
        {toastEl}
        <div className="page-header">
          <h2><BookOpen size={24} /> 智能文献阅读助手</h2>
          <button className="btn btn-primary" onClick={() => setShowCreateWs(true)}>
            <Plus size={16} /> 新建工作空间
          </button>
        </div>

        {error && <div className="error-banner">{error}<button onClick={() => setError('')}><X size={14} /></button></div>}

        <div className="workspace-grid">
          {workspaces.map(ws => (
            <div key={ws.id} className="card workspace-card" onClick={() => setActiveWorkspace(ws)}>
              <h3>{ws.name}</h3>
              <p className="text-muted">{ws.description || '暂无描述'}</p>
              <div className="workspace-meta">
                <span>{ws.literature_count} 篇文献</span>
                <span>{new Date(ws.created_at).toLocaleDateString()}</span>
              </div>
              <div className="workspace-actions" onClick={e => e.stopPropagation()}>
                <button className="btn btn-sm" onClick={() => { setWsForm({ name: ws.name, description: ws.description }); setActiveWorkspace(ws) }}>
                  打开
                </button>
                <button className="btn btn-sm btn-danger" onClick={async () => {
                  if (confirm('确定删除此工作空间？')) {
                    await deleteWorkspace(ws.id)
                    loadWorkspaces()
                  }
                }}>
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          ))}
          {workspaces.length === 0 && (
            <div className="empty-state card">
              <BookOpen size={48} color="var(--text-muted)" />
              <p>创建第一个文献工作空间，开始上传与分析 PDF 文献</p>
            </div>
          )}
        </div>

        {showCreateWs && (
          <div className="modal-overlay" onClick={() => setShowCreateWs(false)}>
            <div className="modal-card" onClick={e => e.stopPropagation()}>
              <div className="modal-header">
                <h3>新建工作空间</h3>
                <button className="icon-btn" onClick={() => setShowCreateWs(false)}><X size={18} /></button>
              </div>
              <div className="form-group">
                <label className="form-label">名称</label>
                <input className="form-input" value={wsForm.name} onChange={e => setWsForm(f => ({ ...f, name: e.target.value }))} placeholder="如：深度学习综述文献库" autoFocus />
              </div>
              <div className="form-group">
                <label className="form-label">描述</label>
                <textarea className="form-textarea" value={wsForm.description} onChange={e => setWsForm(f => ({ ...f, description: e.target.value }))} rows={3} placeholder="简要描述该文献库的用途（可选）" />
              </div>
              <div className="form-actions">
                <button className="btn btn-primary" onClick={handleCreateWorkspace} disabled={!wsForm.name.trim()}>创建</button>
                <button className="btn btn-outline" onClick={() => setShowCreateWs(false)}>取消</button>
              </div>
            </div>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="literature-page literature-detail">
      {toastEl}
      {!detailLit && (
      <div className="page-header">
        <button className="btn btn-outline btn-sm" onClick={() => setActiveWorkspace(null)}>
          <ChevronRight size={16} style={{ transform: 'rotate(180deg)' }} /> 返回
        </button>
        <h2>{activeWorkspace.name}</h2>
        {progress && progress.status === 'running' && (
          <span className="progress-badge">
            <Loader size={14} className="spinner" />
            {progress.completed}/{progress.total} 已完成
            <div className="analysis-progress-bar">
              <div className="analysis-progress-fill" style={{ width: `${progressPct}%` }} />
            </div>
          </span>
        )}
      </div>
      )}

      {error && <div className="error-banner">{error}<button onClick={() => setError('')}><X size={14} /></button></div>}

      {detailLit ? (
        <div className="literature-analysis-view">
          <div className="analysis-view-header">
            <button className="btn btn-outline btn-sm" onClick={() => setDetailLit(null)}>
              <ChevronRight size={16} style={{ transform: 'rotate(180deg)' }} /> 返回文献列表
            </button>
            <h2 className="analysis-view-title">{detailLit.title}</h2>
            <span className={`status-tag ${statusClass(detailLit.status)}`}>
              {STATUS_LABELS[detailLit.status]}
            </span>
          </div>
          <div className="analysis-view-body card">
            {renderAnalysisDetail(detailLit)}
          </div>
        </div>
      ) : (
      <div className="literature-layout">
        <div className="literature-main">
          {/* 上传区 */}
          <div
            className={`upload-zone card${dragOver ? ' drag-over' : ''}`}
            onDragOver={e => { e.preventDefault(); setDragOver(true) }}
            onDragLeave={() => setDragOver(false)}
            onDrop={e => { e.preventDefault(); setDragOver(false); handleUpload(e.dataTransfer.files) }}
            onClick={() => fileRef.current?.click()}
          >
            <input ref={fileRef} type="file" accept=".pdf" multiple hidden
              onChange={e => handleUpload(e.target.files)} />
            {uploading ? <Loader className="spinner" size={32} /> : <Upload size={32} />}
            <p>{uploading ? '正在上传...' : '拖拽 PDF 到此处，或点击选择（支持批量）'}</p>
          </div>

          {/* 筛选栏 */}
          <div className="filter-bar card">
            <Search size={16} />
            <input className="form-input" placeholder="搜索标题、摘要、作者..." value={keyword}
              onChange={e => setKeyword(e.target.value)} />
            <select className="form-input" style={{ width: 'auto', flex: 'none' }} value={sortBy} onChange={e => setSortBy(e.target.value)}>
              <option value="uploaded_at">上传时间</option>
              <option value="relevance_score">匹配度</option>
              <option value="year">年份</option>
            </select>
            <button className="btn btn-outline btn-sm" onClick={() => loadLiteratures(activeWorkspace.id, keyword)}>
              刷新
            </button>
          </div>

          {/* 批量操作 + 选定 / 开题报告 */}
          <div className="batch-bar card">
            <div className="batch-bar-group">
              <button className="btn btn-sm btn-outline" onClick={() => {
                if (checkedIds.size === literatures.length) setCheckedIds(new Set())
                else setCheckedIds(new Set(literatures.map(l => l.id)))
              }}>
                {checkedIds.size === literatures.length && literatures.length > 0
                  ? <CheckSquare size={14} /> : <Square size={14} />}
                全选
              </button>
              <button className="btn btn-sm btn-primary" onClick={() => handleAnalyze()}>
                <Sparkles size={14} /> 批量分析 {checkedIds.size ? `(${checkedIds.size})` : '(全部待分析)'}
              </button>
            </div>
            <div className="batch-bar-divider" />
            <div className="batch-bar-group batch-bar-selection">
              <span className="selected-count-badge">已选定 {selectedIds.length} 篇</span>
              <button className="btn btn-sm btn-outline" onClick={selectAllVisible}>全部选定</button>
              <button className="btn btn-sm btn-outline" onClick={clearAllSelected} disabled={!selectedIds.length}>清空</button>
              <button className="btn btn-sm btn-outline" onClick={async () => {
                const name = prompt('模板名称')
                if (name) await saveSelectionTemplate(activeWorkspace.id, name, selectedIds)
              }}>
                <Bookmark size={14} /> 保存模板
              </button>
              <button className="btn btn-sm btn-primary" disabled={!selectedIds.length} onClick={openProposalModal}>
                <Sparkles size={14} /> 生成开题报告
              </button>
            </div>
          </div>

          {selectedIds.length > 0 && (
            <div className="selected-chips card">
              {literatures.filter(l => selectedIds.includes(l.id)).map(l => (
                <span key={l.id} className="selected-chip">
                  {l.title.length > 36 ? `${l.title.slice(0, 36)}…` : l.title}
                  <button type="button" className="chip-remove" onClick={() => toggleSelect(l.id)} title="移除">
                    <X size={12} />
                  </button>
                </span>
              ))}
            </div>
          )}

          {/* 文献列表 */}
          {loading ? (
            <div className="loading-center"><Loader className="spinner" size={32} /></div>
          ) : (
            <div className="literature-table card">
              <table>
                <thead>
                  <tr>
                    <th></th>
                    <th>标题</th>
                    <th>作者</th>
                    <th>期刊</th>
                    <th>年份</th>
                    <th>状态</th>
                    <th>匹配度</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {literatures.map(lit => (
                    <tr
                      key={lit.id}
                      className={selectedIds.includes(lit.id) ? 'row-selected' : ''}
                    >
                      <td>
                        <input type="checkbox" checked={checkedIds.has(lit.id)}
                          onChange={() => toggleCheck(lit.id)} />
                      </td>
                      <td className="title-cell" onClick={() => setDetailLit(lit)}>{lit.title}</td>
                      <td>{lit.authors.slice(0, 2).join(', ')}{lit.authors.length > 2 ? ' 等' : ''}</td>
                      <td>{lit.journal || '—'}</td>
                      <td>{lit.year || '—'}</td>
                      <td><span className={`status-tag ${statusClass(lit.status)}`}>{STATUS_LABELS[lit.status]}</span></td>
                      <td>{lit.analysis?.relevance_score?.toFixed(1) ?? '—'}</td>
                      <td className="action-cell">
                        <button className="btn btn-sm btn-outline" title="选定" onClick={() => toggleSelect(lit.id)}>
                          {selectedIds.includes(lit.id) ? <CheckSquare size={14} /> : <Square size={14} />}
                        </button>
                        <button
                          className="btn btn-sm btn-outline"
                          title="查看分析结构"
                          onClick={() => setDetailLit(lit)}
                        >
                          <FileText size={14} />
                        </button>
                        <button className="btn btn-sm btn-danger" onClick={async () => {
                          if (confirm('确定删除？')) {
                            await deleteLiterature(activeWorkspace.id, lit.id)
                            loadLiteratures(activeWorkspace.id)
                          }
                        }}>
                          <Trash2 size={14} />
                        </button>
                      </td>
                    </tr>
                  ))}
                  {literatures.length === 0 && (
                    <tr><td colSpan={8} className="empty-cell">暂无文献，请上传 PDF</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
      )}

      {/* 开题报告配置对话框 */}
      {showProposal && (
        <div className="modal-overlay" onClick={() => setShowProposal(false)}>
          <div className="modal-card modal-wide" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h3>基于文献生成开题报告</h3>
              <button className="icon-btn" onClick={() => setShowProposal(false)}><X size={18} /></button>
            </div>
            <div className="form-group">
              <label className="form-label">协作角色</label>
              <p className="form-hint">勾选参与开题报告生成的 Agent。取消某角色将跳过其对应任务。</p>
              <div className="agent-select-grid proposal-agent-grid">
                {agents.map(agent => {
                  const inScenario = proposalScenarioAgentIds.has(agent.id)
                  const checked = proposalSelectedAgents.includes(agent.id)
                  return (
                    <label
                      key={agent.id}
                      className={`agent-select-card ${checked ? 'selected' : ''} ${!inScenario ? 'extra' : ''}`}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleProposalAgent(agent.id)}
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
              {proposalSelectedAgents.length === 0 && (
                <p className="form-hint" style={{ color: 'var(--warning)' }}>请至少选择一个协作角色</p>
              )}
            </div>
            <div className="form-group">
              <label className="form-label">数据源权重</label>
              {([
                ['only_library', '仅使用选定文献'],
                ['library_first', '文献为主，网络检索为辅'],
                ['web_first', '网络检索为主，文献为辅'],
              ] as const).map(([val, label]) => (
                <label key={val} className="radio-label">
                  <input type="radio" name="mode" value={val}
                    checked={proposalForm.mode === val}
                    onChange={() => setProposalForm(f => ({ ...f, mode: val }))} />
                  {label}
                </label>
              ))}
            </div>
            <div className="form-group">
              <label className="form-label">研究主题</label>
              <input
                className="form-input"
                value={proposalForm.topic}
                onChange={e => setProposalForm(f => ({ ...f, topic: e.target.value }))}
                placeholder={activeWorkspace?.name || '请输入研究主题（至少 5 个字符）'}
                minLength={5}
                required
              />
              {!proposalTopicValid && (
                <p className="form-hint" style={{ color: 'var(--warning)' }}>
                  主题过短（当前 {proposalTopic.length} 字），请至少输入 5 个字符
                </p>
              )}
            </div>
            <div className="form-group">
              <label className="form-label">补充要求</label>
              <textarea className="form-textarea" value={proposalForm.additional} rows={3}
                onChange={e => setProposalForm(f => ({ ...f, additional: e.target.value }))}
                placeholder="可选：对开题报告格式、侧重点等的额外要求" />
            </div>
            <p className="form-hint">将使用 {selectedIds.length} 篇选定文献</p>
            <div className="form-actions">
              <button
                className="btn btn-primary"
                onClick={handleProposal}
                disabled={!canStartProposal}
              >
                <Sparkles size={16} /> 确认并启动工作流
              </button>
              <button className="btn btn-outline" onClick={() => setShowProposal(false)}>取消</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
