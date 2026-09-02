import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  PenLine, Plus, Trash2, Loader, ChevronLeft, Sparkles, Wand2,
  CheckCircle, BookMarked, History, GitCompare, Save, FileText,
  List, Eye, Copy, RotateCcw, BookOpen, FlaskConical, BarChart3,
  MessageSquare, Library, Heart, X, Clock, Check, AlertCircle,
  ChevronDown, ChevronUp, ChevronRight, GraduationCap, Presentation, Newspaper, Sparkle,
  Download, Maximize2, Pencil, ArrowUp, ArrowDown, FolderPlus, Heading2, Link2, Hash,
} from 'lucide-react'
import {
  fetchWritingProjects, fetchWritingProject, createWritingProject,
  deleteWritingProject, updateWritingSection, updateWritingProject,
  generateWritingOutline, expandWriting, polishWriting,
  completeWritingFromOutline,
  checkTerminology, checkCoherence, checkStyle, checkBlankLines,
  generateWritingKeywords, checkAbstractKeywords,
  recommendCitations, applyWritingCitation, checkCitationCompleteness, fetchSectionVersions,
  compareSectionVersions, rollbackSection, fetchWritingBibliography,
  createWritingFromWorkflow, fetchWorkspaces, fillMethodsFromWorkflow,
  downloadWritingExport, createWritingSection, updateWritingSectionMeta,
  deleteWritingSection, reorderWritingSections,
  checkFigures, fetchWritingFigureCandidates, createWritingFigureAsset, writingAssetUrl, getToken,
  getSectionDisplayName, getSectionLabel, isAbstractSection,
  type WritingProject, type WritingProjectSummary,
  type WritingSection, type SectionVersion, type PaperType, type CitationFormat,
  type OutlineSubsection, type Workspace, type FigureHintItem,
} from '../api'
import { buildFullDocumentMarkdown } from '../writingPreview'
import { WritingMarkdownPreview } from '../WritingMarkdownPreview'
import { BIBLIOGRAPHY_SECTION_TITLE, insertCitationAtPosition, isBibliographySection } from '../writingCitations'
import { computeSectionNumbers, getNumberedSectionDisplayName } from '../writingSectionNumbers'
import {
  buildExpandStructureItems,
  getExpandPreamble,
  type ExpandStructureItem,
} from '../writingExpandStructure'
import {
  insertMarkdownHeading,
  lineStartOffset,
  getSectionHeadings,
  type SubheadingLevel,
} from '../writingHeadings'
import { figurePlaceholderBlock, insertTextAfterLine } from '../writingFigureHints'

type ToolTab = 'expand' | 'polish' | 'check' | 'citation' | 'version'
type ExpandMode = 'free' | 'structured'
type PolishMode = 'free' | 'structured'
type SaveStatus = 'saved' | 'saving' | 'unsaved'

const PAPER_TYPE_LABELS: Record<PaperType, string> = {
  journal: '期刊论文',
  conference: '会议论文',
  thesis: '学位论文',
}

const PAPER_TYPE_OPTIONS: {
  id: PaperType
  label: string
  desc: string
  sections: string
  Icon: typeof Newspaper
}[] = [
  {
    id: 'journal',
    label: '期刊论文',
    desc: '标准 IMRaD 结构，适合 SCI / EI 期刊投稿',
    sections: '摘要 · Abstract · 引言 · 方法 · 结果 · 讨论 · 结论',
    Icon: Newspaper,
  },
  {
    id: 'conference',
    label: '会议论文',
    desc: '篇幅精炼，突出核心贡献与创新点',
    sections: '摘要 · Abstract · 引言 · 方法 · 结果 · 讨论 · 结论',
    Icon: Presentation,
  },
  {
    id: 'thesis',
    label: '学位论文',
    desc: '完整学位论文结构，含相关工作与致谢',
    sections: '摘要 · Abstract · 引言 · 相关工作 · 方法 · 结果 · 讨论 · 结论 · 致谢',
    Icon: GraduationCap,
  },
]

const CITATION_FORMAT_LABELS: Record<CitationFormat, string> = {
  gb7714: 'GB/T 7714',
  apa: 'APA',
  mla: 'MLA',
  chicago: 'Chicago',
}

const SECTION_ICONS: Record<string, typeof FileText> = {
  abstract: FileText,
  abstract_en: FileText,
  intro: BookOpen,
  methods: FlaskConical,
  results: BarChart3,
  discussion: MessageSquare,
  conclusion: CheckCircle,
  related_work: Library,
  acknowledgments: Heart,
  custom: FolderPlus,
}

const SUBHEADING_LEVEL_LABELS: Record<SubheadingLevel, string> = {
  2: '二级标题',
  3: '三级标题',
  4: '四级标题',
}

function sectionStatus(wordCount: number): 'empty' | 'draft' | 'done' {
  if (wordCount === 0) return 'empty'
  if (wordCount < 100) return 'draft'
  return 'done'
}

function formatRelativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return '刚刚'
  if (mins < 60) return `${mins} 分钟前`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days} 天前`
  return new Date(iso).toLocaleDateString('zh-CN')
}

function formatKeywordsInput(keywords: string[] | undefined, english = false): string {
  if (!keywords?.length) return ''
  return english ? keywords.join('; ') : keywords.join('；')
}

function parseKeywordsInput(text: string): string[] {
  return text.split(/[;；,，、]/).map(s => s.trim()).filter(Boolean)
}

function composeAbstractWithKeywords(body: string, keywords: string[], english: boolean): string {
  if (!keywords.length) return body.trim()
  const label = english ? 'Keywords' : '关键词'
  const sep = english ? '; ' : '；'
  const suffix = english ? `${label}: ${keywords.join(sep)}` : `${label}：${keywords.join(sep)}`
  const trimmed = body.trim()
  return trimmed ? `${trimmed}\n\n${suffix}` : suffix
}

function stripKeywordsFromAbstract(content: string, english: boolean): string {
  const pattern = english
    ? /^\s*Keywords[：:]\s*.+$/im
    : /^\s*关键词[：:]\s*.+$/im
  return content.replace(pattern, '').trim()
}

interface Props {
  workflowRecordId?: string | null
  workspaceLink?: { id: string; name: string } | null
  onProjectReady?: () => void
  onWorkspaceLinkReady?: () => void
}

export function WritingAssistant({
  workflowRecordId,
  workspaceLink,
  onProjectReady,
  onWorkspaceLinkReady,
}: Props) {
  const [projects, setProjects] = useState<WritingProjectSummary[]>([])
  const [activeProject, setActiveProject] = useState<WritingProject | null>(null)
  const [activeSection, setActiveSection] = useState<WritingSection | null>(null)
  const [editContent, setEditContent] = useState('')
  const [showPreview, setShowPreview] = useState(false)
  const [listLoading, setListLoading] = useState(true)
  const [editorLoading, setEditorLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [toolTab, setToolTab] = useState<ToolTab>('expand')
  const [toolLoading, setToolLoading] = useState(false)
  const [toolResult, setToolResult] = useState<any>(null)
  const [error, setError] = useState('')
  const [toast, setToast] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const [creating, setCreating] = useState(false)
  const [outlineExpanded, setOutlineExpanded] = useState(true)
  const [createForm, setCreateForm] = useState({
    title: '', topic: '', paper_type: 'journal' as PaperType, target_journal: '',
    workspace_id: '',
  })
  const [versions, setVersions] = useState<SectionVersion[]>([])
  const [compareResult, setCompareResult] = useState<any>(null)
  const [expandLength, setExpandLength] = useState<'short' | 'medium' | 'long'>('medium')
  const [expandMode, setExpandMode] = useState<ExpandMode>('free')
  const [expandStructureItems, setExpandStructureItems] = useState<ExpandStructureItem[]>([])
  const [expandGlobalRequirements, setExpandGlobalRequirements] = useState('')
  const [exporting, setExporting] = useState(false)
  const [showExportMenu, setShowExportMenu] = useState(false)
  const [showSectionManager, setShowSectionManager] = useState(false)
  const [showFullPreview, setShowFullPreview] = useState(false)
  const [showCompleteOutline, setShowCompleteOutline] = useState(false)
  const [completeOutlineLoading, setCompleteOutlineLoading] = useState(false)
  const [completeGlobalRequirements, setCompleteGlobalRequirements] = useState('')
  const [completeSkipFilled, setCompleteSkipFilled] = useState(true)
  const [completeOutlineResult, setCompleteOutlineResult] = useState<any>(null)
  const [outlineNavCollapsed, setOutlineNavCollapsed] = useState(false)
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set())
  const [activeSubheadingKey, setActiveSubheadingKey] = useState<string | null>(null)
  const [toolsPanelCollapsed, setToolsPanelCollapsed] = useState(false)
  const [newSectionTitle, setNewSectionTitle] = useState('')
  const [sectionManagerLoading, setSectionManagerLoading] = useState(false)
  const [polishStyle, setPolishStyle] = useState<'conservative' | 'moderate' | 'deep'>('moderate')
  const [polishMode, setPolishMode] = useState<PolishMode>('free')
  const [polishStructureItems, setPolishStructureItems] = useState<ExpandStructureItem[]>([])
  const [polishGlobalRequirements, setPolishGlobalRequirements] = useState('')
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [applyingCitationId, setApplyingCitationId] = useState<string | null>(null)
  const [keywordsZhInput, setKeywordsZhInput] = useState('')
  const [keywordsEnInput, setKeywordsEnInput] = useState('')
  const autoSaveTimer = useRef<ReturnType<typeof setInterval>>()
  const lastSaved = useRef('')
  const toastTimer = useRef<ReturnType<typeof setTimeout>>()
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // 图表完整性提醒
  const [figureHints, setFigureHints] = useState<FigureHintItem[]>([])
  const [ignoredFigureKeys, setIgnoredFigureKeys] = useState<Set<string>>(new Set())
  const [assetCandidates, setAssetCandidates] = useState<any>(null)
  const [assetBusy, setAssetBusy] = useState(false)
  const [expandedAssetPickerKey, setExpandedAssetPickerKey] = useState<string | null>(null)
  const [candidatesError, setCandidatesError] = useState('')

  const hasUnsaved = editContent !== lastSaved.current
  const saveStatus: SaveStatus = saving ? 'saving' : hasUnsaved ? 'unsaved' : 'saved'

  const showToastMsg = useCallback((msg: string) => {
    setToast(msg)
    if (toastTimer.current) clearTimeout(toastTimer.current)
    toastTimer.current = setTimeout(() => setToast(''), 2600)
  }, [])

  // ── 图表完整性提醒：徽标 / 占位插入 / 真实图表素材 ──────────
  const figureHintCountFor = useCallback((sectionId: string) => {
    return figureHints.filter(
      h => h.section_id === sectionId && (!h.key || !ignoredFigureKeys.has(h.key)),
    ).length
  }, [figureHints, ignoredFigureKeys])

  const loadFigureHints = useCallback(async (projectId: string) => {
    try {
      const report = await checkFigures(projectId, false)
      setFigureHints(report.issues || [])
    } catch {
      // 徽标加载失败静默处理，可在「检查」Tab 手动重跑
    }
  }, [])

  const clearProjectFigureState = useCallback(() => {
    setFigureHints([])
    setIgnoredFigureKeys(new Set())
    setAssetCandidates(null)
    setExpandedAssetPickerKey(null)
    setCandidatesError('')
  }, [])

  const ensureCandidates = useCallback(async () => {
    if (!activeProject) return
    if (assetCandidates) return
    setAssetBusy(true)
    setCandidatesError('')
    try {
      const data = await fetchWritingFigureCandidates(activeProject.id)
      setAssetCandidates(data)
    } catch (e: any) {
      setCandidatesError(e.message)
    } finally {
      setAssetBusy(false)
    }
  }, [activeProject, assetCandidates])

  const applyFigureContentSave = useCallback(async (next: string, note: string) => {
    if (!activeSection || !activeProject) return false
    try {
      const updated = await updateWritingSection(activeSection.id, {
        content: next,
        save_version: true,
        version_note: note,
      })
      lastSaved.current = next
      setEditContent(next)
      setActiveSection(updated)
      setActiveProject(prev => prev ? {
        ...prev,
        sections: prev.sections.map(s => s.id === updated.id ? updated : s),
      } : prev)
      return true
    } catch (e: any) {
      setError(e.message)
      return false
    }
  }, [activeSection, activeProject])

  const handleInsertFigurePlaceholder = useCallback(async (issue: FigureHintItem) => {
    if (!activeSection || !activeProject) return
    if (issue.section_id && issue.section_id !== activeSection.id) {
      showToastMsg(`请先切换到「${issue.display_title || issue.section_type || '目标'}」章节再插入占位`)
      return
    }
    const block = figurePlaceholderBlock(
      issue.chart_type,
      issue.suggestion || issue.reason || '',
      activeSection.section_type,
    )
    const next = insertTextAfterLine(editContent, issue.line, block)
    if (next === editContent) {
      showToastMsg('插入失败：行号超出正文范围')
      return
    }
    const ok = await applyFigureContentSave(next, '插入图表占位')
    if (ok) {
      const issueKey = issue.key
      if (issueKey) setIgnoredFigureKeys(prev => new Set(prev).add(issueKey))
      showToastMsg('已插入图表占位（导出时自动清理，可替换为真实图表）')
      await loadFigureHints(activeProject.id)
    }
  }, [activeSection, activeProject, editContent, applyFigureContentSave, loadFigureHints, showToastMsg])

  const handleIgnoreFigure = useCallback((issue: FigureHintItem) => {
    const issueKey = issue.key
    if (!issueKey) return
    setIgnoredFigureKeys(prev => new Set(prev).add(issueKey))
  }, [])

  const candidateSource = useCallback((cand: any) => {
    switch (cand.kind) {
      case 'experiment_chart':
        return { analysis_id: cand.analysis_id, chart_index: cand.chart_index }
      case 'experiment_metric':
        return { experiment_id: cand.experiment_id, metric_name: cand.metric_name }
      case 'experiment_attachment':
        return { attachment_id: cand.attachment_id }
      case 'literature_image':
        return { workspace_id: cand.workspace_id, literature_id: cand.literature_id, filename: cand.filename }
      default:
        return {}
    }
  }, [])

  const handleInsertRealAsset = useCallback(async (issue: FigureHintItem, cand: any) => {
    if (!activeSection || !activeProject) return
    if (issue.section_id && issue.section_id !== activeSection.id) {
      showToastMsg(`请先切换到「${issue.display_title || '目标'}」章节再插入真实图表`)
      return
    }
    setAssetBusy(true)
    try {
      const asset = await createWritingFigureAsset(activeProject.id, {
        kind: cand.kind,
        caption: cand.title || cand.filename || '',
        source: candidateSource(cand),
      })
      const note = (issue.suggestion || issue.reason || '').replace(/\n/g, ' ').slice(0, 60)
      const extra = note ? `\n\n*（图注建议：${note}）*` : ''
      const next = insertTextAfterLine(editContent, issue.line, `${asset.markdown_ref}${extra}`)
      if (next === editContent) {
        showToastMsg('插入失败：行号超出正文范围')
        return
      }
      const ok = await applyFigureContentSave(next, '插入真实图表')
      if (ok) {
        const issueKey = issue.key
        if (issueKey) setIgnoredFigureKeys(prev => new Set(prev).add(issueKey))
        setExpandedAssetPickerKey(null)
        showToastMsg('已插入真实图表（预览可见，导出 docx 自动嵌入）')
        await loadFigureHints(activeProject.id)
      }
    } catch (e: any) {
      setError(e.message)
    } finally {
      setAssetBusy(false)
    }
  }, [activeSection, activeProject, editContent, candidateSource, applyFigureContentSave, loadFigureHints, showToastMsg])

  const loadProjects = useCallback(async () => {
    setListLoading(true)
    try {
      const data = await fetchWritingProjects()
      setProjects(data)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setListLoading(false)
    }
  }, [])

  const openProject = useCallback(async (id: string) => {
    setEditorLoading(true)
    setError('')
    clearProjectFigureState()
    try {
      const project = await fetchWritingProject(id)
      setActiveProject(project)
      const first = project.sections[0] || null
      setActiveSection(first)
      setEditContent(first?.content || '')
      lastSaved.current = first?.content || ''
      setExpandedSections(new Set(first ? [first.id] : []))
      setActiveSubheadingKey(null)
      setToolResult(null)
      setCompareResult(null)
      void loadFigureHints(id)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setEditorLoading(false)
    }
  }, [clearProjectFigureState, loadFigureHints])

  useEffect(() => { loadProjects() }, [loadProjects])

  useEffect(() => {
    if (!showExportMenu) return
    const close = () => setShowExportMenu(false)
    document.addEventListener('click', close)
    return () => document.removeEventListener('click', close)
  }, [showExportMenu])
  useEffect(() => {
    fetchWorkspaces().then(setWorkspaces).catch(() => {})
  }, [])

  const getWorkspaceName = useCallback((id: string | null | undefined) => {
    if (!id) return ''
    return workspaces.find(w => w.id === id)?.name || '文献工作空间'
  }, [workspaces])

  useEffect(() => {
    if (!activeProject) return
    setKeywordsZhInput(formatKeywordsInput(activeProject.keywords_zh ?? []))
    setKeywordsEnInput(formatKeywordsInput(activeProject.keywords_en ?? [], true))
  }, [activeProject?.id, activeProject?.keywords_zh, activeProject?.keywords_en])

  useEffect(() => {
    if (!workspaceLink) return
    setActiveProject(null)
    setActiveSection(null)
    setCreateForm(f => ({
      ...f,
      title: workspaceLink.name,
      workspace_id: workspaceLink.id,
    }))
    setShowCreate(true)
    onWorkspaceLinkReady?.()
  }, [workspaceLink]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!workflowRecordId) return
    setEditorLoading(true)
    createWritingFromWorkflow({ workflow_record_id: workflowRecordId })
      .then(p => { openProject(p.id); showToastMsg('已从工作方案创建写作项目'); onProjectReady?.() })
      .catch(e => setError(e.message))
      .finally(() => setEditorLoading(false))
  }, [workflowRecordId]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault()
        if (activeProject && activeSection) saveSectionRef.current?.()
      }
      if (e.key === 'Escape') {
        if (showCreate && !creating) setShowCreate(false)
        if (showSectionManager) setShowSectionManager(false)
        if (showFullPreview) setShowFullPreview(false)
        if (showCompleteOutline && !completeOutlineLoading) setShowCompleteOutline(false)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [activeProject, activeSection, showCreate, showSectionManager, showFullPreview, showCompleteOutline, completeOutlineLoading, creating])

  const saveSectionRef = useRef<(note?: string) => Promise<void>>()

  const saveSection = useCallback(async (note = '') => {
    if (!activeSection || !activeProject) return
    if (editContent === lastSaved.current) return
    setSaving(true)
    try {
      const updated = await updateWritingSection(activeSection.id, {
        content: editContent,
        save_version: true,
        version_note: note || '手动保存',
      })
      lastSaved.current = editContent
      setActiveSection(updated)
      setActiveProject(prev => prev ? {
        ...prev,
        sections: prev.sections.map(s => s.id === updated.id ? updated : s),
      } : prev)
      showToastMsg('已保存')
      void loadFigureHints(activeProject.id)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }, [activeSection, activeProject, editContent, showToastMsg, loadFigureHints])

  saveSectionRef.current = saveSection

  const selectSection = useCallback((section: WritingSection, force = false) => {
    if (!force && editContent !== lastSaved.current) {
      if (!confirm('当前章节有未保存的更改，确定切换章节？')) return
    }
    setActiveSection(section)
    setEditContent(section.content)
    lastSaved.current = section.content
    setExpandedSections(prev => new Set(prev).add(section.id))
    setActiveSubheadingKey(null)
    setToolResult(null)
    setCompareResult(null)
  }, [editContent])

  useEffect(() => {
    if (activeSection) {
      setExpandedSections(prev => new Set(prev).add(activeSection.id))
    }
  }, [activeSection?.id])

  useEffect(() => {
    if (!activeSection) return
    autoSaveTimer.current = setInterval(() => {
      if (editContent !== lastSaved.current) {
        updateWritingSection(activeSection.id, {
          content: editContent,
          save_version: true,
          version_note: '自动保存',
        }).then(updated => {
          lastSaved.current = editContent
          setActiveSection(updated)
          setActiveProject(prev => prev ? {
            ...prev,
            sections: prev.sections.map(s => s.id === updated.id ? updated : s),
          } : prev)
        }).catch(() => {})
      }
    }, 30000)
    return () => { if (autoSaveTimer.current) clearInterval(autoSaveTimer.current) }
  }, [activeSection, editContent])

  const handleCreate = async () => {
    if (!createForm.title.trim()) return
    setCreating(true)
    setError('')
    try {
      const project = await createWritingProject({
        ...createForm,
        workspace_id: createForm.workspace_id || undefined,
      })
      if (createForm.topic.trim()) {
        const outline = await generateWritingOutline({
          topic: createForm.topic,
          paper_type: createForm.paper_type,
          target_journal: createForm.target_journal,
        })
        await updateWritingProject(project.id, { outline: outline.sections })
      }
      setShowCreate(false)
      setCreateForm({ title: '', topic: '', paper_type: 'journal', target_journal: '', workspace_id: '' })
      await loadProjects()
      await openProject(project.id)
      showToastMsg('写作项目已创建')
    } catch (e: any) {
      setError(e.message)
    } finally {
      setCreating(false)
    }
  }

  const closeCreateModal = () => {
    if (creating) return
    setShowCreate(false)
  }

  const handleDelete = async (id: string, e?: React.MouseEvent) => {
    e?.stopPropagation()
    if (!confirm('确定删除此写作项目？此操作不可恢复。')) return
    await deleteWritingProject(id)
    if (activeProject?.id === id) {
      setActiveProject(null)
      setActiveSection(null)
    }
    loadProjects()
    showToastMsg('项目已删除')
  }

  const runExpand = async () => {
    if (!activeSection) return
    if (expandMode === 'free' && !editContent.trim()) {
      showToastMsg('请先输入章节内容')
      return
    }
    setToolLoading(true)
    setToolResult(null)
    try {
      const result = await expandWriting({
        text: editContent,
        section_type: activeSection.section_type,
        topic: activeProject?.topic || '',
        length: expandLength,
        mode: 'free',
        project_id: activeProject?.id,
      })
      setToolResult(result)
      const ragHint = result.rag_evidence_count
        ? `已注入 ${result.rag_evidence_count} 条文献证据`
        : '扩写完成，可预览后应用'
      showToastMsg(ragHint)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setToolLoading(false)
    }
  }

  const loadExpandStructure = useCallback((preserveSettings = true) => {
    if (!activeSection || !activeProject) return
    const outlineForSection = activeProject.outline?.find(o => o.section_type === activeSection.section_type)
    setExpandStructureItems(prev => buildExpandStructureItems(
      editContent,
      outlineForSection?.subsections,
      preserveSettings ? prev : undefined,
    ))
  }, [activeSection, activeProject, editContent])

  useEffect(() => {
    if (expandMode === 'structured' && activeSection && activeProject) {
      loadExpandStructure(true)
    }
  }, [expandMode, activeSection?.id, activeProject?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  const runStructuredExpand = async () => {
    if (!activeSection) return
    const enabledItems = expandStructureItems.filter(item => item.enabled)
    if (!enabledItems.length) {
      showToastMsg('请至少启用一个小节')
      return
    }
    setToolLoading(true)
    setToolResult(null)
    try {
      const result = await expandWriting({
        text: getExpandPreamble(editContent),
        section_type: activeSection.section_type,
        topic: activeProject?.topic || '',
        mode: 'structured',
        global_requirements: expandGlobalRequirements,
        project_id: activeProject?.id,
        items: enabledItems.map(item => ({
          title: item.title,
          level: item.level,
          word_target: item.wordTarget,
          requirements: item.requirements,
          existing_content: item.existingContent,
          outline_points: item.outlinePoints,
          enabled: item.enabled,
        })),
      })
      setToolResult(result)
      const ragHint = result.rag_evidence_count
        ? `已注入 ${result.rag_evidence_count} 条文献证据`
        : '目录扩写完成，可预览后应用'
      showToastMsg(ragHint)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setToolLoading(false)
    }
  }

  const updateExpandStructureItem = useCallback((id: string, patch: Partial<ExpandStructureItem>) => {
    setExpandStructureItems(prev => prev.map(item => item.id === id ? { ...item, ...patch } : item))
  }, [])

  const runCompleteOutline = async () => {
    if (!activeProject) return
    if (!activeProject.outline?.length && !confirm('当前项目尚无 AI 大纲，将仅按章节结构补全。是否继续？')) return
    if (!confirm('将按目录结构逐章生成/补全正文，已有内容的章节默认跳过。是否开始？')) return
    setCompleteOutlineLoading(true)
    setCompleteOutlineResult(null)
    setError('')
    try {
      const result = await completeWritingFromOutline(activeProject.id, {
        global_requirements: completeGlobalRequirements,
        skip_filled: completeSkipFilled,
      })
      setCompleteOutlineResult(result)
      setActiveProject(result.project)
      const current = activeSection
        ? result.project.sections.find(s => s.id === activeSection.id) || result.project.sections[0]
        : result.project.sections[0]
      if (current) {
        setActiveSection(current)
        setEditContent(current.content)
        lastSaved.current = current.content
      }
      showToastMsg(result.summary)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setCompleteOutlineLoading(false)
    }
  }

  const handleExport = async (format: 'md' | 'docx') => {
    if (!activeProject) return
    setExporting(true)
    setShowExportMenu(false)
    try {
      await downloadWritingExport(activeProject.id, format, true)
      showToastMsg(`已导出 ${format.toUpperCase()} 文件`)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setExporting(false)
    }
  }

  const runPolish = async () => {
    if (!activeSection) return
    if (polishMode === 'free' && !editContent.trim()) return
    setToolLoading(true)
    setToolResult(null)
    try {
      const result = await polishWriting({
        text: editContent,
        section_type: activeSection.section_type,
        topic: activeProject?.topic || '',
        style: polishStyle,
        mode: 'free',
        project_id: activeProject?.id,
      })
      setToolResult(result)
      const ragHint = result.rag_evidence_count
        ? `已注入 ${result.rag_evidence_count} 条文献证据`
        : '润色完成，可预览后应用'
      showToastMsg(ragHint)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setToolLoading(false)
    }
  }

  const loadPolishStructure = useCallback((preserveSettings = true) => {
    if (!activeSection || !activeProject) return
    const outlineForSection = activeProject.outline?.find(o => o.section_type === activeSection.section_type)
    setPolishStructureItems(prev => buildExpandStructureItems(
      editContent,
      outlineForSection?.subsections,
      preserveSettings ? prev : undefined,
    ))
  }, [activeSection, activeProject, editContent])

  useEffect(() => {
    if (polishMode === 'structured' && toolTab === 'polish' && activeSection && activeProject) {
      loadPolishStructure(true)
    }
  }, [polishMode, toolTab, activeSection?.id, activeProject?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  const runStructuredPolish = async () => {
    if (!activeSection) return
    const enabledItems = polishStructureItems.filter(item => item.enabled)
    if (!enabledItems.length) {
      showToastMsg('请至少启用一个小节')
      return
    }
    setToolLoading(true)
    setToolResult(null)
    try {
      const result = await polishWriting({
        text: getExpandPreamble(editContent),
        section_type: activeSection.section_type,
        topic: activeProject?.topic || '',
        style: polishStyle,
        mode: 'structured',
        global_requirements: polishGlobalRequirements,
        project_id: activeProject?.id,
        items: enabledItems.map(item => ({
          title: item.title,
          level: item.level,
          word_target: item.wordTarget,
          requirements: item.requirements,
          existing_content: item.existingContent,
          outline_points: item.outlinePoints,
          enabled: item.enabled,
        })),
      })
      setToolResult(result)
      const ragHint = result.rag_evidence_count
        ? `已注入 ${result.rag_evidence_count} 条文献证据`
        : '小节润色完成，可预览后应用'
      showToastMsg(ragHint)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setToolLoading(false)
    }
  }

  const updatePolishStructureItem = useCallback((id: string, patch: Partial<ExpandStructureItem>) => {
    setPolishStructureItems(prev => prev.map(item => item.id === id ? { ...item, ...patch } : item))
  }, [])

  const runCheck = async (type: 'terminology' | 'coherence' | 'style' | 'citation' | 'blank_lines' | 'keywords_generate' | 'abstract_keywords' | 'figures') => {
    if (type !== 'blank_lines' && !activeProject) return
    if (type === 'blank_lines' && !editContent.trim()) {
      showToastMsg('当前章节暂无内容')
      return
    }
    setToolLoading(true)
    setToolResult(null)
    try {
      let result
      if (type === 'terminology') result = await checkTerminology(activeProject!.id)
      else if (type === 'coherence') result = await checkCoherence(activeProject!.id)
      else if (type === 'style') result = await checkStyle(editContent, activeSection?.section_type)
      else if (type === 'blank_lines') result = await checkBlankLines(editContent)
      else if (type === 'keywords_generate') {
        result = await generateWritingKeywords(activeProject!.id)
        setActiveProject(result.project)
        setKeywordsZhInput(formatKeywordsInput(result.keywords_zh))
        const abstractSec = result.project.sections.find(s => s.section_type === 'abstract')
        if (abstractSec && activeSection?.id === abstractSec.id) {
          setEditContent(abstractSec.content)
          lastSaved.current = abstractSec.content
          setActiveSection(abstractSec)
        }
        result = { type: 'keywords_generate', ...result }
      } else if (type === 'abstract_keywords') {
        result = await checkAbstractKeywords(activeProject!.id)
        result = { type: 'abstract_keywords', ...result }
      } else if (type === 'figures') {
        result = await checkFigures(activeProject!.id, true)
        setFigureHints(result.issues || [])
        setExpandedAssetPickerKey(null)
        result = { type: 'figures', ...result }
      } else result = await checkCitationCompleteness(activeProject!.id)
      if (!result.type) setToolResult({ type, ...result })
      else setToolResult(result)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setToolLoading(false)
    }
  }

  const saveKeywords = async () => {
    if (!activeProject) return
    const keywords_zh = parseKeywordsInput(keywordsZhInput)
    const keywords_en = parseKeywordsInput(keywordsEnInput)
    setToolLoading(true)
    try {
      let project = await updateWritingProject(activeProject.id, { keywords_zh, keywords_en })

      const abstractSec = project.sections.find(s => s.section_type === 'abstract')
      if (abstractSec) {
        const body = stripKeywordsFromAbstract(abstractSec.content, false)
        const content = composeAbstractWithKeywords(body, keywords_zh, false)
        const updated = await updateWritingSection(abstractSec.id, {
          content,
          save_version: true,
          version_note: '更新中文关键词',
        })
        project = {
          ...project,
          sections: project.sections.map(s => s.id === abstractSec.id ? updated : s),
        }
        if (activeSection?.id === abstractSec.id) {
          setEditContent(content)
          lastSaved.current = content
          setActiveSection(updated)
        }
      }

      const abstractEnSec = project.sections.find(s => s.section_type === 'abstract_en')
      if (abstractEnSec) {
        const body = stripKeywordsFromAbstract(abstractEnSec.content, true)
        const content = composeAbstractWithKeywords(body, keywords_en, true)
        const updated = await updateWritingSection(abstractEnSec.id, {
          content,
          save_version: true,
          version_note: '更新英文 Keywords',
        })
        project = {
          ...project,
          sections: project.sections.map(s => s.id === abstractEnSec.id ? updated : s),
        }
        if (activeSection?.id === abstractEnSec.id) {
          setEditContent(content)
          lastSaved.current = content
          setActiveSection(updated)
        }
      }

      setActiveProject(project)
      showToastMsg('关键词已保存')
    } catch (e: any) {
      setError(e.message)
    } finally {
      setToolLoading(false)
    }
  }

  const applyAbstractKeywordsFix = async () => {
    if (!activeProject || (!toolResult?.abstract_en_suggested && !toolResult?.keywords_en_suggested?.length)) return
    setToolLoading(true)
    try {
      let project = activeProject
      const keywords_en = toolResult.keywords_en_suggested?.length
        ? toolResult.keywords_en_suggested
        : (project.keywords_en || parseKeywordsInput(keywordsEnInput))

      if (toolResult.abstract_en_suggested) {
        const enSec = project.sections.find(s => s.section_type === 'abstract_en')
        if (enSec) {
          const content = composeAbstractWithKeywords(toolResult.abstract_en_suggested, keywords_en, true)
          const updated = await updateWritingSection(enSec.id, {
            content,
            save_version: true,
            version_note: 'Abstract 自动翻译',
          })
          project = {
            ...project,
            sections: project.sections.map(s => s.id === enSec.id ? updated : s),
          }
          if (activeSection?.id === enSec.id) {
            setEditContent(content)
            lastSaved.current = content
            setActiveSection(updated)
          }
        }
      }

      if (toolResult.keywords_en_suggested?.length) {
        project = await updateWritingProject(project.id, { keywords_en: toolResult.keywords_en_suggested })
        setKeywordsEnInput(formatKeywordsInput(toolResult.keywords_en_suggested, true))
      }

      setActiveProject(project)
      setToolResult((prev: any) => prev ? {
        ...prev,
        abstract_en_ok: true,
        keywords_en_ok: true,
        needs_fix: false,
        summary: '已应用 Abstract 与 Keywords 修正',
      } : prev)
      showToastMsg('已应用 Abstract / Keywords 修正')
    } catch (e: any) {
      setError(e.message)
    } finally {
      setToolLoading(false)
    }
  }

  const runCitationRecommend = async () => {
    if (!activeProject) return
    const ta = textareaRef.current
    const selected = ta
      ? editContent.slice(ta.selectionStart, ta.selectionEnd)
      : (window.getSelection()?.toString() || editContent.slice(-100))
    if (selected.trim().length < 5 && !editContent.trim()) {
      showToastMsg('请先选中要引用的文字，或输入章节内容')
      return
    }
    setToolLoading(true)
    setToolResult(null)
    try {
      const result = await recommendCitations({
        selected_text: selected.trim() || editContent.slice(-100),
        context: editContent,
        project_id: activeProject.id,
      })
      setToolResult({ type: 'recommend', ...result })
    } catch (e: any) {
      setError(e.message)
    } finally {
      setToolLoading(false)
    }
  }

  const applyCitation = async (rec: {
    literature_id: string
    reason?: string
    literature?: { title?: string }
  }) => {
    if (!activeProject || !activeSection || isBibliographySection(activeSection)) {
      showToastMsg('请在正文章节中应用引用')
      return
    }
    const ta = textareaRef.current
    const start = ta?.selectionStart ?? editContent.length
    const end = ta?.selectionEnd ?? editContent.length
    const selected = editContent.slice(start, end)

    setApplyingCitationId(rec.literature_id)
    setError('')
    try {
      const result = await applyWritingCitation({
        project_id: activeProject.id,
        section_id: activeSection.id,
        literature_id: rec.literature_id,
        selected_text: selected,
        purpose: selected || rec.reason || '',
      })

      const newContent = insertCitationAtPosition(editContent, start, end, result.insert_text)
      setEditContent(newContent)
      lastSaved.current = newContent

      const updated = await updateWritingSection(activeSection.id, {
        content: newContent,
        save_version: true,
        version_note: `插入引用 ${result.citation_marker}`,
      })
      setActiveSection(updated)
      setActiveProject(result.project)

      setToolResult({
        type: 'recommend',
        recommendations: toolResult?.recommendations,
        bibliography: result.bibliography,
        lastApplied: result,
      })
      showToastMsg(`已插入引用 ${result.citation_marker}，参考文献已更新`)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setApplyingCitationId(null)
    }
  }

  const applyInsertHeading = useCallback((
    content: string,
    level: SubheadingLevel,
    title?: string,
    selectionStart?: number,
    selectionEnd?: number,
  ) => {
    setShowPreview(false)
    const start = selectionStart ?? textareaRef.current?.selectionStart ?? content.length
    const end = selectionEnd ?? textareaRef.current?.selectionEnd ?? content.length
    const result = insertMarkdownHeading(content, start, end, level, title)
    setEditContent(result.text)
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        const textarea = textareaRef.current
        if (!textarea) return
        textarea.focus()
        textarea.setSelectionRange(result.cursor, result.selectEnd ?? result.cursor)
      })
    })
    showToastMsg(`已插入${SUBHEADING_LEVEL_LABELS[level]}`)
  }, [showToastMsg])

  const handleInsertHeading = useCallback((level: SubheadingLevel, title?: string) => {
    if (!activeSection) return
    applyInsertHeading(editContent, level, title)
  }, [activeSection, editContent, applyInsertHeading])

  const handleInsertHeadingInSection = useCallback((section: WritingSection, level: SubheadingLevel, title?: string) => {
    if (activeSection?.id === section.id) {
      handleInsertHeading(level, title)
      return
    }
    if (editContent !== lastSaved.current && !confirm('当前章节有未保存的更改，确定切换章节？')) return
    setActiveSection(section)
    const content = section.content
    setEditContent(content)
    lastSaved.current = content
    setExpandedSections(prev => new Set(prev).add(section.id))
    requestAnimationFrame(() => {
      applyInsertHeading(content, level, title, content.length, content.length)
    })
  }, [activeSection, editContent, handleInsertHeading, applyInsertHeading])

  const scrollToHeading = useCallback((line: number, content?: string) => {
    const textarea = textareaRef.current
    if (!textarea) return
    const text = content ?? editContent
    const offset = lineStartOffset(text, line)
    textarea.focus()
    textarea.setSelectionRange(offset, offset)
    const lineHeight = parseInt(getComputedStyle(textarea).lineHeight, 10) || 24
    textarea.scrollTop = Math.max(0, line * lineHeight - textarea.clientHeight / 3)
  }, [editContent])

  const jumpToSubheading = useCallback((section: WritingSection, line: number) => {
    const key = `${section.id}:${line}`
    const doScroll = (content: string) => {
      setShowPreview(false)
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          scrollToHeading(line, content)
          setActiveSubheadingKey(key)
        })
      })
    }
    if (activeSection?.id !== section.id) {
      if (editContent !== lastSaved.current && !confirm('当前章节有未保存的更改，确定切换章节？')) return
      setActiveSection(section)
      setEditContent(section.content)
      lastSaved.current = section.content
      setExpandedSections(prev => new Set(prev).add(section.id))
      doScroll(section.content)
      return
    }
    doScroll(editContent)
  }, [activeSection, editContent, scrollToHeading])

  const toggleSectionExpanded = useCallback((sectionId: string) => {
    setExpandedSections(prev => {
      const next = new Set(prev)
      if (next.has(sectionId)) next.delete(sectionId)
      else next.add(sectionId)
      return next
    })
  }, [])

  const loadVersions = async () => {
    if (!activeSection) return
    try {
      const v = await fetchSectionVersions(activeSection.id)
      setVersions(v)
    } catch (e: any) {
      setError(e.message)
    }
  }

  const handleCompare = async (va: number, vb: number) => {
    if (!activeSection) return
    setToolLoading(true)
    try {
      const result = await compareSectionVersions(activeSection.id, va, vb)
      setCompareResult(result)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setToolLoading(false)
    }
  }

  const handleRollback = async (version: number) => {
    if (!activeSection || !confirm(`确定回滚至 v${version}？`)) return
    try {
      const updated = await rollbackSection(activeSection.id, version)
      setEditContent(updated.content)
      lastSaved.current = updated.content
      setActiveSection(updated)
      loadVersions()
      showToastMsg(`已回滚至 v${version}`)
    } catch (e: any) {
      setError(e.message)
    }
  }

  const handleFillMethods = async () => {
    if (!activeProject?.source_workflow_id) return
    setToolLoading(true)
    try {
      const updated = await fillMethodsFromWorkflow(activeProject.id, activeProject.source_workflow_id)
      if (activeSection?.section_type === 'methods') {
        setEditContent(updated.content)
        lastSaved.current = updated.content
        setActiveSection(updated)
      }
      const project = await fetchWritingProject(activeProject.id)
      setActiveProject(project)
      showToastMsg('已从实验方案填充 Methods')
    } catch (e: any) {
      setError(e.message)
    } finally {
      setToolLoading(false)
    }
  }

  const handleCitationFormatChange = async (fmt: CitationFormat) => {
    if (!activeProject) return
    const updated = await updateWritingProject(activeProject.id, { citation_format: fmt })
    setActiveProject(updated)
    const bib = await fetchWritingBibliography(activeProject.id)
    setToolResult(bib)
  }

  const handleWorkspaceLink = async (workspaceId: string) => {
    if (!activeProject) return
    try {
      const updated = await updateWritingProject(activeProject.id, {
        workspace_id: workspaceId || null,
      })
      setActiveProject(updated)
      showToastMsg(workspaceId ? '已关联文献工作空间' : '已取消文献工作空间关联')
    } catch (e: any) {
      setError(e.message)
    }
  }

  const handleBackToList = () => {
    if (hasUnsaved && !confirm('有未保存的更改，确定返回？')) return
    setActiveProject(null)
    setActiveSection(null)
  }

  const refreshProject = useCallback(async (keepSectionId?: string) => {
    if (!activeProject) return
    const project = await fetchWritingProject(activeProject.id)
    setActiveProject(project)
    const sid = keepSectionId || activeSection?.id
    const current = sid ? project.sections.find(s => s.id === sid) : project.sections[0]
    if (current) {
      setActiveSection(current)
      setEditContent(current.content)
      lastSaved.current = current.content
    } else {
      setActiveSection(null)
      setEditContent('')
      lastSaved.current = ''
    }
    void loadFigureHints(project.id)
    return project
  }, [activeProject, activeSection?.id, loadFigureHints])

  const handleAddSection = async () => {
    if (!activeProject || !newSectionTitle.trim()) return
    setSectionManagerLoading(true)
    try {
      const created = await createWritingSection(activeProject.id, {
        title: newSectionTitle.trim(),
        after_section_id: activeSection?.id,
      })
      setNewSectionTitle('')
      await refreshProject(created.id)
      showToastMsg('章节已添加')
    } catch (e: any) {
      setError(e.message)
    } finally {
      setSectionManagerLoading(false)
    }
  }

  const handleRenameSection = async (sectionId: string, title: string) => {
    if (!title.trim()) return
    setSectionManagerLoading(true)
    try {
      await updateWritingSectionMeta(sectionId, title.trim())
      await refreshProject(sectionId)
      showToastMsg('章节已更新')
    } catch (e: any) {
      setError(e.message)
    } finally {
      setSectionManagerLoading(false)
    }
  }

  const handleDeleteSection = async (section: WritingSection) => {
    if (!section.is_custom) return
    if (!confirm(`确定删除章节「${sectionTitle(section)}」？内容将不可恢复。`)) return
    setSectionManagerLoading(true)
    try {
      await deleteWritingSection(section.id)
      await refreshProject()
      showToastMsg('章节已删除')
    } catch (e: any) {
      setError(e.message)
    } finally {
      setSectionManagerLoading(false)
    }
  }

  const handleMoveSection = async (sectionId: string, direction: 'up' | 'down') => {
    if (!activeProject) return
    const ids = activeProject.sections.map(s => s.id)
    const idx = ids.indexOf(sectionId)
    if (idx < 0) return
    const target = direction === 'up' ? idx - 1 : idx + 1
    if (target < 0 || target >= ids.length) return
    ;[ids[idx], ids[target]] = [ids[target], ids[idx]]
    setSectionManagerLoading(true)
    try {
      await reorderWritingSections(activeProject.id, ids)
      await refreshProject(sectionId)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setSectionManagerLoading(false)
    }
  }

  const totalWords = activeProject?.sections.reduce((sum, s) => {
    if (s.id === activeSection?.id) {
      return sum + editContent.replace(/\s/g, '').length
    }
    return sum + s.word_count
  }, 0) ?? 0

  const fullPreviewMarkdown = useMemo(() => {
    if (!activeProject) return ''
    return buildFullDocumentMarkdown(activeProject, activeSection?.id ?? null, editContent)
  }, [activeProject, activeSection?.id, editContent])

  const hasPreviewContent = useMemo(
    () => fullPreviewMarkdown.includes('## '),
    [fullPreviewMarkdown],
  )
  const completedSections = activeProject?.sections.filter(s => sectionStatus(s.word_count) === 'done').length ?? 0
  const outlineItem = activeProject?.outline?.find(o => o.section_type === activeSection?.section_type)
  const activeIsBibliography = activeSection ? isBibliographySection(activeSection) : false

  const sectionNumbers = useMemo(
    () => computeSectionNumbers(activeProject?.sections ?? []),
    [activeProject?.sections],
  )

  const sectionTitle = useCallback(
    (section: WritingSection) => getNumberedSectionDisplayName(section, sectionNumbers),
    [sectionNumbers],
  )

  if (!activeProject) {
    return (
      <div className="writing-page writing-list-view">
        <header className="writing-hero">
          <div className="writing-hero-text">
            <h2><PenLine size={24} /> 学术写作辅助</h2>
            <p>结构化论文写作、智能扩写润色、引用管理与版本控制</p>
          </div>
          <button className="btn btn-primary" onClick={() => setShowCreate(true)}>
            <Plus size={16} /> 新建项目
          </button>
        </header>

        {error && (
          <div className="writing-error-banner">
            <AlertCircle size={16} />
            <span>{error}</span>
            <button type="button" className="writing-error-close" onClick={() => setError('')} aria-label="关闭">
              <X size={14} />
            </button>
          </div>
        )}

        {showCreate && (
          <div className="modal-overlay" onClick={closeCreateModal}>
            <div
              className="modal-card writing-create-modal"
              onClick={e => e.stopPropagation()}
              role="dialog"
              aria-labelledby="writing-create-title"
            >
              <div className="writing-create-header">
                <div className="writing-create-header-icon">
                  <PenLine size={22} />
                </div>
                <div className="writing-create-header-text">
                  <h3 id="writing-create-title">新建写作项目</h3>
                  <p>填写基本信息，系统将自动生成论文章节框架与写作大纲</p>
                </div>
                <button
                  type="button"
                  className="icon-btn writing-create-close"
                  onClick={closeCreateModal}
                  disabled={creating}
                  aria-label="关闭"
                >
                  <X size={18} />
                </button>
              </div>

              <div className={`writing-create-body ${creating ? 'is-submitting' : ''}`}>
                <div className="form-group">
                  <label className="form-label" htmlFor="writing-title">
                    项目标题 <span className="required">*</span>
                  </label>
                  <input
                    id="writing-title"
                    className="form-input"
                    value={createForm.title}
                    onChange={e => setCreateForm(f => ({ ...f, title: e.target.value }))}
                    placeholder="例：基于深度学习的医学图像分割研究"
                    autoFocus
                    disabled={creating}
                  />
                </div>

                <div className="form-group">
                  <label className="form-label" htmlFor="writing-topic">
                    研究主题
                    <span className="form-label-hint">填写后将 AI 生成论文大纲</span>
                  </label>
                  <textarea
                    id="writing-topic"
                    className="form-textarea"
                    value={createForm.topic}
                    onChange={e => setCreateForm(f => ({ ...f, topic: e.target.value }))}
                    rows={3}
                    placeholder="描述研究背景、核心问题与创新点…"
                    disabled={creating}
                  />
                </div>

                <div className="form-group">
                  <span className="form-label">论文类型</span>
                  <div className="writing-paper-type-list">
                    {PAPER_TYPE_OPTIONS.map(({ id, label, desc, sections, Icon }) => (
                      <button
                        key={id}
                        type="button"
                        className={`writing-paper-type-option ${createForm.paper_type === id ? 'active' : ''}`}
                        onClick={() => setCreateForm(f => ({ ...f, paper_type: id }))}
                        disabled={creating}
                      >
                        <div className="paper-type-option-icon">
                          <Icon size={20} />
                        </div>
                        <div className="paper-type-option-body">
                          <div className="paper-type-option-title">
                            <span>{label}</span>
                            {createForm.paper_type === id && (
                              <Check size={14} className="paper-type-check" />
                            )}
                          </div>
                          <p className="paper-type-option-desc">{desc}</p>
                          <p className="paper-type-option-sections">{sections}</p>
                        </div>
                      </button>
                    ))}
                  </div>
                </div>

                <div className="form-group">
                  <label className="form-label" htmlFor="writing-journal">
                    目标期刊 / 会议
                    <span className="form-label-hint">可选</span>
                  </label>
                  <input
                    id="writing-journal"
                    className="form-input"
                    value={createForm.target_journal}
                    onChange={e => setCreateForm(f => ({ ...f, target_journal: e.target.value }))}
                    placeholder="例：IEEE Transactions on Medical Imaging"
                    disabled={creating}
                  />
                </div>

                {workspaces.length > 0 && (
                  <div className="form-group" style={{ marginBottom: 0 }}>
                    <label className="form-label" htmlFor="writing-workspace">
                      关联文献工作空间
                      <span className="form-label-hint">可选 · 用于引用推荐</span>
                    </label>
                    <select
                      id="writing-workspace"
                      className="form-input"
                      value={createForm.workspace_id}
                      onChange={e => setCreateForm(f => ({ ...f, workspace_id: e.target.value }))}
                      disabled={creating}
                    >
                      <option value="">不关联</option>
                      {workspaces.map(w => (
                        <option key={w.id} value={w.id}>
                          {w.name}（{w.literature_count} 篇文献）
                        </option>
                      ))}
                    </select>
                  </div>
                )}

                {creating && (
                  <div className="writing-create-loading">
                    <Loader size={28} className="spinner" />
                    <p>正在创建项目并生成大纲…</p>
                  </div>
                )}
              </div>

              <div className="writing-create-footer">
                <p className="writing-create-tip">
                  <Sparkle size={14} />
                  {createForm.topic.trim()
                    ? '创建后将自动生成 IMRaD 章节结构与写作要点'
                    : '填写研究主题可启用 AI 大纲生成'}
                </p>
                <div className="form-actions writing-create-actions">
                  <button
                    type="button"
                    className="btn btn-outline"
                    onClick={closeCreateModal}
                    disabled={creating}
                  >
                    取消
                  </button>
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={handleCreate}
                    disabled={creating || !createForm.title.trim()}
                  >
                    {creating ? (
                      <><Loader size={16} className="spinner" /> 创建中…</>
                    ) : (
                      <><Plus size={16} /> 创建项目</>
                    )}
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {listLoading && projects.length === 0 ? (
          <div className="writing-skeleton-grid">
            {[1, 2, 3].map(i => <div key={i} className="writing-skeleton-card" />)}
          </div>
        ) : projects.length === 0 ? (
          <div className="writing-empty-state">
            <div className="writing-empty-icon"><FileText size={40} strokeWidth={1.2} /></div>
            <h3>开始你的第一篇论文</h3>
            <p>创建写作项目，系统将按 IMRaD 结构生成章节框架</p>
            <button className="btn btn-primary" onClick={() => setShowCreate(true)}>
              <Plus size={16} /> 新建项目
            </button>
          </div>
        ) : (
          <div className="writing-project-list">
            {projects.map(p => (
              <article
                key={p.id}
                className="writing-project-card"
                onClick={() => openProject(p.id)}
                role="button"
                tabIndex={0}
                onKeyDown={e => { if (e.key === 'Enter') openProject(p.id) }}
              >
                <div className="writing-card-top">
                  <span className={`writing-badge writing-badge-${p.paper_type}`}>
                    {PAPER_TYPE_LABELS[p.paper_type]}
                  </span>
                  <button
                    type="button"
                    className="btn-icon writing-card-delete"
                    title="删除项目"
                    onClick={e => handleDelete(p.id, e)}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
                <h3>{p.title}</h3>
                <p className="writing-card-topic">{p.topic || '未设置研究主题'}</p>
                <div className="writing-card-footer">
                  <span><Clock size={12} /> {formatRelativeTime(p.updated_at)}</span>
                  {p.workspace_id && (
                    <span className="writing-card-workspace" title="已关联文献工作空间">
                      <Link2 size={12} /> {getWorkspaceName(p.workspace_id)}
                    </span>
                  )}
                  {p.target_journal && <span className="writing-card-journal">{p.target_journal}</span>}
                </div>
              </article>
            ))}
          </div>
        )}

        {toast && <div className="writing-toast">{toast}</div>}
      </div>
    )
  }

  return (
    <div className="writing-page writing-editor-view">
      <header className="writing-editor-header">
        <button type="button" className="btn btn-outline writing-back-btn" onClick={handleBackToList} title="返回项目列表">
          <ChevronLeft size={18} />
        </button>
        <div className="writing-editor-title">
          <h2>{activeProject.title}</h2>
          <div className="writing-editor-meta">
            <span className={`writing-badge writing-badge-${activeProject.paper_type}`}>
              {PAPER_TYPE_LABELS[activeProject.paper_type]}
            </span>
            <span>{totalWords} 字</span>
            <span>{completedSections}/{activeProject.sections.length} 章节已完成</span>
            {activeProject.workspace_id ? (
              <span className="writing-workspace-badge linked" title="已关联文献工作空间">
                <Link2 size={12} />
                {getWorkspaceName(activeProject.workspace_id)}
              </span>
            ) : workspaces.length > 0 && (
              <select
                className="writing-workspace-inline-select"
                value=""
                onChange={e => { if (e.target.value) handleWorkspaceLink(e.target.value) }}
                title="关联文献工作空间"
                aria-label="关联文献工作空间"
              >
                <option value="">关联文献库…</option>
                {workspaces.map(w => (
                  <option key={w.id} value={w.id}>{w.name}</option>
                ))}
              </select>
            )}
          </div>
        </div>
        <div className="writing-header-actions">
          <button
            type="button"
            className="btn btn-outline"
            onClick={() => { setCompleteOutlineResult(null); setShowCompleteOutline(true) }}
            title="按章节目录与大纲自动补全整篇论文"
          >
            <Sparkles size={14} /> 目录补全全文
          </button>
          <button
            type="button"
            className="btn btn-outline"
            onClick={() => setShowFullPreview(true)}
            title={hasPreviewContent ? '预览整篇论文排版效果' : '暂无章节内容'}
          >
            <BookOpen size={14} /> 整体预览
          </button>
          <div className="writing-export-anchor">
            <button
              type="button"
              className="btn btn-outline"
              onClick={e => { e.stopPropagation(); setShowExportMenu(v => !v) }}
              disabled={exporting || totalWords === 0}
              title={totalWords === 0 ? '请先撰写内容' : '导出论文'}
            >
              {exporting ? <Loader size={14} className="spinner" /> : <Download size={14} />}
              导出
            </button>
            {showExportMenu && (
              <div className="writing-export-menu" onClick={e => e.stopPropagation()}>
                <button type="button" onClick={() => handleExport('md')}>
                  <FileText size={14} /> Markdown (.md)
                </button>
                <button type="button" onClick={() => handleExport('docx')}>
                  <FileText size={14} /> Word (.docx)
                </button>
              </div>
            )}
          </div>
          {activeProject.source_workflow_id && (
            <button type="button" className="btn btn-outline" onClick={handleFillMethods} disabled={toolLoading}>
              <FileText size={14} /> 填充 Methods
            </button>
          )}
          <div className={`writing-save-indicator writing-save-${saveStatus}`}>
            {saveStatus === 'saving' && <Loader size={12} className="spinner" />}
            {saveStatus === 'saved' && <Check size={12} />}
            {saveStatus === 'unsaved' && <span className="writing-unsaved-dot" />}
            <span>
              {saveStatus === 'saving' ? '保存中' : saveStatus === 'unsaved' ? '未保存' : '已保存'}
            </span>
          </div>
          <button type="button" className="btn btn-primary" onClick={() => saveSection()} disabled={saving || !hasUnsaved}>
            <Save size={14} /> 保存
          </button>
        </div>
      </header>

      {error && (
        <div className="writing-error-banner">
          <AlertCircle size={16} /><span>{error}</span>
          <button type="button" className="writing-error-close" onClick={() => setError('')} aria-label="关闭"><X size={14} /></button>
        </div>
      )}

      {editorLoading ? (
        <div className="writing-editor-loading">
          <Loader size={32} className="spinner" />
          <p>加载项目中...</p>
        </div>
      ) : (
        <div
          className={[
            'writing-editor-layout',
            outlineNavCollapsed && 'outline-nav-collapsed',
            toolsPanelCollapsed && 'tools-panel-collapsed',
          ].filter(Boolean).join(' ')}
        >
          {outlineNavCollapsed ? (
            <button
              type="button"
              className="writing-outline-nav-expand"
              title="显示章节栏"
              onClick={() => setOutlineNavCollapsed(false)}
            >
              <ChevronRight size={14} />
              <span>章节</span>
            </button>
          ) : (
          <aside className="writing-outline-nav">
            <div className="writing-outline-nav-header">
              <h4><List size={14} /> 章节</h4>
              <div className="writing-outline-nav-actions">
                <button
                  type="button"
                  className="btn-icon writing-outline-nav-hide-btn"
                  title="隐藏章节栏"
                  onClick={() => setOutlineNavCollapsed(true)}
                >
                  <ChevronLeft size={14} />
                </button>
                <button
                  type="button"
                  className="btn-icon writing-manage-sections-btn"
                  title="管理章节"
                  onClick={() => setShowSectionManager(true)}
                >
                  <Pencil size={14} />
                </button>
              </div>
            </div>
            <nav className="writing-section-tree">
              {activeProject.sections.map(sec => {
                const outlineForSection = activeProject.outline?.find(o => o.section_type === sec.section_type)
                return (
                  <SectionTreeNode
                    key={sec.id}
                    section={sec}
                    displayName={sectionTitle(sec)}
                    outlineSubsections={outlineForSection?.subsections}
                    isActive={activeSection?.id === sec.id}
                    isExpanded={expandedSections.has(sec.id)}
                    activeSubheadingKey={activeSubheadingKey}
                    activeSectionId={activeSection?.id ?? null}
                    editContent={editContent}
                    figureHintCount={figureHintCountFor(sec.id)}
                    onToggleExpand={() => toggleSectionExpanded(sec.id)}
                    onSelect={() => selectSection(sec)}
                    onJumpToSubheading={line => jumpToSubheading(sec, line)}
                    onInsertHeading={(level, title) => handleInsertHeadingInSection(sec, level, title)}
                  />
                )
              })}
            </nav>

            {outlineItem && (
              <div className="writing-outline-panel">
                <button
                  type="button"
                  className="writing-outline-toggle"
                  onClick={() => setOutlineExpanded(v => !v)}
                >
                  <span>大纲要点</span>
                  {outlineExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                </button>
                {outlineExpanded && (
                  <div className="writing-outline-body">
                    {outlineItem.subsections && outlineItem.subsections.length > 0 ? (
                      <ul className="writing-outline-subsections">
                        {outlineItem.subsections.map((sub, i) => (
                          <li
                            key={`${sub.level}-${sub.title}-${i}`}
                            className={`writing-outline-subsection level-${sub.level}`}
                          >
                            <div className="writing-outline-subsection-head">
                              <span className="writing-subsection-level">H{sub.level}</span>
                              <span>{sub.title}</span>
                              <button
                                type="button"
                                className="writing-subsection-insert-btn"
                                title={`插入${SUBHEADING_LEVEL_LABELS[sub.level]}`}
                                onClick={() => activeSection && handleInsertHeadingInSection(activeSection, sub.level, sub.title)}
                              >
                                插入
                              </button>
                            </div>
                            {sub.outline_points && sub.outline_points.length > 0 && (
                              <ul>
                                {sub.outline_points.map((p, j) => <li key={j}>{p}</li>)}
                              </ul>
                            )}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <ul>{outlineItem.outline_points?.map((p, i) => <li key={i}>{p}</li>)}</ul>
                    )}
                    {outlineItem.writing_hints && <p className="hint-text">{outlineItem.writing_hints}</p>}
                  </div>
                )}
              </div>
            )}

          </aside>
          )}

          <div className="writing-editor-main">
            <div className="writing-editor-toolbar">
              <div className="toolbar-left">
                <span className="writing-section-name">
                  {activeSection ? sectionTitle(activeSection) : ''}
                </span>
                {activeSection && (
                  <span className="writing-toolbar-stat">v{activeSection.version}</span>
                )}
                <span className="writing-toolbar-stat">{editContent.length} 字符</span>
                {activeSection && figureHintCountFor(activeSection.id) > 0 && (
                  <button
                    type="button"
                    className="writing-toolbar-stat writing-toolbar-figure-hint"
                    title="运行「图表完整」检查并查看建议位置"
                    onClick={() => { setToolTab('check'); void runCheck('figures') }}
                  >
                    📊 建议插图 {figureHintCountFor(activeSection.id)}
                  </button>
                )}
              </div>
              <div className="toolbar-right">
                {!isAbstractSection(activeSection?.section_type ?? '') && (
                <div className="writing-heading-toolbar" role="toolbar" aria-label="小节标题">
                  {([2, 3, 4] as const).map(level => (
                    <button
                      key={level}
                      type="button"
                      className="btn btn-outline writing-heading-btn"
                      title={`插入${SUBHEADING_LEVEL_LABELS[level]}（Markdown ${'#'.repeat(level)}）`}
                      onClick={() => handleInsertHeading(level)}
                    >
                      <Heading2 size={14} />
                      <span>H{level}</span>
                    </button>
                  ))}
                </div>
                )}
                <button
                  type="button"
                  className={`btn btn-outline writing-preview-toggle ${showPreview ? 'active' : ''}`}
                  onClick={() => setShowPreview(v => !v)}
                >
                  <Eye size={14} /> {showPreview ? '隐藏预览' : '显示预览'}
                </button>
              </div>
            </div>
            <div className="writing-editor-split">
              {activeIsBibliography && (
                <div className="writing-bibliography-banner">
                  <BookMarked size={14} />
                  <span>「{BIBLIOGRAPHY_SECTION_TITLE}」章节由引用自动维护，应用引用后将自动更新</span>
                </div>
              )}
              {!showPreview ? (
                <textarea
                  ref={textareaRef}
                  className="writing-textarea"
                  value={editContent}
                  onChange={e => setEditContent(e.target.value)}
                  readOnly={activeIsBibliography}
                  placeholder={
                    activeIsBibliography
                      ? '参考文献将在应用引用后自动生成…'
                      : activeSection?.section_type === 'abstract'
                      ? '在此撰写中文摘要，约300字，连贯段落，不要使用标题…\n\nCtrl+S 快速保存'
                      : activeSection?.section_type === 'abstract_en'
                        ? 'Write the English Abstract here (~250-300 words, continuous paragraphs, no headings)…\n\nCtrl+S to save'
                        : `在此撰写${activeSection ? sectionTitle(activeSection) : ''}…\n\n支持 Markdown；可用工具栏插入二/三/四级小节标题（##、###、####），Ctrl+S 快速保存`
                  }
                />
              ) : (
                <div className="writing-preview markdown-body">
                  <WritingMarkdownPreview
                    content={editContent || '*暂无内容，返回编辑模式后可输入正文*'}
                    hints={activeSection
                      ? figureHints.filter(
                          h => h.section_id === activeSection.id
                            && (!h.key || !ignoredFigureKeys.has(h.key)),
                        )
                      : []}
                    assetUrlFor={activeProject
                      ? assetId => writingAssetUrl(activeProject.id, assetId)
                      : undefined}
                  />
                </div>
              )}
            </div>
          </div>

          {toolsPanelCollapsed ? (
            <button
              type="button"
              className="writing-tools-panel-expand"
              title="显示操作栏"
              onClick={() => setToolsPanelCollapsed(false)}
            >
              <ChevronLeft size={14} />
              <span>操作</span>
            </button>
          ) : (
          <aside className="writing-tools-panel">
            <div className="writing-tools-panel-header">
              <h4><Sparkles size={14} /> 操作</h4>
              <button
                type="button"
                className="btn-icon writing-tools-panel-hide-btn"
                title="隐藏操作栏"
                onClick={() => setToolsPanelCollapsed(true)}
              >
                <ChevronRight size={14} />
              </button>
            </div>
            <div className="writing-tool-tabs">
              {([
                ['expand', '扩写', Maximize2],
                ['polish', '润色', Wand2],
                ['check', '检查', CheckCircle],
                ['citation', '引用', BookMarked],
                ['version', '版本', History],
              ] as const).map(([id, label, Icon]) => (
                <button
                  key={id}
                  type="button"
                  className={`writing-tool-tab ${toolTab === id ? 'active' : ''}`}
                  onClick={() => { setToolTab(id); setToolResult(null); if (id === 'version') loadVersions() }}
                >
                  <Icon size={15} />
                  <span>{label}</span>
                </button>
              ))}
            </div>

            <div className="writing-tool-body">
              {toolLoading && (
                <div className="writing-tool-loading">
                  <Loader size={24} className="spinner" />
                  <span>AI 处理中...</span>
                </div>
              )}

              {toolTab === 'expand' && (
                <div className={`writing-tool-section ${toolLoading ? 'dimmed' : ''}`}>
                  <p className="writing-tool-desc">
                    {activeSection?.section_type === 'abstract'
                      ? '中文摘要为约300字的连贯段落，不使用小节标题'
                      : activeSection?.section_type === 'abstract_en'
                        ? 'English Abstract: ~250-300 words, no subheadings'
                        : '按整章或目录结构扩写，优化学术表达与论述层次'}
                  </p>
                  {!isAbstractSection(activeSection?.section_type ?? '') && (
                  <div className="writing-segmented writing-segmented-wrap">
                    {([
                      ['free', '自由扩写'],
                      ['structured', '本章目录'],
                    ] as const).map(([mode, label]) => (
                      <button
                        key={mode}
                        type="button"
                        className={expandMode === mode ? 'active' : ''}
                        onClick={() => setExpandMode(mode)}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                  )}

                  {(expandMode === 'free' || isAbstractSection(activeSection?.section_type ?? '')) ? (
                    <>
                      <div className="writing-segmented">
                        {([
                          ['short', '适度'],
                          ['medium', '充实'],
                          ['long', '全面'],
                        ] as const).map(([len, label]) => (
                          <button
                            key={len}
                            type="button"
                            className={expandLength === len ? 'active' : ''}
                            onClick={() => setExpandLength(len)}
                          >
                            {label}
                          </button>
                        ))}
                      </div>
                      <button type="button" className="btn btn-primary writing-tool-action" onClick={runExpand} disabled={toolLoading || !editContent.trim()}>
                        <Maximize2 size={14} /> 智能扩写
                      </button>
                    </>
                  ) : (
                    <>
                      <p className="writing-tool-desc writing-complete-outline-hint">
                        需补全整篇论文？请使用顶部 <strong>目录补全全文</strong>，将按所有章节与子节目录自动生成正文。
                      </p>
                      <label className="writing-field compact">
                        <span>全局写作要求</span>
                        <textarea
                          className="form-textarea writing-expand-requirements"
                          value={expandGlobalRequirements}
                          onChange={e => setExpandGlobalRequirements(e.target.value)}
                          placeholder="如：突出创新点、补充对比实验、避免第一人称…"
                          rows={2}
                        />
                      </label>
                      <div className="writing-expand-structure-toolbar">
                        <span className="writing-expand-structure-count">
                          已加载 {expandStructureItems.length} 个小节
                        </span>
                        <button
                          type="button"
                          className="btn btn-outline btn-sm"
                          onClick={() => loadExpandStructure(true)}
                          disabled={toolLoading}
                        >
                          从目录同步
                        </button>
                      </div>
                      <div className="writing-expand-structure-list">
                        {expandStructureItems.length === 0 && (
                          <p className="writing-muted">暂无小节。请先在正文中添加 ##/###/#### 标题，或生成含子节的大纲后点击「从目录同步」。</p>
                        )}
                        {expandStructureItems.map(item => (
                          <SectionRewriteItemEditor
                            key={item.id}
                            item={item}
                            disabled={toolLoading}
                            onChange={patch => updateExpandStructureItem(item.id, patch)}
                          />
                        ))}
                      </div>
                      <button
                        type="button"
                        className="btn btn-primary writing-tool-action"
                        onClick={runStructuredExpand}
                        disabled={toolLoading || expandStructureItems.filter(i => i.enabled).length === 0}
                      >
                        <Maximize2 size={14} /> 按目录扩写
                      </button>
                    </>
                  )}

                  {toolResult?.expanded_text && toolTab === 'expand' && (
                    <div className="writing-tool-result fade-in">
                      <button
                        type="button"
                        className="btn btn-primary"
                        onClick={() => { setEditContent(toolResult.expanded_text); showToastMsg('已应用扩写结果') }}
                      >
                        应用扩写结果
                      </button>
                      <p className="writing-expand-hint">
                        {toolResult.mode === 'structured' ? '目录扩写' : '自由扩写'}
                        {' · '}
                        原 {toolResult.original_text?.length || 0} 字 → 扩写后 {toolResult.expanded_text.length} 字
                      </p>
                    </div>
                  )}
                </div>
              )}

              {toolTab === 'polish' && (
                <div className={`writing-tool-section ${toolLoading ? 'dimmed' : ''}`}>
                  <p className="writing-tool-desc">
                    {activeSection?.section_type === 'abstract'
                      ? '润色中文摘要，保持约300字'
                      : activeSection?.section_type === 'abstract_en'
                        ? 'Polish English Abstract (~250-300 words)'
                        : '优化表达，或按小节指定字数与要求重写'}
                  </p>
                  {!isAbstractSection(activeSection?.section_type ?? '') && (
                  <div className="writing-segmented writing-segmented-wrap">
                    {([
                      ['free', '整章润色'],
                      ['structured', '小节重写'],
                    ] as const).map(([mode, label]) => (
                      <button
                        key={mode}
                        type="button"
                        className={polishMode === mode ? 'active' : ''}
                        onClick={() => setPolishMode(mode)}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                  )}
                  <div className="writing-segmented writing-segmented-wrap">
                    {([
                      ['conservative', '保守'],
                      ['moderate', '中等'],
                      ['deep', '深度'],
                    ] as const).map(([k, label]) => (
                      <button
                        key={k}
                        type="button"
                        className={polishStyle === k ? 'active' : ''}
                        onClick={() => setPolishStyle(k)}
                      >
                        {label}
                      </button>
                    ))}
                  </div>

                  {(polishMode === 'free' || isAbstractSection(activeSection?.section_type ?? '')) ? (
                    <button
                      type="button"
                      className="btn btn-primary writing-tool-action"
                      onClick={runPolish}
                      disabled={toolLoading || !editContent.trim()}
                    >
                      <Wand2 size={14} /> 学术润色
                    </button>
                  ) : (
                    <>
                      <label className="writing-field compact">
                        <span>全局重写要求</span>
                        <textarea
                          className="form-textarea writing-expand-requirements"
                          value={polishGlobalRequirements}
                          onChange={e => setPolishGlobalRequirements(e.target.value)}
                          placeholder="如：统一被动语态、删除口语化表达、术语与摘要保持一致…"
                          rows={2}
                        />
                      </label>
                      <div className="writing-expand-structure-toolbar">
                        <span className="writing-expand-structure-count">
                          已加载 {polishStructureItems.length} 个小节
                        </span>
                        <button
                          type="button"
                          className="btn btn-outline btn-sm"
                          onClick={() => loadPolishStructure(true)}
                          disabled={toolLoading}
                        >
                          从目录同步
                        </button>
                      </div>
                      <div className="writing-expand-structure-list">
                        {polishStructureItems.length === 0 && (
                          <p className="writing-muted">暂无小节。请先在正文中添加标题，或点击「从目录同步」加载大纲子节。</p>
                        )}
                        {polishStructureItems.map(item => (
                          <SectionRewriteItemEditor
                            key={item.id}
                            item={item}
                            disabled={toolLoading}
                            requirementLabel="小节重写要求"
                            requirementPlaceholder="如：压缩至目标字数、补充数据解读、改为第三人称…"
                            onChange={patch => updatePolishStructureItem(item.id, patch)}
                          />
                        ))}
                      </div>
                      <button
                        type="button"
                        className="btn btn-primary writing-tool-action"
                        onClick={runStructuredPolish}
                        disabled={toolLoading || polishStructureItems.filter(i => i.enabled).length === 0}
                      >
                        <Wand2 size={14} /> 按小节润色/重写
                      </button>
                    </>
                  )}

                  {toolResult?.polished_text && toolTab === 'polish' && (
                    <div className="writing-tool-result fade-in">
                      <button
                        type="button"
                        className="btn btn-primary"
                        onClick={() => { setEditContent(toolResult.polished_text); showToastMsg('已应用润色结果') }}
                      >
                        应用润色结果
                      </button>
                      {toolResult.mode === 'structured' && (
                        <p className="writing-expand-hint">小节重写模式</p>
                      )}
                      {toolResult.changes_summary?.map((c: string, i: number) => (
                        <p key={i} className="writing-change-item">{c}</p>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {toolTab === 'check' && (
                <div className={`writing-tool-section ${toolLoading ? 'dimmed' : ''}`}>
                  <p className="writing-tool-desc">多维度检查论文质量</p>

                  <div className="writing-keywords-panel">
                    <h5><Hash size={14} /> 关键词设置</h5>
                    <label className="writing-field compact">
                      <span>中文关键词（3–5 个，分号分隔）</span>
                      <input
                        className="form-input"
                        value={keywordsZhInput}
                        onChange={e => setKeywordsZhInput(e.target.value)}
                        placeholder="深度学习；医学图像；语义分割"
                        disabled={toolLoading}
                      />
                    </label>
                    <label className="writing-field compact">
                      <span>英文 Keywords</span>
                      <input
                        className="form-input"
                        value={keywordsEnInput}
                        onChange={e => setKeywordsEnInput(e.target.value)}
                        placeholder="deep learning; medical imaging; semantic segmentation"
                        disabled={toolLoading}
                      />
                    </label>
                    <div className="writing-keywords-actions">
                      <button
                        type="button"
                        className="btn btn-outline btn-sm"
                        onClick={() => runCheck('keywords_generate')}
                        disabled={toolLoading}
                      >
                        <Sparkles size={12} /> 从摘要生成
                      </button>
                      <button
                        type="button"
                        className="btn btn-outline btn-sm"
                        onClick={saveKeywords}
                        disabled={toolLoading}
                      >
                        <Save size={12} /> 保存关键词
                      </button>
                    </div>
                  </div>

                  <div className="writing-check-grid">
                    {([
                      ['terminology', '术语一致'],
                      ['coherence', '逻辑连贯'],
                      ['style', '表达规范'],
                      ['citation', '引用完整'],
                      ['figures', '图表完整'],
                      ['abstract_keywords', 'Abstract 检查'],
                      ['blank_lines', '去除空行'],
                    ] as const).map(([k, label]) => (
                      <button key={k} type="button" className="btn btn-outline" onClick={() => runCheck(k)} disabled={toolLoading}>
                        {label}
                      </button>
                    ))}
                  </div>
                  {toolResult && (
                    <div className="writing-tool-result fade-in">
                      {toolResult.type === 'blank_lines' ? (
                        <>
                          <p className="writing-result-summary">{toolResult.summary}</p>
                          {toolResult.changed && (
                            <button
                              type="button"
                              className="btn btn-primary"
                              onClick={() => {
                                setEditContent(toolResult.cleaned_text)
                                showToastMsg('已应用去空行结果')
                              }}
                            >
                              应用整理结果
                            </button>
                          )}
                        </>
                      ) : toolResult.type === 'keywords_generate' ? (
                        <>
                          <p className="writing-result-summary">{toolResult.summary}</p>
                          <div className="writing-keywords-result">
                            {toolResult.keywords_zh?.map((kw: string, i: number) => (
                              <span key={i} className="writing-keyword-chip">{kw}</span>
                            ))}
                          </div>
                        </>
                      ) : toolResult.type === 'abstract_keywords' ? (
                        <>
                          <p className="writing-result-summary">{toolResult.summary}</p>
                          <div className="writing-abstract-check-status">
                            <span className={toolResult.abstract_en_ok ? 'ok' : 'warn'}>
                              Abstract {toolResult.abstract_en_ok ? '✓ 英文' : '✗ 需修正'}
                            </span>
                            <span className={toolResult.keywords_en_ok ? 'ok' : 'warn'}>
                              Keywords {toolResult.keywords_en_ok ? '✓ 英文' : '✗ 需修正'}
                            </span>
                          </div>
                          {toolResult.abstract_en_suggested && (
                            <div className="writing-check-card severity-low">
                              <strong>建议 Abstract</strong>
                              <p className="writing-suggested-text">{toolResult.abstract_en_suggested.slice(0, 280)}{toolResult.abstract_en_suggested.length > 280 ? '…' : ''}</p>
                            </div>
                          )}
                          {toolResult.keywords_en_suggested?.length > 0 && (
                            <div className="writing-check-card severity-low">
                              <strong>建议 Keywords</strong>
                              <p>{toolResult.keywords_en_suggested.join('; ')}</p>
                            </div>
                          )}
                          {(toolResult.issues || []).map((item: any, i: number) => (
                            <div key={i} className={`writing-check-card severity-${item.severity || 'medium'}`}>
                              <strong>{item.description}</strong>
                              <p>{item.suggestion}</p>
                            </div>
                          ))}
                          {toolResult.needs_fix && (
                            <button
                              type="button"
                              className="btn btn-primary writing-tool-action"
                              onClick={applyAbstractKeywordsFix}
                              disabled={toolLoading}
                            >
                              应用 Abstract / Keywords 修正
                            </button>
                          )}
                        </>
                      ) : toolResult.type === 'figures' ? (
                        <FigureCheckPanel
                          report={toolResult}
                          activeSection={activeSection}
                          ignoredKeys={ignoredFigureKeys}
                          onInsertPlaceholder={handleInsertFigurePlaceholder}
                          onIgnore={handleIgnoreFigure}
                          ensureCandidates={ensureCandidates}
                          onInsertAsset={handleInsertRealAsset}
                          assetCandidates={assetCandidates}
                          assetBusy={assetBusy}
                          expandedAssetPickerKey={expandedAssetPickerKey}
                          setExpandedAssetPickerKey={setExpandedAssetPickerKey}
                          candidatesError={candidatesError}
                        />
                      ) : (
                        <>
                      {(toolResult.overall_score ?? toolResult.score) != null && (
                        <div className="writing-score-ring">
                          <span className="score-value">{toolResult.overall_score ?? toolResult.score}</span>
                          <span className="score-label">分</span>
                        </div>
                      )}
                      {toolResult.summary && <p className="writing-result-summary">{toolResult.summary}</p>}
                      {(toolResult.issues || toolResult.terms || toolResult.missing_citations || []).map((item: any, i: number) => (
                        <div key={i} className={`writing-check-card severity-${item.severity || 'medium'}`}>
                          <strong>{item.description || item.concept || item.text}</strong>
                          <p>{item.suggestion || item.recommended || item.reason}</p>
                        </div>
                      ))}
                        </>
                      )}
                    </div>
                  )}
                </div>
              )}

              {toolTab === 'citation' && (
                <div className={`writing-tool-section ${toolLoading ? 'dimmed' : ''}`}>
                  <p className="writing-tool-desc">选中正文后推荐文献，点击「应用引用」插入上标编号；参考文献将自动追加为最后一章</p>
                  {workspaces.length > 0 && (
                    <label className="writing-field compact">
                      <span>文献工作空间</span>
                      <select
                        value={activeProject.workspace_id || ''}
                        onChange={e => handleWorkspaceLink(e.target.value)}
                      >
                        <option value="">未关联</option>
                        {workspaces.map(w => (
                          <option key={w.id} value={w.id}>
                            {w.name}（{w.literature_count} 篇）
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                  {!activeProject.workspace_id && (
                    <p className="writing-muted writing-workspace-hint">
                      请先关联文献助手中的工作空间，以启用智能引用推荐
                    </p>
                  )}
                  <button type="button" className="btn btn-primary writing-tool-action" onClick={runCitationRecommend} disabled={toolLoading || !activeProject.workspace_id}>
                    <BookMarked size={14} /> 推荐引用
                  </button>
                  <label className="writing-field compact">
                    <span>引用格式</span>
                    <select
                      value={activeProject.citation_format}
                      onChange={e => handleCitationFormatChange(e.target.value as CitationFormat)}
                    >
                      {Object.entries(CITATION_FORMAT_LABELS).map(([k, v]) => (
                        <option key={k} value={k}>{v}</option>
                      ))}
                    </select>
                  </label>
                  {toolResult?.recommendations?.map((rec: any, i: number) => (
                    <div key={i} className="writing-citation-card fade-in">
                      <div className="citation-score">{Math.round((rec.relevance_score || 0) * 100)}%</div>
                      <div className="writing-citation-card-body">
                        <strong>{rec.literature?.title || rec.literature_id}</strong>
                        <p>{rec.reason}</p>
                        {rec.excerpt && (
                          <blockquote className="writing-citation-excerpt">{rec.excerpt}</blockquote>
                        )}
                        {rec.literature?.authors?.length > 0 && (
                          <p className="writing-citation-authors">
                            {rec.literature.authors.slice(0, 3).join(', ')}
                            {rec.literature.year ? ` (${rec.literature.year})` : ''}
                          </p>
                        )}
                        <button
                          type="button"
                          className="btn btn-primary btn-sm writing-citation-apply"
                          disabled={!!applyingCitationId || activeIsBibliography}
                          onClick={() => applyCitation(rec)}
                        >
                          {applyingCitationId === rec.literature_id ? (
                            <><Loader size={12} className="spinner" /> 插入中…</>
                          ) : (
                            <><BookMarked size={12} /> 应用引用</>
                          )}
                        </button>
                      </div>
                    </div>
                  ))}
                  {toolResult?.lastApplied && (
                    <div className="writing-citation-applied fade-in">
                      <Check size={14} />
                      <span>
                        已插入 {toolResult.lastApplied.citation_marker}
                        {toolResult.lastApplied.is_new_reference ? '（新增参考文献）' : '（复用已有编号）'}
                      </span>
                    </div>
                  )}
                  {(toolResult?.bibliography?.length > 0 || toolResult?.references?.length > 0) && (
                    <div className="writing-bibliography-preview">
                      <h5><Library size={14} /> 参考文献</h5>
                      {(toolResult.bibliography || toolResult.references).map((ref: any) => (
                        <div key={ref.index ?? ref.literature_id} className="writing-bib-item fade-in">
                          <span className="bib-index">[{ref.index}]</span>
                          <span className="bib-text">{ref.formatted}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {toolTab === 'version' && (
                <div className={`writing-tool-section ${toolLoading ? 'dimmed' : ''}`}>
                  <p className="writing-tool-desc">版本历史 · 对比 · 回滚</p>
                  <div className="writing-version-list">
                    {versions.length === 0 && <p className="writing-muted">暂无版本记录</p>}
                    {versions.map(v => (
                      <div key={v.id} className={`writing-version-card ${v.version === activeSection?.version ? 'current' : ''}`}>
                        <div className="version-card-header">
                          <span className="version-tag">v{v.version}</span>
                          {v.version === activeSection?.version && <span className="version-current">当前</span>}
                          <span className="version-time">{formatRelativeTime(v.created_at)}</span>
                        </div>
                        <p className="version-note">{v.note} · {v.word_count} 字</p>
                        <div className="version-card-actions">
                          {v.version !== activeSection?.version && (
                            <button type="button" className="btn btn-outline btn-sm" onClick={() => handleRollback(v.version)}>
                              <RotateCcw size={12} /> 回滚
                            </button>
                          )}
                          {versions.length > 1 && v.version !== activeSection?.version && (
                            <button type="button" className="btn btn-outline btn-sm" onClick={() => handleCompare(v.version, activeSection!.version)}>
                              <GitCompare size={12} /> 对比
                            </button>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                  {compareResult && (
                    <pre className="writing-diff-view fade-in">{compareResult.diff || '无差异'}</pre>
                  )}
                </div>
              )}
            </div>
          </aside>
          )}
        </div>
      )}

      {toast && <div className="writing-toast">{toast}</div>}

      {showCompleteOutline && activeProject && (
        <div className="modal-overlay writing-complete-outline-overlay" onClick={() => !completeOutlineLoading && setShowCompleteOutline(false)}>
          <div className="modal-card writing-complete-outline-modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <div>
                <h3>按目录补全全文</h3>
                <p className="writing-full-preview-subtitle">根据章节目录、大纲要点与子节结构自动生成/补全各章正文</p>
              </div>
              <button
                type="button"
                className="icon-btn"
                onClick={() => !completeOutlineLoading && setShowCompleteOutline(false)}
                disabled={completeOutlineLoading}
                aria-label="关闭"
              >
                <X size={18} />
              </button>
            </div>
            <div className="writing-complete-outline-body">
              <label className="writing-field compact">
                <span>全局写作要求</span>
                <textarea
                  className="form-textarea writing-expand-requirements"
                  value={completeGlobalRequirements}
                  onChange={e => setCompleteGlobalRequirements(e.target.value)}
                  placeholder="如：突出创新点、与目标期刊风格一致、方法需可复现…"
                  rows={3}
                  disabled={completeOutlineLoading}
                />
              </label>
              <label className="writing-complete-skip-filled">
                <input
                  type="checkbox"
                  checked={completeSkipFilled}
                  onChange={e => setCompleteSkipFilled(e.target.checked)}
                  disabled={completeOutlineLoading}
                />
                <span>跳过已有内容的章节（默认跳过字数 ≥ 80 的章节，保留已写内容）</span>
              </label>
              <div className="writing-complete-outline-plan">
                <div className="writing-complete-outline-plan-title">将按以下目录结构处理：</div>
                <ul>
                  {activeProject.sections.map(sec => {
                    const outlineSec = activeProject.outline?.find(o => o.section_type === sec.section_type)
                    const subCount = outlineSec?.subsections?.length || outlineSec?.outline_points?.length || 0
                    const willSkip = completeSkipFilled && sec.word_count >= 80 && sec.content.trim()
                    return (
                      <li key={sec.id} className={willSkip ? 'skipped' : ''}>
                        <strong>{sectionTitle(sec)}</strong>
                        {subCount > 0 && <span> · {subCount} 个子节/要点</span>}
                        {willSkip && <span className="tag">跳过</span>}
                      </li>
                    )
                  })}
                </ul>
              </div>
              {completeOutlineLoading && (
                <div className="writing-complete-outline-loading">
                  <Loader size={28} className="spinner" />
                  <p>正在按目录逐章补全，整篇论文可能需要数分钟，请稍候…</p>
                </div>
              )}
              {completeOutlineResult && (
                <div className="writing-complete-outline-result">
                  <p>{completeOutlineResult.summary}</p>
                  <ul>
                    {completeOutlineResult.results?.map((r: any) => (
                      <li key={r.section_id}>
                        {r.display_title} — {r.status === 'skipped' ? '已跳过' : `已生成 ${r.word_count} 字`}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
            <div className="writing-full-preview-footer">
              <span className="writing-full-preview-hint">生成后可直接在左侧目录查看各章，或使用「整体预览」查看全文</span>
              <div className="writing-complete-outline-actions">
                <button
                  type="button"
                  className="btn btn-outline"
                  onClick={() => setShowCompleteOutline(false)}
                  disabled={completeOutlineLoading}
                >
                  关闭
                </button>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={runCompleteOutline}
                  disabled={completeOutlineLoading}
                >
                  {completeOutlineLoading ? <Loader size={14} className="spinner" /> : <Sparkles size={14} />}
                  开始补全全文
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {showFullPreview && activeProject && (
        <div className="modal-overlay writing-full-preview-overlay" onClick={() => setShowFullPreview(false)}>
          <div className="modal-card writing-full-preview-modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <div>
                <h3>整体预览</h3>
                <p className="writing-full-preview-subtitle">{activeProject.title} · 含自动生成的目录</p>
              </div>
              <button
                type="button"
                className="icon-btn"
                onClick={() => setShowFullPreview(false)}
                aria-label="关闭"
              >
                <X size={18} />
              </button>
            </div>
            <div className="writing-full-preview-body markdown-body">
              <WritingMarkdownPreview
                content={fullPreviewMarkdown}
                assetUrlFor={activeProject
                  ? assetId => writingAssetUrl(activeProject.id, assetId)
                  : undefined}
              />
            </div>
            <div className="writing-full-preview-footer">
              <span className="writing-full-preview-hint">
                {hasUnsaved ? '含当前章节未保存的编辑内容' : '按章节顺序合并预览，目录根据章节与子标题自动生成'}
              </span>
              <button type="button" className="btn btn-primary" onClick={() => setShowFullPreview(false)}>
                关闭
              </button>
            </div>
          </div>
        </div>
      )}

      {showSectionManager && activeProject && (
        <div className="modal-overlay" onClick={() => !sectionManagerLoading && setShowSectionManager(false)}>
          <div className="modal-card writing-section-manager" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h3>管理章节</h3>
              <button
                type="button"
                className="icon-btn"
                onClick={() => setShowSectionManager(false)}
                disabled={sectionManagerLoading}
                aria-label="关闭"
              >
                <X size={18} />
              </button>
            </div>
            <p className="writing-section-manager-desc">
              可重命名任意章节、添加自定义章节、调整顺序。内置章节不可删除。
            </p>
            <div className="writing-section-manager-list">
              {activeProject.sections.map((sec, idx) => (
                <SectionManagerRow
                  key={sec.id}
                  section={sec}
                  displayName={sectionTitle(sec)}
                  isFirst={idx === 0}
                  isLast={idx === activeProject.sections.length - 1}
                  disabled={sectionManagerLoading}
                  onRename={handleRenameSection}
                  onDelete={handleDeleteSection}
                  onMove={handleMoveSection}
                />
              ))}
            </div>
            <div className="writing-section-add">
              <input
                className="form-input"
                value={newSectionTitle}
                onChange={e => setNewSectionTitle(e.target.value)}
                placeholder="新章节名称，如：附录、符号说明"
                disabled={sectionManagerLoading}
                onKeyDown={e => { if (e.key === 'Enter') handleAddSection() }}
              />
              <button
                type="button"
                className="btn btn-primary"
                onClick={handleAddSection}
                disabled={sectionManagerLoading || !newSectionTitle.trim()}
              >
                <Plus size={14} /> 添加
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function SectionRewriteItemEditor({
  item,
  disabled,
  onChange,
  requirementLabel = '小节写作要求',
  requirementPlaceholder = '如：引用近 5 年文献、突出方法对比…',
}: {
  item: ExpandStructureItem
  disabled: boolean
  onChange: (patch: Partial<ExpandStructureItem>) => void
  requirementLabel?: string
  requirementPlaceholder?: string
}) {
  return (
    <div className={`writing-expand-structure-item level-${item.level} ${item.enabled ? '' : 'disabled'}`}>
      <div className="writing-expand-structure-item-head">
        <label className="writing-expand-structure-check">
          <input
            type="checkbox"
            checked={item.enabled}
            disabled={disabled}
            onChange={e => onChange({ enabled: e.target.checked })}
          />
          <span className="writing-subsection-level">H{item.level}</span>
        </label>
        <input
          className="form-input"
          value={item.title}
          disabled={disabled}
          onChange={e => onChange({ title: e.target.value })}
          placeholder="小节标题"
        />
        <select
          className="form-input writing-expand-level-select"
          value={item.level}
          disabled={disabled}
          onChange={e => onChange({ level: Number(e.target.value) as ExpandStructureItem['level'] })}
        >
          <option value={2}>H2</option>
          <option value={3}>H3</option>
          <option value={4}>H4</option>
        </select>
        <label className="writing-expand-word-target">
          <span>字数</span>
          <input
            type="number"
            min={50}
            max={8000}
            step={50}
            value={item.wordTarget}
            disabled={disabled}
            onChange={e => onChange({ wordTarget: Math.max(50, Number(e.target.value) || 0) })}
          />
        </label>
      </div>
      <label className="writing-field compact">
        <span>{requirementLabel}</span>
        <textarea
          className="form-textarea writing-expand-requirements"
          value={item.requirements}
          disabled={disabled}
          onChange={e => onChange({ requirements: e.target.value })}
          placeholder={requirementPlaceholder}
          rows={2}
        />
      </label>
      {item.outlinePoints.length > 0 && (
        <div className="writing-expand-outline-points">
          <span>大纲要点</span>
          <ul>{item.outlinePoints.map((point, i) => <li key={i}>{point}</li>)}</ul>
        </div>
      )}
      {item.existingContent && (
        <p className="writing-expand-existing-hint">已有内容约 {item.existingContent.length} 字</p>
      )}
    </div>
  )
}

function FigureCheckPanel({
  report,
  activeSection,
  ignoredKeys,
  onInsertPlaceholder,
  onIgnore,
  ensureCandidates,
  onInsertAsset,
  assetCandidates,
  assetBusy,
  expandedAssetPickerKey,
  setExpandedAssetPickerKey,
  candidatesError,
}: {
  report: any
  activeSection: WritingSection | null
  ignoredKeys: Set<string>
  onInsertPlaceholder: (issue: FigureHintItem) => void
  onIgnore: (issue: FigureHintItem) => void
  ensureCandidates: () => void
  onInsertAsset: (issue: FigureHintItem, cand: any) => void
  assetCandidates: any
  assetBusy: boolean
  expandedAssetPickerKey: string | null
  setExpandedAssetPickerKey: (key: string | null) => void
  candidatesError: string
}) {
  const issues: FigureHintItem[] = (report.issues || []).filter(
    (i: FigureHintItem) => i.key ? !ignoredKeys.has(i.key) : true,
  )
  const togglePicker = (key: string) => {
    if (expandedAssetPickerKey === key) {
      setExpandedAssetPickerKey(null)
      return
    }
    setExpandedAssetPickerKey(key)
    ensureCandidates()
  }
  return (
    <div className="writing-figures-panel">
      <div className="writing-figures-stats">
        <span>全文已有 {report.figure_count ?? 0} 张图 · {report.table_count ?? 0} 张表</span>
        {report.used_llm ? <span className="writing-chip">AI 语义检查</span> : null}
      </div>
      {report.summary && <p className="writing-result-summary">{report.summary}</p>}
      {issues.length === 0 ? (
        <p className="writing-muted">未发现明显缺图表的位置 🎉</p>
      ) : (
        issues.map((issue: FigureHintItem, i: number) => {
          const isCurrent = !!issue.section_id && !!activeSection && issue.section_id === activeSection.id
          const pickerOpen = expandedAssetPickerKey === issue.key
          return (
            <div key={issue.key || i} className={`writing-check-card severity-${issue.severity || 'medium'} writing-figure-card`}>
              <div className="writing-figure-card-head">
                <strong>📊 建议插入【{issue.chart_type}】</strong>
                <span className="writing-figure-card-loc">
                  {issue.display_title || issue.section_type || '正文'} · 第 {issue.line} 行
                  {isCurrent ? ' · 当前章节' : ''}
                </span>
              </div>
              {issue.anchor_text && <p className="writing-figure-anchor">“{issue.anchor_text}”</p>}
              {issue.reason && <p className="writing-figure-reason">{issue.reason}</p>}
              {issue.suggestion && <p className="writing-figure-suggestion">{issue.suggestion}</p>}
              <div className="writing-figure-actions">
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  disabled={!isCurrent || assetBusy}
                  onClick={() => isCurrent && onInsertPlaceholder(issue)}
                  title={isCurrent ? '插入占位符（导出时自动清理）' : '请先切换到该章节'}
                >
                  插入占位
                </button>
                <button
                  type="button"
                  className="btn btn-outline btn-sm"
                  disabled={!isCurrent}
                  onClick={() => isCurrent && togglePicker(issue.key || '')}
                  title={isCurrent ? '从实验结果/文献图插入真实图表' : '请先切换到该章节'}
                >
                  素材插入{pickerOpen ? ' ▾' : ''}
                </button>
                <button
                  type="button"
                  className="btn btn-outline btn-sm"
                  onClick={() => onIgnore(issue)}
                >
                  忽略
                </button>
              </div>
              {pickerOpen && isCurrent && (
                <FigureCandidatesPicker
                  candidates={assetCandidates}
                  busy={assetBusy}
                  error={candidatesError}
                  onInsert={(cand) => onInsertAsset(issue, cand)}
                />
              )}
            </div>
          )
        })
      )}
    </div>
  )
}

function SectionTreeNode({
  section,
  displayName,
  outlineSubsections,
  isActive,
  isExpanded,
  activeSubheadingKey,
  activeSectionId,
  editContent,
  figureHintCount,
  onToggleExpand,
  onSelect,
  onJumpToSubheading,
  onInsertHeading,
}: {
  section: WritingSection
  displayName: string
  outlineSubsections?: OutlineSubsection[]
  isActive: boolean
  isExpanded: boolean
  activeSubheadingKey: string | null
  activeSectionId: string | null
  editContent: string
  figureHintCount: number
  onToggleExpand: () => void
  onSelect: () => void
  onJumpToSubheading: (line: number) => void
  onInsertHeading: (level: SubheadingLevel, title?: string) => void
}) {
  const Icon = SECTION_ICONS[section.section_type] || SECTION_ICONS.custom
  const status = sectionStatus(section.word_count)
  const headings = getSectionHeadings(section.content, activeSectionId, section.id, editContent)
  const headingTitles = new Set(headings.map(h => h.title.toLowerCase()))
  const plannedSubsections = (outlineSubsections || []).filter(
    sub => !headingTitles.has(sub.title.toLowerCase()),
  )

  return (
    <div className={`writing-section-tree-node ${isActive ? 'active-section' : ''}`}>
      <div className={`writing-section-tree-row ${isActive ? 'active' : ''} status-${status}`}>
        <button
          type="button"
          className="writing-tree-toggle"
          onClick={onToggleExpand}
          title={isExpanded ? '折叠子标题' : '展开子标题'}
          aria-expanded={isExpanded}
        >
          {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </button>
        <button
          type="button"
          className="writing-section-tree-main"
          onClick={onSelect}
        >
          <Icon size={14} className="section-icon" />
          <span className="section-label">{displayName}</span>
          {isBibliographySection(section) && (
            <span className="section-auto-badge" title="自动维护">自动</span>
          )}
          <span className="section-words">{section.word_count || '—'}</span>
          {figureHintCount > 0 && (
            <span
              className="writing-section-figure-badge"
              title={`本章节有 ${figureHintCount} 处建议配图位置，可运行「图表完整」检查`}
            >
              📊 {figureHintCount}
            </span>
          )}
        </button>
      </div>

      {isExpanded && (
        <div className="writing-section-tree-children" role="group" aria-label={`${displayName} 子标题`}>
          {headings.map((heading, i) => {
            const key = `${section.id}:${heading.line}`
            return (
              <button
                key={`${heading.line}-${heading.title}-${i}`}
                type="button"
                className={[
                  'writing-subheading-tree-item',
                  `level-${heading.level}`,
                  activeSubheadingKey === key && 'active',
                ].filter(Boolean).join(' ')}
                onClick={() => onJumpToSubheading(heading.line)}
                title={`跳转到第 ${heading.line + 1} 行`}
              >
                <span className="writing-tree-branch" aria-hidden />
                <span className="writing-subsection-level">H{heading.level}</span>
                <span className="writing-subheading-title">{heading.title}</span>
              </button>
            )
          })}

          {!isAbstractSection(section.section_type) && plannedSubsections.map((sub, i) => (
            <div
              key={`planned-${sub.level}-${sub.title}-${i}`}
              className={`writing-subheading-tree-item planned level-${sub.level}`}
            >
              <span className="writing-tree-branch" aria-hidden />
              <span className="writing-subsection-level">H{sub.level}</span>
              <span className="writing-subheading-title">{sub.title}</span>
              <button
                type="button"
                className="writing-subsection-insert-btn"
                title={`插入${SUBHEADING_LEVEL_LABELS[sub.level]}`}
                onClick={() => onInsertHeading(sub.level, sub.title)}
              >
                插入
              </button>
            </div>
          ))}

          {!isAbstractSection(section.section_type) && (
          <div className="writing-subheading-add-row">
            <span className="writing-subheading-add-label">添加子标题</span>
            <div className="writing-subheading-add-actions">
              {([2, 3, 4] as const).map(level => (
                <button
                  key={level}
                  type="button"
                  className="writing-subheading-add-btn"
                  title={`添加${SUBHEADING_LEVEL_LABELS[level]}`}
                  onClick={() => onInsertHeading(level)}
                >
                  H{level}
                </button>
              ))}
            </div>
          </div>
          )}
        </div>
      )}
    </div>
  )
}

const FIGURE_SOURCE_LABELS: Record<string, string> = {
  experiment_chart: '实验分析图',
  experiment_metric: '指标曲线',
  experiment_attachment: '实验照片',
  literature_image: '文献图',
}

function urlWithToken(url: string): string {
  const token = getToken()
  if (!token) return url
  const sep = url.includes('?') ? '&' : '?'
  return `${url}${sep}token=${encodeURIComponent(token)}`
}

function FigureCandidatesPicker({
  candidates,
  busy,
  error,
  onInsert,
}: {
  candidates: any
  busy: boolean
  error: string
  onInsert: (cand: any) => void
}) {
  if (busy) {
    return <div className="writing-candidates-state">正在加载可插入的图表素材…</div>
  }
  if (error) {
    return <div className="writing-candidates-state writing-candidates-error">{error}</div>
  }
  if (!candidates || (candidates.total ?? 0) === 0) {
    return (
      <div className="writing-candidates-state writing-candidates-empty">
        未找到可用素材：请先为写作项目关联实验记录（从同一工作方案创建）或文献工作空间，
        并在实验/文献中完成数据上传与分析。
      </div>
    )
  }
  const groups: { key: string; label: string }[] = [
    { key: 'experiment_charts', label: '实验分析图表' },
    { key: 'experiment_metrics', label: '实验指标曲线' },
    { key: 'experiment_attachments', label: '实验照片' },
    { key: 'literature_images', label: '文献配图' },
  ]
  return (
    <div className="writing-candidates-picker">
      {groups.map(group => {
        const items: any[] = candidates?.[group.key] || []
        if (!items.length) return null
        return (
          <div key={group.key} className="writing-candidates-group">
            <h6>{group.label}（{items.length}）</h6>
            <ul className="writing-candidates-list">
              {items.map((cand, idx) => {
                const title = cand.title || cand.filename
                  || `${FIGURE_SOURCE_LABELS[cand.kind] || '素材'} ${idx + 1}`
                const sub = cand.experiment_title || cand.literature_title
                  || FIGURE_SOURCE_LABELS[cand.kind] || ''
                return (
                  <li
                    key={`${group.key}-${cand.analysis_id || cand.attachment_id || cand.metric_name || cand.filename || idx}`}
                  >
                    {cand.url ? (
                      <img src={urlWithToken(cand.url)} alt="" className="writing-candidate-thumb" loading="lazy" />
                    ) : (
                      <span className="writing-candidate-thumb writing-candidate-thumb-placeholder">
                        📊
                      </span>
                    )}
                    <div className="writing-candidate-info">
                      <span className="writing-candidate-title">{title}</span>
                      <span className="writing-candidate-sub">
                        {sub}
                        {cand.page ? ` · 第 ${cand.page} 页` : ''}
                        {cand.context ? ` · ${cand.context}` : ''}
                      </span>
                    </div>
                    <button type="button" className="btn btn-outline btn-sm" onClick={() => onInsert(cand)}>
                      插入
                    </button>
                  </li>
                )
              })}
            </ul>
          </div>
        )
      })}
    </div>
  )
}

function SectionManagerRow({
  section,
  displayName,
  isFirst,
  isLast,
  disabled,
  onRename,
  onDelete,
  onMove,
}: {
  section: WritingSection
  displayName: string
  isFirst: boolean
  isLast: boolean
  disabled: boolean
  onRename: (id: string, title: string) => void
  onDelete: (section: WritingSection) => void
  onMove: (id: string, dir: 'up' | 'down') => void
}) {
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(getSectionDisplayName(section))

  useEffect(() => {
    setTitle(getSectionDisplayName(section))
  }, [section])

  const commitRename = () => {
    const next = title.trim()
    if (!next) {
      setTitle(getSectionDisplayName(section))
      setEditing(false)
      return
    }
    if (next !== getSectionDisplayName(section)) {
      onRename(section.id, next)
    }
    setEditing(false)
  }

  return (
    <div className={`writing-section-manager-row ${section.is_custom ? 'custom' : ''}`}>
      <div className="row-main">
        {editing ? (
          <input
            className="form-input"
            value={title}
            onChange={e => setTitle(e.target.value)}
            onBlur={commitRename}
            onKeyDown={e => {
              if (e.key === 'Enter') commitRename()
              if (e.key === 'Escape') { setTitle(getSectionDisplayName(section)); setEditing(false) }
            }}
            autoFocus
            disabled={disabled}
          />
        ) : (
          <button type="button" className="row-title-btn" onClick={() => setEditing(true)} disabled={disabled}>
            <span>{displayName}</span>
            {section.is_custom && <span className="custom-tag">自定义</span>}
            {!section.is_custom && section.title && <span className="renamed-tag">已重命名</span>}
            <Pencil size={12} />
          </button>
        )}
        <span className="row-meta">{section.word_count} 字</span>
      </div>
      <div className="row-actions">
        <button type="button" className="btn-icon" title="上移" disabled={disabled || isFirst} onClick={() => onMove(section.id, 'up')}>
          <ArrowUp size={14} />
        </button>
        <button type="button" className="btn-icon" title="下移" disabled={disabled || isLast} onClick={() => onMove(section.id, 'down')}>
          <ArrowDown size={14} />
        </button>
        {section.is_custom && (
          <button type="button" className="btn-icon danger" title="删除" disabled={disabled} onClick={() => onDelete(section)}>
            <Trash2 size={14} />
          </button>
        )}
      </div>
    </div>
  )
}
