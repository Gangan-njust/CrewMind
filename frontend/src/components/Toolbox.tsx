import { useCallback, useEffect, useState } from 'react'
import {
  Activity, BarChart3, Clock, KeyRound, Layers, Loader, PlugZap,
  RefreshCw, Trash2, ChevronDown, ChevronRight, ChevronUp, ShieldCheck, ServerCog, X,
} from 'lucide-react'
import {
  fetchUsageRuns, fetchUsageRunDetail, fetchUsageLogs, fetchUsageSummary,
  fetchApiConfig, saveApiConfig, clearApiConfig, testApiConfig,
  type UsageRun, type UsageCall, type UsageSummary, type ApiConfig,
} from '../api'

type Tab = 'runs' | 'logs' | 'config'

const SOURCE_LABELS: Record<string, string> = {
  workflow: '工作流',
  literature: '文献助手',
  writing: '学术写作',
  experiment: '实验分析',
  agent_extract: '角色提取',
}

const SOURCE_COLORS: Record<string, string> = {
  workflow: 'status-done',
  literature: 'status-running',
  writing: 'status-pending',
  experiment: 'status-failed',
}

function fmtDuration(ms: number): string {
  if (!ms) return '0s'
  if (ms < 1000) return `${ms}ms`
  const s = ms / 1000
  if (s < 60) return `${s.toFixed(1)}s`
  const m = Math.floor(s / 60)
  const rest = Math.round(s % 60)
  return `${m}m ${rest}s`
}

function fmtNumber(n: number): string {
  return (n || 0).toLocaleString('zh-CN')
}

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const pad = (x: number) => String(x).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function sourceBadge(source: string) {
  const cls = SOURCE_COLORS[source] || 'status-pending'
  return <span className={`status-tag ${cls}`}>{SOURCE_LABELS[source] || source}</span>
}

function SummaryCards({ summary }: { summary: UsageSummary | null }) {
  const cards = [
    { icon: <Activity size={18} />, label: 'API 调用次数', value: summary ? fmtNumber(summary.call_count) : '—', color: 'var(--info)' },
    { icon: <BarChart3 size={18} />, label: '累计 Token', value: summary ? fmtNumber(summary.total_tokens) : '—', color: 'var(--accent-light)' },
    { icon: <Layers size={18} />, label: '累计输入 Token', value: summary ? fmtNumber(summary.prompt_tokens) : '—', color: 'var(--success)' },
    { icon: <Clock size={18} />, label: '累计耗时', value: summary ? fmtDuration(summary.duration_ms) : '—', color: 'var(--warning)' },
  ]
  return (
    <div className="toolbox-summary-grid">
      {cards.map((c, i) => (
        <div className="toolbox-summary-card" key={i}>
          <span className="toolbox-summary-icon" style={{ color: c.color }}>{c.icon}</span>
          <div>
            <div className="toolbox-summary-label">{c.label}</div>
            <div className="toolbox-summary-value">{c.value}</div>
          </div>
        </div>
      ))}
    </div>
  )
}

