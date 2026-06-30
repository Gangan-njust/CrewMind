import { useCallback, useEffect, useRef, useState } from 'react'
import {
  FlaskConical, Plus, Trash2, Upload, Loader, ChevronLeft, Camera,
  BarChart3, GitCompare, FileSpreadsheet, BookOpen, CheckCircle, AlertCircle,
  X, Image as ImageIcon, Link2, Clock, Pencil, ChevronDown, ChevronUp,
  Microscope, StickyNote, Target, Sparkles, Check, ZoomIn,
} from 'lucide-react'
import {
  fetchExperiments, fetchExperiment, createExperiment, deleteExperiment,
  createExperimentEntry, updateExperimentEntry, deleteExperimentEntry,
  uploadExperimentAttachment, uploadExperimentDataset,
  analyzeExperimentDataset, compareExperimentData,
  createExperimentFromWorkflow, fetchHistory,
  type Experiment, type ExperimentSummary, type ExperimentEntry,
  type ExperimentAnalysis, type ComparisonResult, type HistoryRecord,
  type ExperimentDataset,
} from '../api'

type Tab = 'eln' | 'data' | 'compare'

const ENTRY_TYPE_META: Record<string, { label: string; Icon: typeof BookOpen; color: string }> = {
  observation: { label: '观察记录', Icon: Microscope, color: 'var(--info)' },
  measurement: { label: '测量数据', Icon: BarChart3, color: 'var(--success)' },
  note: { label: '备注', Icon: StickyNote, color: 'var(--text-muted)' },
}

const COMPARE_STATUS: Record<string, { label: string; color: string }> = {
  match: { label: '达标', color: 'var(--success)' },
  mismatch: { label: '需关注', color: 'var(--danger)' },
  below: { label: '不足', color: 'var(--warning)' },
  unknown: { label: '未知', color: 'var(--text-muted)' },
  no_data: { label: '无数据', color: 'var(--text-muted)' },
}