function RunDetail({ runId, onClose }: { runId: string; onClose: () => void }) {
  const [calls, setCalls] = useState<UsageCall[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    fetchUsageRunDetail(runId)
      .then((d) => { if (!cancelled) { setCalls(d.calls); setLoading(false) } })
      .catch((e) => { if (!cancelled) { setError(e.message); setLoading(false) } })
    return () => { cancelled = true }
  }, [runId])

  if (loading) return <div className="toolbox-detail-loading"><Loader size={16} className="spin" /> 加载中…</div>
  if (error) return <div className="toolbox-detail-empty">{error}</div>

  return (
    <div className="toolbox-run-detail">
      <div className="toolbox-run-detail-header">
        <strong>调用明细（{calls.length} 次）</strong>
        <button className="icon-btn" onClick={onClose} title="收起"><ChevronUp size={16} /></button>
      </div>
      {calls.length === 0 ? (
        <div className="toolbox-detail-empty">该运行暂无成功调用记录</div>
      ) : (
        <div className="literature-table">
          <table>
            <thead>
              <tr>
                <th>时间</th>
                <th>模型</th>
                <th>输入 Token</th>
                <th>输出 Token</th>
                <th>总 Token</th>
                <th>耗时</th>
              </tr>
            </thead>
            <tbody>
              {calls.map((c) => (
                <tr key={c.id}>
                  <td>{fmtTime(c.created_at)}</td>
                  <td><code className="toolbox-model">{c.model || '—'}</code></td>
                  <td>{fmtNumber(c.prompt_tokens)}</td>
                  <td>{fmtNumber(c.completion_tokens)}</td>
                  <td>{fmtNumber(c.total_tokens)}</td>
                  <td>{fmtDuration(c.duration_ms)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function RunRow({ run, expanded, onToggle }: {
  run: UsageRun
  expanded: boolean
  onToggle: () => void
}) {
  const title = run.title || (run.scenario ? `方案生成（${run.scenario}）` : run.run_id)
  return (
    <>
      <tr className="toolbox-run-row" onClick={onToggle}>
        <td className="toolbox-expand-cell">
          {expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
        </td>
        <td className="toolbox-run-title">{title}</td>
        <td>{sourceBadge(run.source)}</td>
        <td className="toolbox-time">{fmtTime(run.first_at)}</td>
        <td>{fmtNumber(run.call_count)}</td>
        <td>{fmtNumber(run.prompt_tokens)}</td>
        <td>{fmtNumber(run.completion_tokens)}</td>
        <td><strong>{fmtNumber(run.total_tokens)}</strong></td>
        <td>{fmtDuration(run.duration_ms)}</td>
      </tr>
      {expanded && (
        <tr className="toolbox-detail-row">
          <td colSpan={9}>
            <RunDetail runId={run.run_id} onClose={onToggle} />
          </td>
        </tr>
      )}
    </>
  )
}

function RunsTab() {
  const [runs, setRuns] = useState<UsageRun[]>([])
  const [summary, setSummary] = useState<UsageSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [filter, setFilter] = useState<string>('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [runsData, summaryData] = await Promise.all([
        fetchUsageRuns(filter || undefined),
        fetchUsageSummary(),
      ])
      setRuns(runsData)
      setSummary(summaryData)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [filter])

  useEffect(() => { load() }, [load])

  return (
    <>
      <SummaryCards summary={summary} />

      <div className="toolbox-toolbar">
        <div className="toolbox-filters">
          {[
            ['', '全部来源'],
            ['workflow', '工作流'],
            ['literature', '文献助手'],
            ['writing', '学术写作'],
            ['experiment', '实验分析'],
          ].map(([value, label]) => (
            <button
              key={value}
              className={`filter-chip ${filter === value ? 'active' : ''}`}
              onClick={() => setFilter(value)}
            >
              {label}
            </button>
          ))}
        </div>
        <button className="btn btn-outline btn-sm" onClick={load} title="刷新">
          <RefreshCw size={14} /> 刷新
        </button>
      </div>

      {loading ? (
        <div className="toolbox-loading"><Loader size={20} className="spin" /> 加载中…</div>
      ) : error ? (
        <div className="toolbox-error">{error}</div>
      ) : runs.length === 0 ? (
        <div className="toolbox-empty">
          <div className="toolbox-empty-title">暂无运行记录</div>
          <p>运行一次工作流、文献分析或学术写作任务后，这里将展示每次运行的 token 数、耗时与 API 调用次数。</p>
        </div>
      ) : (
        <div className="card toolbox-table-card">
          <div className="literature-table">
            <table>
              <thead>
                <tr>
                  <th></th>
                  <th>运行 / 标题</th>
                  <th>来源</th>
                  <th>开始时间</th>
                  <th>调用次数</th>
                  <th>输入 Token</th>
                  <th>输出 Token</th>
                  <th>总 Token</th>
                  <th>总耗时</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <RunRow key={r.run_id} run={r} expanded={expanded === r.run_id}
                    onToggle={() => setExpanded(expanded === r.run_id ? null : r.run_id)} />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  )
}


function LogsTab() {
  const [logs, setLogs] = useState<UsageCall[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setLogs(await fetchUsageLogs())
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  return (
    <>
      <div className="toolbox-toolbar">
        <p className="toolbox-toolbar-hint">最近 200 条 LLM 调用记录（含工作流、文献、写作、实验等全部来源）</p>
        <button className="btn btn-outline btn-sm" onClick={load}><RefreshCw size={14} /> 刷新</button>
      </div>
      {loading ? (
        <div className="toolbox-loading"><Loader size={20} className="spin" /> 加载中…</div>
      ) : error ? (
        <div className="toolbox-error">{error}</div>
      ) : logs.length === 0 ? (
        <div className="toolbox-empty"><div className="toolbox-empty-title">暂无调用日志</div></div>
      ) : (
        <div className="card toolbox-table-card">
          <div className="literature-table">
            <table>
              <thead>
                <tr>
                  <th>时间</th>
                  <th>来源</th>
                  <th>模型</th>
                  <th>运行 ID</th>
                  <th>输入 Token</th>
                  <th>输出 Token</th>
                  <th>总 Token</th>
                  <th>耗时</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((c) => (
                  <tr key={c.id}>
                    <td className="toolbox-time">{fmtTime(c.created_at)}</td>
                    <td>{sourceBadge(c.source)}</td>
                    <td><code className="toolbox-model">{c.model || '—'}</code></td>
                    <td className="toolbox-run-id">{c.run_id ? c.run_id.slice(0, 8) + '…' : '—'}</td>
                    <td>{fmtNumber(c.prompt_tokens)}</td>
                    <td>{fmtNumber(c.completion_tokens)}</td>
                    <td>{fmtNumber(c.total_tokens)}</td>
                    <td>{fmtDuration(c.duration_ms)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  )
}

function ConfigTab() {
  const [config, setConfig] = useState<ApiConfig | null>(null)
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [model, setModel] = useState('')
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [message, setMessage] = useState<{ type: 'ok' | 'err' | 'info'; text: string } | null>(null)
  const [showKey, setShowKey] = useState(false)

  const load = useCallback(async () => {
    try {
      const cfg = await fetchApiConfig()
      setConfig(cfg)
      setBaseUrl(cfg.base_url || '')
      setModel(cfg.model || '')
    } catch (e) {
      setMessage({ type: 'err', text: (e as Error).message })
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handleSave = async () => {
    setSaving(true)
    setMessage(null)
    try {
      const saved = await saveApiConfig({ api_key: apiKey, base_url: baseUrl, model: model })
      setConfig(saved)
      setApiKey('')
      setMessage({ type: 'ok', text: saved.has_api_key ? '已保存自定义 API 配置，后续调用将优先使用您的 Key。' : '已保存（未填写 Key），将继续使用系统 Key。' })
    } catch (e) {
      setMessage({ type: 'err', text: (e as Error).message })
    } finally {
      setSaving(false)
    }
  }

  const handleClear = async () => {
    setSaving(true)
    setMessage(null)
    try {
      await clearApiConfig()
      setApiKey('')
      setBaseUrl('')
      setModel('')
      await load()
      setMessage({ type: 'info', text: '已清除自定义配置，恢复使用系统 Key。' })
    } catch (e) {
      setMessage({ type: 'err', text: (e as Error).message })
    } finally {
      setSaving(false)
    }
  }

  const handleTest = async () => {
    setTesting(true)
    setMessage(null)
    try {
      const result = await testApiConfig({ api_key: apiKey, base_url: baseUrl, model: model })
      setMessage({ type: 'ok', text: `${result.message}（${result.model}）${result.reply ? ` · 回复：${result.reply}` : ''}` })
    } catch (e) {
      setMessage({ type: 'err', text: (e as Error).message })
    } finally {
      setTesting(false)
    }
  }

  return (
    <div className="card toolbox-config-card">
      <div className="toolbox-config-status">
        <span className="toolbox-config-status-icon"><ShieldCheck size={20} /></span>
        <div>
          <div className="toolbox-config-status-title">
            {config?.using_system_key ? '当前使用系统 Key' : '当前使用您的自定义 Key'}
          </div>
          <div className="toolbox-config-status-desc">
            {config?.using_system_key
              ? '未填写自定义 Key，所有 LLM 调用（工作流、文献、写作、实验等）均使用系统配置的 Key。'
              : config?.updated_at ? `上次更新：${fmtTime(config.updated_at)}` : ''}
          </div>
        </div>
      </div>

      <div className="form-group">
        <label className="form-label">API Key（留空则继续使用系统 Key）</label>
        <div className="toolbox-key-input">
          <KeyRound size={16} className="toolbox-input-icon" />
          <input
            className="form-input"
            type={showKey ? 'text' : 'password'}
            placeholder={config?.has_api_key ? '••••••••（已配置，留空保持不变）' : 'sk-…'}
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            autoComplete="off"
          />
          <button className="icon-btn" type="button" onClick={() => setShowKey(!showKey)} title={showKey ? '隐藏' : '显示'}>
            {showKey ? <X size={15} /> : <PlugZap size={15} />}
          </button>
        </div>
      </div>

      <div className="form-group">
        <label className="form-label">Base URL（OpenAI 兼容接口地址，留空使用系统默认）</label>
        <div className="toolbox-key-input">
          <ServerCog size={16} className="toolbox-input-icon" />
          <input
            className="form-input"
            type="text"
            placeholder="https://api.deepseek.com"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            autoComplete="off"
          />
        </div>
      </div>

      <div className="form-group">
        <label className="form-label">模型名称（留空使用系统默认）</label>
        <input
          className="form-input"
          type="text"
          placeholder="deepseek-chat"
          value={model}
          onChange={(e) => setModel(e.target.value)}
          autoComplete="off"
        />
      </div>


      {message && (
        <div className={`toolbox-config-message ${message.type === 'ok' ? 'ok' : message.type === 'err' ? 'err' : 'info'}`}>
          {message.text}
        </div>
      )}

      <div className="toolbox-config-actions">
        <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
          {saving ? <Loader size={16} className="spin" /> : <KeyRound size={16} />} 保存配置
        </button>
        <button className="btn btn-outline" onClick={handleTest} disabled={testing}>
          {testing ? <Loader size={16} className="spin" /> : <PlugZap size={16} />} 测试连接
        </button>
        <button className="btn btn-outline danger" onClick={handleClear} disabled={saving}>
          <Trash2 size={16} /> 清除并恢复系统 Key
        </button>
      </div>

      <p className="toolbox-config-note">
        提示：保存后，您在工作流、文献助手、学术写作、实验分析等所有使用外部大模型的场景中，
        都将优先使用您自己的 Key 与接口地址；留空时自动使用系统 Key，无需额外操作。
      </p>
    </div>
  )
}

export function ToolboxPage() {
  const [tab, setTab] = useState<Tab>('runs')

  return (
    <div className="toolbox-page">
      <h2 className="page-title">工具箱</h2>
      <p className="page-desc">查看每次运行的 token 数、耗时与 API 调用次数，并配置自己的大模型 API Key（未配置时自动使用系统 Key）。</p>

      <nav className="exp-tabs" role="tablist">
        <button className={`exp-tab ${tab === 'runs' ? 'active' : ''}`} onClick={() => setTab('runs')}>
          <BarChart3 size={16} /> 运行记录
        </button>
        <button className={`exp-tab ${tab === 'logs' ? 'active' : ''}`} onClick={() => setTab('logs')}>
          <Activity size={16} /> 调用日志
        </button>
        <button className={`exp-tab ${tab === 'config' ? 'active' : ''}`} onClick={() => setTab('config')}>
          <KeyRound size={16} /> API 配置
        </button>
      </nav>

      {tab === 'runs' && <RunsTab />}
      {tab === 'logs' && <LogsTab />}
      {tab === 'config' && <ConfigTab />}
    </div>
  )
}