function attachmentSrc(url: string): string {
  const token = localStorage.getItem('crewmind-token')
  if (!token) return url
  const sep = url.includes('?') ? '&' : '?'
  return `${url}${sep}token=${encodeURIComponent(token)}`
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleString('zh-CN', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

function KeyValueGrid({ data, label }: { data: Record<string, unknown>; label: string }) {
  const entries = Object.entries(data)
  if (!entries.length) return null
  return (
    <div className="exp-kv-block">
      <span className="exp-field-label">{label}</span>
      <div className="exp-kv-grid">
        {entries.map(([k, v]) => (
          <div key={k} className="exp-kv-item">
            <span className="exp-kv-key">{k}</span>
            <span className="exp-kv-val">{typeof v === 'object' ? JSON.stringify(v) : String(v)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function ExperimentToast({ message }: { message: string }) {
  if (!message) return null
  return (
    <div className="toast-container">
      <div className="toast"><Check size={16} color="var(--success)" />{message}</div>
    </div>
  )
}

interface Props {
  workflowRecordId?: string | null
}

export function ExperimentManager({ workflowRecordId }: Props) {
  const [experiments, setExperiments] = useState<ExperimentSummary[]>([])
  const [active, setActive] = useState<Experiment | null>(null)
  const [tab, setTab] = useState<Tab>('eln')
  const [loading, setLoading] = useState(false)
  const [listLoading, setListLoading] = useState(true)
  const [error, setError] = useState('')
  const [toast, setToast] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const [showFromWorkflow, setShowFromWorkflow] = useState(false)
  const [workflowRecords, setWorkflowRecords] = useState<HistoryRecord[]>([])
  const [analysis, setAnalysis] = useState<ExperimentAnalysis | null>(null)
  const [comparison, setComparison] = useState<ComparisonResult | null>(null)
  const [analyzingId, setAnalyzingId] = useState<string | null>(null)
  const [comparing, setComparing] = useState(false)
  const [creating, setCreating] = useState(false)
  const [savingEntry, setSavingEntry] = useState(false)
  const [uploadingData, setUploadingData] = useState(false)
  const [dataDragOver, setDataDragOver] = useState(false)
  const [showEntryForm, setShowEntryForm] = useState(true)
  const [expandedDatasets, setExpandedDatasets] = useState<Set<string>>(new Set())
  const [lightboxSrc, setLightboxSrc] = useState<string | null>(null)

  const [createForm, setCreateForm] = useState({ title: '', description: '' })
  const [workflowForm, setWorkflowForm] = useState({ recordId: '', title: '' })
  const [entryForm, setEntryForm] = useState({
    title: '', step_name: '', notes: '', entry_type: 'observation',
    instrument_params: '{}', raw_data: '{}',
  })
  const [editingEntry, setEditingEntry] = useState<ExperimentEntry | null>(null)

  const photoRef = useRef<HTMLInputElement>(null)
  const dataRef = useRef<HTMLInputElement>(null)
  const toastTimer = useRef<ReturnType<typeof setTimeout>>()
  const entryFormRef = useRef<HTMLDivElement>(null)

  const showToast = useCallback((msg: string) => {
    setToast(msg)
    if (toastTimer.current) clearTimeout(toastTimer.current)
    toastTimer.current = setTimeout(() => setToast(''), 2400)
  }, [])

  const loadList = useCallback(async () => {
    setListLoading(true)
    try {
      setExperiments(await fetchExperiments())
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '加载失败')
    } finally {
      setListLoading(false)
    }
  }, [])

  const loadDetail = useCallback(async (id: string) => {
    setLoading(true)
    try {
      const data = await fetchExperiment(id)
      setActive(data)
      setAnalysis(null)
      setComparison(null)
      setTab('eln')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadList() }, [loadList])

  useEffect(() => {
    if (workflowRecordId) {
      setWorkflowForm(f => ({ ...f, recordId: workflowRecordId }))
    }
  }, [workflowRecordId])

  useEffect(() => {
    if (!workflowRecordId || active) return
    let cancelled = false
    ;(async () => {
      try {
        const exp = await createExperimentFromWorkflow({ workflow_record_id: workflowRecordId })
        if (!cancelled) {
          await loadList()
          await loadDetail(exp.id)
          showToast('已从方案创建实验并提取预期指标')
        }
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof Error ? e.message : '从方案创建失败')
      }
    })()
    return () => { cancelled = true }
  }, [workflowRecordId]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (showFromWorkflow) fetchHistory().then(setWorkflowRecords).catch(() => {})
  }, [showFromWorkflow])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (lightboxSrc) setLightboxSrc(null)
        else if (showCreate) setShowCreate(false)
        else if (showFromWorkflow) setShowFromWorkflow(false)
        else if (active) setActive(null)
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [lightboxSrc, showCreate, showFromWorkflow, active])

  const resetEntryForm = () => {
    setEditingEntry(null)
    setEntryForm({ title: '', step_name: '', notes: '', entry_type: 'observation', instrument_params: '{}', raw_data: '{}' })
  }

  const handleCreate = async () => {
    if (!createForm.title.trim()) return
    setCreating(true)
    try {
      const exp = await createExperiment(createForm)
      setShowCreate(false)
      setCreateForm({ title: '', description: '' })
      await loadList()
      await loadDetail(exp.id)
      showToast('实验已创建')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '创建失败')
    } finally {
      setCreating(false)
    }
  }

  const handleFromWorkflow = async () => {
    if (!workflowForm.recordId) return
    setCreating(true)
    try {
      const exp = await createExperimentFromWorkflow({
        workflow_record_id: workflowForm.recordId,
        title: workflowForm.title || undefined,
      })
      setShowFromWorkflow(false)
      await loadList()
      await loadDetail(exp.id)
      showToast('已从方案创建实验并提取预期指标')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '创建失败')
    } finally {
      setCreating(false)
    }
  }

  const handleDelete = async (id: string) => {
    if (!confirm('确定删除该实验及所有记录？')) return
    try {
      await deleteExperiment(id)
      if (active?.id === id) setActive(null)
      await loadList()
      showToast('已删除')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '删除失败')
    }
  }

  const parseJsonField = (text: string): Record<string, unknown> => {
    try {
      const v = JSON.parse(text || '{}')
      return typeof v === 'object' && v !== null ? v : {}
    } catch {
      return {}
    }
  }

  const handleSaveEntry = async () => {
    if (!active) return
    const wasEditing = !!editingEntry
    const payload = {
      title: entryForm.title,
      step_name: entryForm.step_name,
      notes: entryForm.notes,
      entry_type: entryForm.entry_type,
      instrument_params: parseJsonField(entryForm.instrument_params),
      raw_data: parseJsonField(entryForm.raw_data),
    }
    setSavingEntry(true)
    try {
      if (editingEntry) {
        await updateExperimentEntry(editingEntry.id, payload)
      } else {
        await createExperimentEntry(active.id, payload)
      }
      resetEntryForm()
      setShowEntryForm(false)
      await loadDetail(active.id)
      showToast(wasEditing ? '记录已更新' : '记录已添加')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '保存失败')
    } finally {
      setSavingEntry(false)
    }
  }

  const handlePhotoUpload = async (entryId: string, files: FileList | null) => {
    if (!files?.length || !active) return
    try {
      for (const file of Array.from(files)) {
        await uploadExperimentAttachment(entryId, file, 'photo')
      }
      await loadDetail(active.id)
      showToast('照片已上传')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '上传失败')
    }
  }

  const handleDataUpload = async (files: FileList | null) => {
    if (!files?.length || !active) return
    setUploadingData(true)
    try {
      for (const file of Array.from(files)) {
        await uploadExperimentDataset(active.id, file)
      }
      await loadDetail(active.id)
      setTab('data')
      showToast('数据集已上传')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '上传失败')
    } finally {
      setUploadingData(false)
    }
  }

  const handleAnalyze = async (datasetId: string) => {
    setAnalyzingId(datasetId)
    try {
      const result = await analyzeExperimentDataset(datasetId)
      setAnalysis(result)
      setTab('data')
      showToast('分析完成')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '分析失败')
    } finally {
      setAnalyzingId(null)
    }
  }

  const handleCompare = async () => {
    if (!active) return
    setComparing(true)
    try {
      const result = await compareExperimentData(active.id)
      setComparison(result)
      showToast('对比完成')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '对比失败')
    } finally {
      setComparing(false)
    }
  }

  const startEditEntry = (entry: ExperimentEntry) => {
    setEditingEntry(entry)
    setShowEntryForm(true)
    setEntryForm({
      title: entry.title,
      step_name: entry.step_name,
      notes: entry.notes,
      entry_type: entry.entry_type,
      instrument_params: JSON.stringify(entry.instrument_params, null, 2),
      raw_data: JSON.stringify(entry.raw_data, null, 2),
    })
    setTimeout(() => entryFormRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50)
  }

  const toggleDatasetExpand = (id: string) => {
    setExpandedDatasets(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const renderDatasetCard = (ds: ExperimentDataset) => {
    const expanded = expandedDatasets.has(ds.id)
    const isAnalyzing = analyzingId === ds.id
    const isAnalyzed = analysis?.dataset_id === ds.id
    return (
      <div key={ds.id} className={`exp-dataset-card ${isAnalyzed ? 'analyzed' : ''}`}>
        <div className="exp-dataset-head">
          <div className="exp-dataset-icon"><FileSpreadsheet size={22} /></div>
          <div className="exp-dataset-info">
            <strong>{ds.filename}</strong>
            <div className="exp-dataset-meta">
              <span>{ds.row_count} 行</span>
              <span>{ds.columns.length} 列</span>
              <span>{ds.file_type.toUpperCase()}</span>
            </div>
          </div>
          <div className="exp-dataset-actions">
            <button type="button" className="btn btn-outline btn-sm" onClick={() => toggleDatasetExpand(ds.id)}>
              {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
              预览
            </button>
            <button
              type="button"
              className="btn btn-primary btn-sm"
              disabled={!!analyzingId}
              onClick={() => handleAnalyze(ds.id)}
            >
              {isAnalyzing ? <Loader size={14} className="spinner" /> : <Sparkles size={14} />}
              自动分析
            </button>
          </div>
        </div>
        {expanded && ds.preview.length > 0 && (
          <div className="exp-preview-wrap">
            <table className="exp-preview-table">
              <thead>
                <tr>{ds.columns.map(c => <th key={c.name}>{c.name}</th>)}</tr>
              </thead>
              <tbody>
                {ds.preview.slice(0, 5).map((row, i) => (
                  <tr key={i}>
                    {ds.columns.map(c => <td key={c.name}>{String(row[c.name] ?? '')}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    )
  }

  if (active) {
    const matchedCount = comparison?.comparisons.filter(c => c.status === 'match').length ?? 0
    const totalCompare = comparison?.comparisons.length ?? 0

    return (
      <div className="experiment-page exp-detail-view fade-in">
        <header className="exp-detail-header">
          <button type="button" className="btn btn-outline exp-back-btn" onClick={() => setActive(null)}>
            <ChevronLeft size={18} /> 返回列表
          </button>
          <div className="exp-detail-title-block">
            <h2>{active.title}</h2>
            <div className="exp-detail-meta">
              {active.source_workflow_id && (
                <span className="exp-chip linked"><Link2 size={12} /> 已关联方案</span>
              )}
              <span className="exp-chip"><BookOpen size={12} /> {active.entries.length} 条记录</span>
              <span className="exp-chip"><FileSpreadsheet size={12} /> {active.datasets.length} 个数据集</span>
              <span className="exp-chip muted"><Clock size={12} /> 更新于 {formatDate(active.updated_at)}</span>
            </div>
          </div>
        </header>

        {active.description && (
          <p className="exp-detail-desc">{active.description}</p>
        )}

        <nav className="exp-tabs" role="tablist">
          {([
            { id: 'eln' as Tab, label: '实验记录本', icon: BookOpen, count: active.entries.length },
            { id: 'data' as Tab, label: '数据分析', icon: BarChart3, count: active.datasets.length },
            { id: 'compare' as Tab, label: '方案对比', icon: GitCompare, count: active.expected_metrics.length },
          ]).map(({ id, label, icon: Icon, count }) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={tab === id}
              className={`exp-tab ${tab === id ? 'active' : ''}`}
              onClick={() => setTab(id)}
            >
              <Icon size={15} />
              {label}
              {count > 0 && <span className="exp-tab-count">{count}</span>}
            </button>
          ))}
        </nav>

        {loading ? (
          <div className="exp-loading">
            <Loader size={28} className="spinner" />
            <span>加载实验数据…</span>
          </div>
        ) : (
          <div className="exp-tab-panel fade-in" key={tab}>
            {tab === 'eln' && (
              <div className="exp-eln">
                <div className="exp-entry-form-card card" ref={entryFormRef}>
                  <button
                    type="button"
                    className="exp-form-toggle"
                    onClick={() => setShowEntryForm(v => !v)}
                  >
                    <h3>{editingEntry ? '编辑记录' : '新增实验记录'}</h3>
                    {showEntryForm ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
                  </button>
                  {showEntryForm && (
                    <div className="exp-form-body">
                      <div className="exp-form-row">
                        <input className="form-input" placeholder="记录标题" value={entryForm.title}
                          onChange={e => setEntryForm(f => ({ ...f, title: e.target.value }))} />
                        <input className="form-input" placeholder="实验步骤名称" value={entryForm.step_name}
                          onChange={e => setEntryForm(f => ({ ...f, step_name: e.target.value }))} />
                        <select className="form-select" value={entryForm.entry_type}
                          onChange={e => setEntryForm(f => ({ ...f, entry_type: e.target.value }))}>
                          <option value="observation">观察记录</option>
                          <option value="measurement">测量数据</option>
                          <option value="note">备注</option>
                        </select>
                      </div>
                      <textarea className="form-textarea" placeholder="实验笔记、观察现象、操作记录…" rows={4}
                        value={entryForm.notes}
                        onChange={e => setEntryForm(f => ({ ...f, notes: e.target.value }))} />
                      <div className="exp-form-row two-col">
                        <div>
                          <label className="exp-field-label">仪器参数 (JSON)</label>
                          <textarea className="form-textarea exp-code-input" rows={4} value={entryForm.instrument_params}
                            onChange={e => setEntryForm(f => ({ ...f, instrument_params: e.target.value }))} />
                        </div>
                        <div>
                          <label className="exp-field-label">原始数据 (JSON)</label>
                          <textarea className="form-textarea exp-code-input" rows={4} value={entryForm.raw_data}
                            onChange={e => setEntryForm(f => ({ ...f, raw_data: e.target.value }))} />
                        </div>
                      </div>
                      <div className="exp-form-actions">
                        <button type="button" className="btn btn-primary" disabled={savingEntry} onClick={handleSaveEntry}>
                          {savingEntry ? <Loader size={16} className="spinner" /> : <Plus size={16} />}
                          {editingEntry ? '保存修改' : '添加记录'}
                        </button>
                        {editingEntry && (
                          <button type="button" className="btn btn-outline" onClick={resetEntryForm}>取消编辑</button>
                        )}
                      </div>
                    </div>
                  )}
                </div>

                {active.entries.length === 0 ? (
                  <div className="exp-empty-inline">
                    <Microscope size={36} strokeWidth={1.2} />
                    <p>暂无实验记录</p>
                    <span>按方案步骤记录观察、仪器参数与原始数据，并可上传实验照片。</span>
                    <button type="button" className="btn btn-outline btn-sm" onClick={() => setShowEntryForm(true)}>
                      <Plus size={14} /> 添加第一条记录
                    </button>
                  </div>
                ) : (
                  <div className="exp-timeline">
                    {active.entries.map((entry, idx) => {
                      const meta = ENTRY_TYPE_META[entry.entry_type] || ENTRY_TYPE_META.observation
                      const TypeIcon = meta.Icon
                      return (
                        <article key={entry.id} className="exp-entry-card" style={{ '--entry-accent': meta.color } as React.CSSProperties}>
                          <div className="exp-entry-marker">
                            <span className="exp-entry-dot" />
                            {idx < active.entries.length - 1 && <span className="exp-entry-line" />}
                          </div>
                          <div className="exp-entry-body card">
                            <header className="exp-entry-head">
                              <div>
                                <div className="exp-entry-title-row">
                                  <TypeIcon size={16} style={{ color: meta.color }} />
                                  <strong>{entry.title || entry.step_name || '未命名记录'}</strong>
                                  <span className="exp-type-badge" style={{ color: meta.color }}>{meta.label}</span>
                                </div>
                                {entry.step_name && entry.title && (
                                  <span className="exp-entry-step">{entry.step_name}</span>
                                )}
                              </div>
                              <div className="exp-entry-actions">
                                <button type="button" className="btn-icon" title="上传照片"
                                  onClick={() => {
                                    photoRef.current?.setAttribute('data-entry-id', entry.id)
                                    photoRef.current?.click()
                                  }}>
                                  <Camera size={16} />
                                </button>
                                <button type="button" className="btn-icon" title="编辑" onClick={() => startEditEntry(entry)}>
                                  <Pencil size={16} />
                                </button>
                                <button type="button" className="btn-icon danger" title="删除"
                                  onClick={async () => {
                                    if (!confirm('删除此记录？')) return
                                    await deleteExperimentEntry(entry.id)
                                    await loadDetail(active.id)
                                    showToast('记录已删除')
                                  }}>
                                  <Trash2 size={16} />
                                </button>
                              </div>
                            </header>
                            {entry.notes && <p className="exp-entry-notes">{entry.notes}</p>}
                            <KeyValueGrid data={entry.instrument_params} label="仪器参数" />
                            <KeyValueGrid data={entry.raw_data} label="原始数据" />
                            {entry.attachments.length > 0 && (
                              <div className="exp-photo-grid">
                                {entry.attachments.map(att => (
                                  att.mime_type.startsWith('image/') ? (
                                    <button
                                      key={att.id}
                                      type="button"
                                      className="exp-photo-thumb"
                                      onClick={() => setLightboxSrc(attachmentSrc(att.url))}
                                    >
                                      <img src={attachmentSrc(att.url)} alt={att.filename} />
                                      <span className="exp-photo-zoom"><ZoomIn size={16} /></span>
                                    </button>
                                  ) : (
                                    <a key={att.id} className="exp-file-thumb" href={attachmentSrc(att.url)} target="_blank" rel="noreferrer">
                                      <ImageIcon size={20} />
                                      <span>{att.filename}</span>
                                    </a>
                                  )
                                ))}
                              </div>
                            )}
                            <footer className="exp-entry-time">{formatDate(entry.created_at)}</footer>
                          </div>
                        </article>
                      )
                    })}
                  </div>
                )}
              </div>
            )}

            {tab === 'data' && (
              <div className="exp-data">
                <div
                  className={`upload-zone exp-upload-zone ${dataDragOver ? 'drag-over' : ''}`}
                  onDragOver={e => { e.preventDefault(); setDataDragOver(true) }}
                  onDragLeave={() => setDataDragOver(false)}
                  onDrop={e => {
                    e.preventDefault()
                    setDataDragOver(false)
                    handleDataUpload(e.dataTransfer.files)
                  }}
                  onClick={() => !uploadingData && dataRef.current?.click()}
                  role="button"
                  tabIndex={0}
                  onKeyDown={e => e.key === 'Enter' && dataRef.current?.click()}
                >
                  {uploadingData ? (
                    <><Loader size={32} className="spinner" /><p>正在上传…</p></>
                  ) : (
                    <>
                      <Upload size={32} />
                      <p>拖拽或点击上传 CSV / Excel</p>
                      <span>支持 .csv、.xlsx、.xls，最大 10MB</span>
                    </>
                  )}
                </div>

                {active.datasets.length > 0 ? (
                  <div className="exp-dataset-list">{active.datasets.map(renderDatasetCard)}</div>
                ) : (
                  <div className="exp-empty-inline compact">
                    <BarChart3 size={32} strokeWidth={1.2} />
                    <p>尚无数据集</p>
                    <span>上传后将自动生成描述统计、图表与显著性检验。</span>
                  </div>
                )}

                {analysis && (
                  <section className="exp-analysis-result card fade-in">
                    <header className="exp-analysis-head">
                      <h3><Sparkles size={18} /> 分析结果</h3>
                      <div className="exp-analysis-tags">
                        <span className="exp-chip">变量：{String(analysis.summary.value_column)}</span>
                        {analysis.summary.group_column != null && analysis.summary.group_column !== '' && (
                          <span className="exp-chip">分组：{String(analysis.summary.group_column)}</span>
                        )}
                      </div>
                    </header>
                    {analysis.charts.length > 0 && (
                      <div className="exp-charts-grid">
                        {analysis.charts.map((chart, i) => (
                          <figure key={i} className="exp-chart-card">
                            <figcaption>{chart.title}</figcaption>
                            <img src={`data:image/png;base64,${chart.image_base64}`} alt={chart.title} />
                          </figure>
                        ))}
                      </div>
                    )}
                    {analysis.stats.length > 0 && (
                      <div className="exp-stats-wrap">
                        <table className="exp-preview-table">
                          <thead>
                            <tr><th>检验</th><th>变量</th><th>统计量</th><th>p 值</th><th>结论</th></tr>
                          </thead>
                          <tbody>
                            {analysis.stats.map((s, i) => {
                              const sig = s.significant_005 === true
                              const pVal = s.p_value != null ? Number(s.p_value) : null
                              return (
                                <tr key={i} className={sig ? 'significant' : ''}>
                                  <td><code>{String(s.test || '')}</code></td>
                                  <td>{String(s.variable || s.group_column || '')}</td>
                                  <td>{s.statistic != null ? String(s.statistic) : (s.mean != null ? `μ=${s.mean}` : '—')}</td>
                                  <td>
                                    {pVal != null ? (
                                      <span className={sig ? 'exp-p-sig' : ''}>{pVal < 0.001 ? '<0.001' : pVal.toFixed(4)}</span>
                                    ) : '—'}
                                  </td>
                                  <td>{String(s.interpretation || (sig ? '显著' : ''))}</td>
                                </tr>
                              )
                            })}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </section>
                )}
              </div>
            )}

            {tab === 'compare' && (
              <div className="exp-compare">
                <div className="exp-compare-toolbar card">
                  <div>
                    <h3><Target size={18} /> 预期 vs 实际</h3>
                    <p className="exp-compare-hint">将方案中提取的预期指标与上传的实验数据自动比对。</p>
                  </div>
                  <button type="button" className="btn btn-primary" disabled={comparing} onClick={handleCompare}>
                    {comparing ? <Loader size={16} className="spinner" /> : <GitCompare size={16} />}
                    运行对比
                  </button>
                </div>

                {active.expected_metrics.length > 0 ? (
                  <div className="exp-expected-grid">
                    {active.expected_metrics.map((m, i) => (
                      <div key={i} className="exp-expected-card card">
                        <span className="exp-expected-label">{m.label}</span>
                        <span className="exp-expected-value">
                          {m.expected_value != null ? m.expected_value : '—'}
                          {m.unit || ''}
                          {m.tolerance != null && <small> ±{m.tolerance}</small>}
                        </span>
                        {m.source_text && <span className="exp-expected-src">{m.source_text}</span>}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="exp-empty-inline compact">
                    <Link2 size={32} strokeWidth={1.2} />
                    <p>未关联方案预期指标</p>
                    <span>从历史方案创建实验可自动提取样本量、准确率等预期值。</span>
                  </div>
                )}

                {comparison && (
                  <section className="exp-compare-result fade-in">
                    <div className="exp-compare-summary card">
                      <p className="exp-compare-summary-text">{comparison.summary}</p>
                      {totalCompare > 0 && (
                        <div className="exp-compare-score">
                          <div className="exp-score-ring" style={{ '--pct': `${(matchedCount / totalCompare) * 100}%` } as React.CSSProperties}>
                            <span>{matchedCount}/{totalCompare}</span>
                          </div>
                          <div className="exp-score-legend">
                            <span><i className="dot match" /> 达标 {matchedCount}</span>
                            <span><i className="dot warn" /> 需关注 {totalCompare - matchedCount}</span>
                          </div>
                        </div>
                      )}
                    </div>
                    {comparison.comparisons.length > 0 && (
                      <div className="exp-compare-list">
                        {comparison.comparisons.map((item, i) => {
                          const st = COMPARE_STATUS[item.status] || COMPARE_STATUS.unknown
                          return (
                            <div key={i} className={`exp-compare-item card status-${item.status}`}>
                              <div className="exp-compare-item-head">
                                {item.status === 'match'
                                  ? <CheckCircle size={18} style={{ color: st.color }} />
                                  : <AlertCircle size={18} style={{ color: st.color }} />}
                                <strong>{item.metric.label}</strong>
                                <span className="exp-status-pill" style={{ color: st.color, borderColor: st.color }}>{st.label}</span>
                              </div>
                              <p>{item.interpretation}</p>
                              {(item.actual_value != null || item.expected_value != null) && (
                                <div className="exp-compare-values">
                                  {item.expected_value != null && <span>预期 <b>{item.expected_value}</b></span>}
                                  {item.actual_value != null && <span>实测 <b>{item.actual_value}</b></span>}
                                  {item.deviation_percent != null && (
                                    <span>偏差 <b>{item.deviation_percent > 0 ? '+' : ''}{item.deviation_percent}%</b></span>
                                  )}
                                </div>
                              )}
                            </div>
                          )
                        })}
                      </div>
                    )}
                  </section>
                )}
              </div>
            )}
          </div>
        )}

        <input ref={photoRef} type="file" accept="image/*" multiple hidden
          onChange={e => {
            const entryId = photoRef.current?.getAttribute('data-entry-id')
            if (entryId) handlePhotoUpload(entryId, e.target.files)
            e.target.value = ''
          }} />
        <input ref={dataRef} type="file" accept=".csv,.xlsx,.xls" multiple hidden
          onChange={e => { handleDataUpload(e.target.files); e.target.value = '' }} />

        {lightboxSrc && (
          <div className="modal-overlay exp-lightbox" onClick={() => setLightboxSrc(null)}>
            <button type="button" className="exp-lightbox-close" onClick={() => setLightboxSrc(null)}><X size={24} /></button>
            <img src={lightboxSrc} alt="实验照片" onClick={e => e.stopPropagation()} />
          </div>
        )}

        {error && (
          <div className="error-banner" role="alert">
            {error}
            <button type="button" onClick={() => setError('')}><X size={14} /></button>
          </div>
        )}
        <ExperimentToast message={toast} />
      </div>
    )
  }

  return (
    <div className="experiment-page fade-in">
      <header className="exp-hero">
        <div className="exp-hero-text">
          <h2><FlaskConical size={24} color="var(--accent-light)" /> 实验数据管理</h2>
          <p>电子实验记录本、数据自动分析与方案预期对比，贯穿实验执行全流程。</p>
          <div className="exp-feature-pills">
            <span><BookOpen size={13} /> ELN 记录</span>
            <span><BarChart3 size={13} /> 统计检验</span>
            <span><GitCompare size={13} /> 方案联动</span>
          </div>
        </div>
        <div className="exp-hero-actions">
          <button type="button" className="btn btn-outline" onClick={() => setShowFromWorkflow(true)}>
            <Link2 size={16} /> 从方案创建
          </button>
          <button type="button" className="btn btn-primary" onClick={() => setShowCreate(true)}>
            <Plus size={16} /> 新建实验
          </button>
        </div>
      </header>

      {listLoading ? (
        <div className="exp-loading">
          <Loader size={28} className="spinner" />
          <span>加载实验列表…</span>
        </div>
      ) : experiments.length === 0 ? (
        <div className="exp-empty-hero card">
          <div className="exp-empty-icon"><FlaskConical size={56} strokeWidth={1.2} /></div>
          <h3>开始您的第一个实验项目</h3>
          <p>从工作方案一键创建并自动提取预期指标，或手动新建电子实验记录本。</p>
          <div className="exp-empty-actions">
            <button type="button" className="btn btn-primary" onClick={() => setShowCreate(true)}>
              <Plus size={16} /> 新建实验
            </button>
            <button type="button" className="btn btn-outline" onClick={() => setShowFromWorkflow(true)}>
              <Link2 size={16} /> 从方案创建
            </button>
          </div>
        </div>
      ) : (
        <div className="exp-project-list">
          {experiments.map(exp => (
            <article
              key={exp.id}
              className="exp-project-card"
              tabIndex={0}
              onClick={() => loadDetail(exp.id)}
              onKeyDown={e => e.key === 'Enter' && loadDetail(exp.id)}
            >
              <div className="exp-card-top">
                <span className={`exp-status-dot ${exp.status}`} />
                <button
                  type="button"
                  className="btn-icon danger exp-card-delete"
                  title="删除"
                  onClick={e => { e.stopPropagation(); handleDelete(exp.id) }}
                >
                  <Trash2 size={14} />
                </button>
              </div>
              <h3>{exp.title}</h3>
              {exp.description && <p className="exp-card-desc">{exp.description}</p>}
              <footer className="exp-card-footer">
                <span><BookOpen size={13} /> {exp.entry_count} 记录</span>
                <span><FileSpreadsheet size={13} /> {exp.dataset_count} 数据集</span>
                {exp.source_workflow_id && (
                  <span className="exp-chip linked sm"><Link2 size={11} /> 已关联</span>
                )}
                <span className="exp-card-date">{formatDate(exp.updated_at)}</span>
              </footer>
            </article>
          ))}
        </div>
      )}

      {showCreate && (
        <div className="modal-overlay" onClick={() => setShowCreate(false)}>
          <div className="modal-card" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h3>新建实验</h3>
              <button type="button" className="btn-icon" onClick={() => setShowCreate(false)}><X size={18} /></button>
            </div>
            <label className="exp-field-label">实验名称</label>
            <input className="form-input" placeholder="例如：催化剂活性测试 v1" value={createForm.title}
              onChange={e => setCreateForm(f => ({ ...f, title: e.target.value }))}
              onKeyDown={e => e.key === 'Enter' && handleCreate()} />
            <label className="exp-field-label">实验说明（可选）</label>
            <textarea className="form-textarea" placeholder="简要描述实验目的与方案…" rows={3} value={createForm.description}
              onChange={e => setCreateForm(f => ({ ...f, description: e.target.value }))} />
            <div className="modal-actions">
              <button type="button" className="btn btn-outline" onClick={() => setShowCreate(false)}>取消</button>
              <button type="button" className="btn btn-primary" disabled={creating || !createForm.title.trim()} onClick={handleCreate}>
                {creating ? <Loader size={16} className="spinner" /> : <Plus size={16} />}
                创建
              </button>
            </div>
          </div>
        </div>
      )}

      {showFromWorkflow && (
        <div className="modal-overlay" onClick={() => setShowFromWorkflow(false)}>
          <div className="modal-card modal-wide" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h3>从历史方案创建实验</h3>
              <button type="button" className="btn-icon" onClick={() => setShowFromWorkflow(false)}><X size={18} /></button>
            </div>
            <p className="form-hint">自动关联实验方案并提取样本量、预期指标等，便于后续与实际数据对比。</p>
            <label className="exp-field-label">选择历史方案</label>
            <select className="form-select" value={workflowForm.recordId}
              onChange={e => setWorkflowForm(f => ({ ...f, recordId: e.target.value }))}>
              <option value="">请选择…</option>
              {workflowRecords.map(r => (
                <option key={r.id} value={r.id}>{r.title} ({r.scenario})</option>
              ))}
            </select>
            <label className="exp-field-label">实验名称（可选）</label>
            <input className="form-input" placeholder="默认取自方案标题" value={workflowForm.title}
              onChange={e => setWorkflowForm(f => ({ ...f, title: e.target.value }))} />
            <div className="modal-actions">
              <button type="button" className="btn btn-outline" onClick={() => setShowFromWorkflow(false)}>取消</button>
              <button type="button" className="btn btn-primary" disabled={creating || !workflowForm.recordId} onClick={handleFromWorkflow}>
                {creating ? <Loader size={16} className="spinner" /> : <Sparkles size={16} />}
                创建并提取预期指标
              </button>
            </div>
          </div>
        </div>
      )}

      {error && (
        <div className="error-banner" role="alert">
          {error}
          <button type="button" onClick={() => setError('')}><X size={14} /></button>
        </div>
      )}
      <ExperimentToast message={toast} />
    </div>
  )
}
