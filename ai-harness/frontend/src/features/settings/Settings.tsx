// Настройки — DOM design_mockup/settings.js:
// вкладки SETTINGS_TABS (Status-flow, Проекты, ИИ-провайдеры, Агенты и матрица,
// Очередь автомата, Журнал настроек); flow: seg типов, граф (fs-card + edges +
// fs-conn протягивание) и таблица (tr-chip) одной рабочей копии, flow-panel,
// publish-panel; провайдеры prov-grid; агенты agents-grid + agent-editor;
// матрица seg типов + table.mx с ag-cell; проекты cm-row с CRUD; q-row; jr-row.

import { useEffect, useRef, useState } from 'react'
import { api } from '../../api/client'
import { TYPE } from '../../shared/refs'
import { pushUndo } from '../../shared/undo'
import { toast } from '../../shared/toast'

const TABS: [string, string][] = [
  ['flow', 'Status-flow'], ['projects', 'Проекты'], ['providers', 'ИИ-провайдеры'],
  ['agents', 'Агенты и матрица'], ['queue', 'Очередь автомата'], ['journal', 'Журнал настроек'],
]
const FLOW_TYPES: [string, string][] = [
  ['story', 'Истории'], ['common_task', 'Задачи'], ['qa_task', 'QA'],
  ['bug', 'Баги'], ['analyse_task', 'Анализ'],
]

export function Settings({ reload }: { reload: () => void }) {
  const tab = useSettingsTab()
  return (
    <div className="settings">
      <div className="set-tabs" role="tablist">
        {TABS.map(([v, l]) => (
          <button key={v} className={`set-tab ${tab === v ? 'active' : ''}`}
            onClick={() => { window.location.hash = `#settings/${v}` }}>{l}</button>
        ))}
      </div>
      <div className="set-body">
        {tab === 'flow' && <FlowEditor reload={reload} />}
        {tab === 'projects' && <Projects />}
        {tab === 'providers' && <Providers />}
        {tab === 'agents' && <AgentsAndMatrix />}
        {tab === 'queue' && <Queue />}
        {tab === 'journal' && <Journal />}
      </div>
    </div>
  )
}

function useSettingsTab(): string {
  const m = window.location.hash.match(/settings\/(\w+)/)
  return m ? m[1] : 'flow'
}

/* ==================== Status-flow — полноценный редактор ==================== */

interface Fs { key: string; label: string; stageDesc?: string; gate?: string; entry: boolean; terminal: boolean; blocking: boolean; aliasColumnId: string }
interface Ft { from: string; to: string; runner: string; display: string; rule?: string }
interface FlowData { version: number; isPublished: boolean; statuses: Fs[]; transitions: Ft[] }

const GATE_LABELS: Record<string, string> = {
  developer: 'чеклист разработчика', reviewer: 'чеклист ревьюера', tester: 'чеклист тестировщика',
}
const RUNNER_LABELS: [string, string][] = [
  ['human', 'Человек'], ['agent', 'Агент'], ['auto', 'Автомат'], ['auto_or_agent', 'Автомат или агент'],
]

function slugify(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9_]/g, '_').replace(/_{2,}/g, '_').replace(/^_|_$/g, '') || 'new_status'
}

function posFor(i: number): { x: number; y: number } {
  return { x: 30 + (i % 4) * 230, y: 30 + Math.floor(i / 4) * 140 }
}

function FlowEditor({ reload }: { reload: () => void }) {
  const [typeKey, setTypeKey] = useState('common_task')
  const [data, setData] = useState<FlowData>({ version: 0, isPublished: false, statuses: [], transitions: [] })
  const [mode, setMode] = useState<'graph' | 'table'>('graph')
  const [positions, setPositions] = useState<Record<string, { x: number; y: number }>>({})
  const [sel, setSel] = useState<{ kind: 'status' | 'edge'; id: string } | null>(null)
  const [dirty, setDirty] = useState(false)
  const [note, setNote] = useState<{ text: string; bad: boolean } | null>(null)
  const [zoom, setZoom] = useState(1)
  const [columns, setColumns] = useState<{ id: string; label: string }[]>([])
  const [newColName, setNewColName] = useState('')
  const [newColFor, setNewColFor] = useState<string | null>(null)
  const [edgeAddFor, setEdgeAddFor] = useState<string | null>(null)
  const [edgeTarget, setEdgeTarget] = useState('')
  const [edgeRunner, setEdgeRunner] = useState('human')
  const [validation, setValidation] = useState<{ errors: string[]; warnings: string[]; ok: boolean } | null>(null)
  const [showValidation, setShowValidation] = useState(false)
  const dragRef = useRef<{ key: string; dx: number; dy: number } | null>(null)
  const connRef = useRef<{ from: string; x: number; y: number } | null>(null)
  const [, tick] = useState(0)

  const reloadFlow = () => {
    void api.flow(typeKey).then((d) => {
      setData(d)
      const saved = JSON.parse(localStorage.getItem(`flow-pos-${typeKey}`) ?? '{}')
      setPositions(Object.fromEntries(
        d.statuses.map((s, i) => [s.key, saved[s.key] ?? posFor(i)])))
    })
    void api.aliasColumns().then(setColumns)
  }
  useEffect(reloadFlow, [typeKey])

  const mutate = (fn: (d: FlowData) => Partial<FlowData>) => { setData((d) => d && { ...d, ...fn(d) }); setDirty(true) }

  const addStatus = () => {
    let i = (data.statuses.length)
    let key = `new_status_${i}`
    while ((data.statuses).some((s) => s.key === key)) { i++; key = `new_status_${i}` }
    mutate((d) => ({ ...d, statuses: [...d.statuses, {
      key, label: `Новый статус ${i + 1}`, stageDesc: '', gate: undefined,
      entry: false, terminal: false, blocking: false,
      aliasColumnId: columns[0]?.id ?? '',
    }] }))
    setPositions((p) => ({ ...p, [key]: posFor((data.statuses.length)) }))
    setSel({ kind: 'status', id: key })
  }

  const removeStatus = (key: string) => {
    mutate((d) => ({
      statuses: d.statuses.filter((s) => s.key !== key),
      transitions: d.transitions.filter((t) => t.from !== key && t.to !== key),
    }))
    setSel(null)
  }

  const addEdge = (from: string, to: string, runner = 'human') => {
    if ((data.transitions).some((t) => t.from === from && t.to === to)) {
      setNote({ text: 'Дубликат перехода отклонён', bad: true })
      return
    }
    mutate((d) => ({ ...d, transitions: [...d.transitions, {
      from, to, runner, display: runner === 'auto' ? 'Автоматически' : 'Ручное вмешательство' }] }))
    setSel({ kind: 'edge', id: `${from}→${to}` })
  }

  const removeEdge = (from: string, to: string) => {
    mutate((d) => ({ ...d, transitions: d.transitions.filter((t) => !(t.from === from && t.to === to)) }))
    if (sel?.kind === 'edge' && sel.id === `${from}→${to}`) setSel(null)
  }

  const saveDraft = async (d: FlowData = data) => {
    await api.saveDraft(typeKey, {
      statuses: d.statuses.map((s) => ({ key: s.key, label: s.label, gate: s.gate,
        entry: s.entry, terminal: s.terminal, blocking: s.blocking,
        stage_desc: s.stageDesc, alias_column_id: s.aliasColumnId || undefined })),
      transitions: d.transitions.map((t) => ({ from: t.from, to: t.to, runner: t.runner,
        display: t.display, rule: t.rule })),
    })
    setDirty(false)
    setNote({ text: 'Черновик сохранён', bad: false })
  }

  const doValidate = async () => {
    await saveDraft()
    const r = await api.validateFlow(typeKey)
    setValidation(r)
    setShowValidation(true)
    const msg = r.ok
      ? 'Валидация пройдена' + (r.warnings.length ? ' · ' + r.warnings.join('; ') : '')
      : 'Ошибки: ' + r.errors.join('; ')
    setNote({ text: msg, bad: !r.ok })
  }

  const doPublish = async () => {
    await saveDraft()
    try {
      const r = await api.publishFlow(typeKey)
      setNote({ text: `Опубликовано v${r.version}`, bad: false })
      setValidation(null); setShowValidation(false); reloadFlow(); reload()
    } catch (err) {
      const e = err as Error & { tech?: string }
      setNote({ text: e.message, bad: true })
    }
  }

  const selectedStatus = data ? sel?.kind === 'status' ? data.statuses.find((s) => s.key === sel.id) : undefined : undefined
  const selEdge = data ? sel?.kind === 'edge' ? data.transitions.find((t) => `${t.from}→${t.to}` === sel.id) : undefined : undefined

  // --- канвас ---
  const onMouseDownCard = (e: React.MouseEvent, key: string) => {
    if ((e.target as HTMLElement).closest('.fs-conn, .colh-x')) return
    dragRef.current = { key, dx: e.clientX - (positions[key]?.x ?? 0) * zoom, dy: e.clientY - (positions[key]?.y ?? 0) * zoom }
    setSel({ kind: 'status', id: key })
  }
  const onMouseMove = (e: React.MouseEvent) => {
    if (dragRef.current) {
      const { key, dx, dy } = dragRef.current
      setPositions((p) => { const n = { ...p, [key]: { x: (e.clientX - dx) / zoom, y: (e.clientY - dy) / zoom } }; localStorage.setItem(`flow-pos-${typeKey}`, JSON.stringify(n)); return n })
      tick((n) => n + 1)
    } else if (connRef.current) {
      connRef.current = { ...connRef.current, x: e.clientX, y: e.clientY }
      tick((n) => n + 1)
    }
  }
  const onMouseUp = (e: React.MouseEvent) => {
    if (connRef.current) {
      const { from } = connRef.current
      const rect = canvasRef.current?.getBoundingClientRect()
      if (rect) {
        const x = (e.clientX - rect.left) / zoom, y = (e.clientY - rect.top) / zoom
        const target = (data.statuses).find((s) => {
          const p = positions[s.key]
          return p && x >= p.x && x <= p.x + 184 && y >= p.y && y <= p.y + 64
        })
        if (target && target.key !== from) addEdge(from, target.key)
      }
      connRef.current = null; tick((n) => n + 1)
    }
    dragRef.current = null
  }
  const startConn = (e: React.MouseEvent, from: string) => {
    e.stopPropagation(); connRef.current = { from, x: e.clientX, y: e.clientY }
  }

  const canvasRef = useRef<HTMLDivElement>(null)
  const cardCenter = (key: string) => {
    const p = positions[key] ?? { x: 0, y: 0 }
    return { x: p.x + 92, y: p.y + 32 }
  }

  const statusField = (key: string, patch: Partial<Fs>) => {
    mutate((d) => ({ ...d, statuses: d.statuses.map((s) => s.key === key ? { ...s, ...patch } : s) }))
  }
  const edgeField = (from: string, to: string, patch: Partial<Ft>) => {
    mutate((d) => ({ ...d, transitions: d.transitions.map((t) => t.from === from && t.to === to ? { ...t, ...patch } : t) }))
  }

  if (data.version === 0) return <div className="empty"><b>Загрузка flow…</b></div>

  return (
    <div className="set-body">
      <div className="publish-panel">
        <div className="flex">
          <span className="mini-chip mc-accent">v{data.version}{data.isPublished ? '' : ' · черновик'}</span>
          <span className="sp" />
          <button className="btn small" disabled={!dirty} onClick={() => void saveDraft()}>Сохранить черновик</button>
          <button className="btn small" onClick={() => void doValidate()}>Проверить</button>
          <button className="btn primary small" onClick={() => void doPublish()}>Опубликовать</button>
          <button className="btn small" onClick={async () => {
            const res = await fetch(`/api/v1/flows/${typeKey}/reset`, { method: 'POST' })
            if (res.ok) { setNote({ text: 'Сброшено к пресету', bad: false }); reloadFlow() }
          }}>Сбросить</button>
        </div>
        {note && <div className={`check-row ${note.bad ? 'err' : 'ok'}`}>{note.bad ? '✗ ' : '✓ '}{note.text}</div>}
        {showValidation && validation && (
          <div className="mt8">
            {validation.errors.map((e, i) => <div key={'e' + i} className="check-row err">✗ {e}</div>)}
            {validation.warnings.map((w, i) => <div key={'w' + i} className="check-row warn">⚠ {w}</div>)}
            {validation.ok && validation.warnings.length === 0 && <div className="check-row ok">✓ Ошибок и предупреждений нет</div>}
          </div>
        )}
      </div>

      <div className="flow-toolbar">
        <div className="seg">
          {FLOW_TYPES.map(([k, l]) => (
            <button key={k} className={typeKey === k ? 'active' : ''} onClick={() => { setTypeKey(k); setSel(null); setValidation(null) }}>{l}</button>
          ))}
        </div>
        <div className="mode-tabs">
          <button className={mode === 'graph' ? 'active' : ''} onClick={() => setMode('graph')}>Граф</button>
          <button className={mode === 'table' ? 'active' : ''} onClick={() => setMode('table')}>Таблица</button>
        </div>
        <button className="btn small" onClick={addStatus}>＋ статус</button>
        <span className="sp" />
        <span className="muted">{data.statuses.length} статусов · {data.transitions.length} переходов{dirty ? ' · есть правки' : ''}</span>
      </div>

      {mode === 'graph' ? (
        <div className="flow-body">
          <div className="flow-canvas" ref={canvasRef}
            onMouseMove={onMouseMove} onMouseUp={onMouseUp} onMouseLeave={onMouseUp}>
            <div className="paper" style={{ transform: `scale(${zoom})`, width: 1400, height: 700 }}>
              <svg className="edges" width="1400" height="700">
                {data.transitions.map((t, i) => {
                  const a = cardCenter(t.from), b = cardCenter(t.to)
                  if (!a.x && !b.x) return null
                  const mx = (a.x + b.x) / 2
                  const d = `M ${a.x} ${a.y} C ${mx} ${a.y}, ${mx} ${b.y}, ${b.x} ${b.y}`
                  return (
                    <g key={i}>
                      <path className={`line ${t.runner === 'auto' ? 'edge-auto' : t.runner === 'agent' ? 'edge-agent' : 'edge-human'}`} d={d}
                        onClick={() => setSel({ kind: 'edge', id: `${t.from}→${t.to}` })} />
                      <path className="hit" d={d} onClick={() => setSel({ kind: 'edge', id: `${t.from}→${t.to}` })} />
                    </g>
                  )
                })}
                {connRef.current && <path className="edge-new-temp" d={`M ${cardCenter(connRef.current.from).x} ${cardCenter(connRef.current.from).y} L ${(connRef.current.x - (canvasRef.current?.getBoundingClientRect().left ?? 0)) / zoom} ${(connRef.current.y - (canvasRef.current?.getBoundingClientRect().top ?? 0)) / zoom}`} />}
              </svg>
              {data.statuses.map((s, i) => {
                const p = positions[s.key] ?? posFor(i)
                return (
                  <div key={s.key} className={`fs-card ${s.terminal ? 'term' : ''} ${sel?.kind === 'status' && sel.id === s.key ? 'sel' : ''}`}
                    style={{ left: p.x, top: p.y }}
                    onMouseDown={(e) => onMouseDownCard(e, s.key)}>
                    <div className="lbl">{s.label}</div>
                    <div className="key">{s.key}{s.gate ? ` · ${GATE_LABELS[s.gate] ?? s.gate}` : ''}</div>
                    {s.stageDesc && <div className="fs-desc">{s.stageDesc}</div>}
                    <div className="fs-chips">
                      {s.entry && <span className="mini-chip mc-accent">вход</span>}
                      {s.terminal && <span className="mini-chip mc-green">терминальный</span>}
                      {s.blocking && <span className="mini-chip mc-red">блокирующий</span>}
                    </div>
                    <button className="fs-conn" title="Протяните на другой статус — создастся переход"
                      onMouseDown={(e) => startConn(e, s.key)}>+</button>
                  </div>
                )
              })}
            </div>
          </div>
          <div className="flow-panel">
            {selectedStatus && (
              <>
                <div className="blk-h"><h3>Статус flow</h3><span className="fill" />
                  <button className="icon-btn" onClick={() => setSel(null)} style={{ width: 22, height: 22 }}>✕</button></div>
                <div className="f-field"><label>Ключ (не меняется)</label>
                  <input className="mono" value={selectedStatus.key} disabled /></div>
                <div className="f-field"><label>Название на интерфейсе</label>
                  <input value={selectedStatus.label} maxLength={64}
                    onChange={(e) => statusField(selectedStatus.key, { label: e.target.value })} /></div>
                <div className="f-field"><label>Что происходит на этом этапе</label>
                  <textarea rows={3} value={selectedStatus.stageDesc ?? ''}
                    onChange={(e) => statusField(selectedStatus.key, { stageDesc: e.target.value })} /></div>
                <div className="f-field"><label>Чеклист-гейт</label>
                  <select value={selectedStatus.gate ?? ''} onChange={(e) => statusField(selectedStatus.key, { gate: e.target.value || undefined })}>
                    <option value="">без гейта</option>
                    <option value="developer">чеклист разработчика</option>
                    <option value="reviewer">чеклист ревьюера</option>
                    <option value="tester">чеклист тестировщика</option>
                  </select></div>
                <div className="f-field"><label>Alias-колонка на доске</label>
                  <select value={newColFor === selectedStatus.key ? '__new' : (selectedStatus.aliasColumnId ?? '')}
                    onChange={async (e) => {
                      if (e.target.value === '__new') { setNewColFor(selectedStatus.key); return }
                      setNewColFor(null)
                      statusField(selectedStatus.key, { aliasColumnId: e.target.value })
                    }}>
                    <option value="">— не назначена —</option>
                    {columns.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
                    <option value="__new">＋ новая колонка…</option>
                  </select>
                  {newColFor === selectedStatus.key && (
                    <div className="flex mt8">
                      <input className="cm-name" placeholder="Название колонки" value={newColName}
                        onChange={(e) => setNewColName(e.target.value)} />
                      <button className="btn small" onClick={async () => {
                        if (!newColName.trim()) return
                        const res = await api.createColumn({ label: newColName.trim() })
                        setColumns((c) => [...c, { id: res.id, label: newColName.trim() }])
                        statusField(selectedStatus.key, { aliasColumnId: res.id })
                        setNewColFor(null); setNewColName('')
                      }}>Создать</button>
                    </div>
                  )}
                </div>
                <label className="f-check"><input type="checkbox" checked={selectedStatus.entry}
                  onChange={(e) => statusField(selectedStatus.key, { entry: e.target.checked })} /> точка входа</label>
                <label className="f-check"><input type="checkbox" checked={selectedStatus.terminal}
                  onChange={(e) => statusField(selectedStatus.key, { terminal: e.target.checked })} /> терминальный</label>
                <label className="f-check"><input type="checkbox" checked={selectedStatus.blocking}
                  onChange={(e) => statusField(selectedStatus.key, { blocking: e.target.checked })} /> блокирующий</label>
                <button className="btn danger small mt12" onClick={() => removeStatus(selectedStatus.key)}>Удалить статус</button>
              </>
            )}
            {selEdge && (
              <>
                <div className="blk-h"><h3>Переход</h3><span className="fill" />
                  <button className="icon-btn" onClick={() => setSel(null)} style={{ width: 22, height: 22 }}>✕</button></div>
                <div className="f-field"><label>Направление</label>
                  <input value={`${selEdge.from} → ${selEdge.to}`} disabled /></div>
                <div className="f-field"><label>Кто запускает</label>
                  <select value={selEdge.runner} onChange={(e) => edgeField(selEdge.from, selEdge.to, { runner: e.target.value })}>
                    {RUNNER_LABELS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select></div>
                <div className="f-field"><label>Как отображается</label>
                  <input value={selEdge.display} onChange={(e) => edgeField(selEdge.from, selEdge.to, { display: e.target.value })} /></div>
                <button className="btn danger small mt12" onClick={() => removeEdge(selEdge.from, selEdge.to)}>Удалить переход</button>
              </>
            )}
            {!selectedStatus && !selEdge && (
              <div className="muted">Кликните по карточке статуса или стрелке — здесь откроется редактирование. Новый переход: потяните за «+» на краю карточки.</div>
            )}
          </div>
        </div>
      ) : (
        <div className="flow-canvas flow-table">
          <table className="tasks">
            <thead><tr>
              <th>Статус</th><th>Что происходит на этапе</th><th>Чеклист-гейт</th><th>Флаги</th>
              <th>Возможные переходы</th><th>Alias-колонка</th><th></th>
            </tr></thead>
            <tbody>
              {data.statuses.map((s) => (
                <tr key={s.key} onClick={() => setSel({ kind: 'status', id: s.key })}>
                  <td onClick={(e) => e.stopPropagation()}>
                    <input value={s.label} maxLength={64} style={{ width: 150 }}
                      onChange={(e) => statusField(s.key, { label: e.target.value })} />
                    <div className="key mono muted">{s.key}</div>
                  </td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <input value={s.stageDesc ?? ''} style={{ width: 220 }}
                      placeholder="что происходит на этапе"
                      onChange={(e) => statusField(s.key, { stageDesc: e.target.value })} />
                  </td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <select value={s.gate ?? ''} onChange={(e) => statusField(s.key, { gate: e.target.value || undefined })}>
                      <option value="">—</option>
                      {Object.entries(GATE_LABELS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                    </select>
                  </td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <label className="f-check"><input type="checkbox" checked={s.entry}
                      onChange={(e) => statusField(s.key, { entry: e.target.checked })} /> вход</label>
                    <label className="f-check"><input type="checkbox" checked={s.terminal}
                      onChange={(e) => statusField(s.key, { terminal: e.target.checked })} /> терм.</label>
                    <label className="f-check"><input type="checkbox" checked={s.blocking}
                      onChange={(e) => statusField(s.key, { blocking: e.target.checked })} /> блок.</label>
                  </td>
                  <td className="tr-cell" onClick={(e) => e.stopPropagation()}>
                    {data.transitions.filter((t) => t.from === s.key).map((t) => (
                      <span key={`${t.from}${t.to}`} className="mini-chip tr-chip" title={t.runner}>
                        → {data.statuses.find((x) => x.key === t.to)?.label ?? t.to}
                        <button className="tr-x" onClick={() => removeEdge(t.from, t.to)}>✕</button>
                      </span>
                    ))}
                    {edgeAddFor === s.key ? (
                      <span className="flex mt8">
                        <select value={edgeTarget} onChange={(e) => setEdgeTarget(e.target.value)}>
                          <option value="">→ куда</option>
                          {data.statuses
                            .filter((x) => x.key !== s.key)
                            .filter((x) => !data.transitions.some((t) => t.from === s.key && t.to === x.key))
                            .map((x) => <option key={x.key} value={x.key}>{x.label}</option>)}
                        </select>
                        <select value={edgeRunner} onChange={(e) => setEdgeRunner(e.target.value)}>
                          {RUNNER_LABELS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                        </select>
                        <button className="btn small" onClick={() => {
                          if (edgeTarget) { addEdge(s.key, edgeTarget, edgeRunner); setEdgeAddFor(null); setEdgeTarget('') }
                        }}>✓</button>
                        <button className="btn small" onClick={() => { setEdgeAddFor(null); setEdgeTarget('') }}>✕</button>
                      </span>
                    ) : (
                      <button className="btn small" disabled={s.terminal}
                        title={s.terminal ? 'У терминального статуса нет исходящих переходов' : undefined}
                        onClick={() => { setEdgeAddFor(s.key); setEdgeTarget('') }}>＋ переход</button>
                    )}
                  </td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <select value={newColFor === s.key ? '__new' : (s.aliasColumnId ?? '')}
                      onChange={async (e) => {
                        if (e.target.value === '__new') { setNewColFor(s.key); return }
                        setNewColFor(null)
                        statusField(s.key, { aliasColumnId: e.target.value })
                      }}>
                      <option value="">— не назначена —</option>
                      {columns.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
                      <option value="__new">＋ новая колонка…</option>
                    </select>
                    {newColFor === s.key && (
                      <div className="flex mt8">
                        <input className="cm-name" placeholder="Название колонки" value={newColName}
                          onChange={(e) => setNewColName(e.target.value)} />
                        <button className="btn small" onClick={async () => {
                          if (!newColName.trim()) return
                          const res = await api.createColumn({ label: newColName.trim() })
                          setColumns((c) => [...c, { id: res.id, label: newColName.trim() }])
                          statusField(s.key, { aliasColumnId: res.id })
                          setNewColFor(null); setNewColName('')
                        }}>Создать</button>
                      </div>
                    )}
                  </td>
                  <td><button className="btn danger small" onClick={() => removeStatus(s.key)}>✕</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

/* ==================== Проекты ==================== */

function Projects() {
  const [list, setList] = useState<{ id: string; name: string; mnemonic: string; path: string; baseBranch: string; isArchived: boolean; description?: string }[]>([])
  const [edit, setEdit] = useState<{ id?: string; name: string; mnemonic: string; path: string; baseBranch: string; description: string } | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const reload = () => { void fetch('/api/v1/projects').then((r) => r.json()).then(setList) }
  useEffect(reload, [])

  const save = async () => {
    if (!edit) return
    const res = edit.id
      ? await fetch(`/api/v1/projects/${edit.id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: edit.name, path: edit.path, baseBranch: edit.baseBranch, description: edit.description }) })
      : await fetch('/api/v1/projects', { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: edit.name, mnemonic: edit.mnemonic, path: edit.path, baseBranch: edit.baseBranch, description: edit.description }) })
    const body = await res.json().catch(() => ({}))
    if (!res.ok) { setNote(body.message); return }
    setNote(null); setEdit(null); reload()
  }

  return (
    <div className="set-body">
      <div className="flow-toolbar">
        <button className="btn primary small" onClick={() => setEdit({ name: '', mnemonic: '', path: '', baseBranch: 'main', description: '' })}>＋ Проект</button>
        {note && <span className="check-row err">{note}</span>}
      </div>
      {edit && (
        <div className="agent-editor mt12">
          <div className="q-sec">{edit.id ? 'Правка проекта' : 'Новый проект'}</div>
          <div className="ag-fields">
            <div className="f-field"><label>Название</label>
              <input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></div>
            <div className="f-field"><label>Мнемоника (2–10, A-Z0-9; неизменна)</label>
              <input value={edit.mnemonic} disabled={Boolean(edit.id)}
                onChange={(e) => setEdit({ ...edit, mnemonic: e.target.value.toUpperCase() })} /></div>
            <div className="f-field"><label>Путь на диске (существует и доступен на запись)</label>
              <input value={edit.path} onChange={(e) => setEdit({ ...edit, path: e.target.value })} /></div>
            <div className="f-field"><label>Базовая ветка</label>
              <input value={edit.baseBranch} onChange={(e) => setEdit({ ...edit, baseBranch: e.target.value })} /></div>
            <div className="f-field" style={{ gridColumn: '1 / -1' }}><label>Описание</label>
              <input value={edit.description} onChange={(e) => setEdit({ ...edit, description: e.target.value })} /></div>
          </div>
          <div className="flex mt12">
            <button className="btn primary" onClick={() => void save()}>Сохранить</button>
            <button className="btn" onClick={() => setEdit(null)}>Отмена</button>
          </div>
        </div>
      )}
      <div className="col-mgr mt12">
        {list.map((p) => (
          <div key={p.id} className={`prov-row ${p.isArchived ? 'proj-arch' : ''}`}>
            <div className="pr-main">
              <b><span className="mono">{p.mnemonic}</span> · {p.name}</b>
              <div className="muted">{p.path} · ветка {p.baseBranch}{p.isArchived ? ' · в архиве' : ''}</div>
            </div>
            <div className="pr-actions">
              <button className="btn small" onClick={() => setEdit({ id: p.id, name: p.name, mnemonic: p.mnemonic, path: p.path, baseBranch: p.baseBranch, description: p.description ?? '' })}>Править</button>
              <button className="btn small" onClick={async () => {
                await fetch(`/api/v1/projects/${p.id}/archive?archived=${!p.isArchived}`, { method: 'POST' }); reload()
              }}>{p.isArchived ? 'Из архива' : 'В архив'}</button>
              <button className="btn danger small" onClick={async () => {
                const res = await fetch(`/api/v1/projects/${p.id}`, { method: 'DELETE' })
                const body = await res.json().catch(() => ({}))
                if (!res.ok) setNote(body.message); else reload()
              }}>Удалить</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ==================== ИИ-провайдеры ==================== */

function Providers() {
  const [list, setList] = useState<{ id: string; name: string; protocol: string; url: string; model: string; tokenTail: string; checkStatus: string; isActive: boolean }[]>([])
  const [presets, setPresets] = useState<{ name: string; protocol: string; baseUrl: string }[]>([])
  const [form, setForm] = useState({ name: '', protocol: 'anthropic', url: '', model: '', token: '' })
  const [message, setMessage] = useState<{ text: string; bad: boolean } | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const reload = () => void api.requestProviders().then(setList)
  useEffect(reload, [])
  useEffect(() => {
    void fetch('/api/v1/provider-presets').then((r) => r.json()).then(setPresets)
  }, [])

  return (
    <div className="set-body">
      <div className="prov-grid">
        <div>
          <div className="q-sec">Подключения</div>
          {list.map((c) => (
            <div key={c.id} className={`prov-row ${c.isActive ? 'active' : ''}`}>
              <div className="pr-main">
                <b>{c.name}</b> <span className="mini-chip">{c.protocol}</span>
                <div className="muted">{c.url} · {c.model}</div>
                <div className="muted">токен {c.tokenTail} · проверка: {c.checkStatus}</div>
              </div>
              <div className="pr-actions">
                <button className="btn small" onClick={() => {
                  setEditingId(c.id)
                  setForm({ name: c.name, protocol: c.protocol,
                    url: c.url, model: c.model, token: '' })
                }}>Править</button>
                {!c.isActive && <button className="btn small danger" onClick={async () => {
                  if (!window.confirm(`Удалить подключение «${c.name}»?`)) return
                  const res = await fetch(`/api/v1/connections/${c.id}`, { method: 'DELETE' })
                  const body = await res.json().catch(() => ({}))
                  if (!res.ok) setMessage({ text: body.message, bad: true }); else reload()
                }}>Удалить</button>}
                {!c.isActive && <button className="btn small" onClick={async () => {
                  await fetch(`/api/v1/connections/${c.id}/activate`, { method: 'POST' }); reload()
                }}>Сделать активным</button>}
              </div>
            </div>
          ))}
          {list.length === 0 && <div className="muted">Подключений пока нет</div>}
        </div>
        <div className="prov-form">
          <div className="q-sec">Новое подключение</div>
          <div className="f-field"><label>{editingId ? `Правка подключения` : 'Название'}</label>
            <input value={form.name} disabled={Boolean(editingId)}
              onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
          <div className="f-field"><label>Пресет провайдера — подставит адрес, поле остаётся редактируемым</label>
            <select value="" onChange={(e) => {
              const pr = presets.find((x) => x.name === e.target.value)
              if (pr) setForm({ ...form, protocol: pr.protocol, url: pr.baseUrl })
            }}>
              <option value="">— выбрать пресет —</option>
              {presets.map((pr) => <option key={pr.name} value={pr.name}>{pr.name}</option>)}
            </select></div>
          <div className="f-field"><label>Протокол</label>
            <select value={form.protocol} onChange={(e) => setForm({ ...form, protocol: e.target.value })}>
              <option value="anthropic">Anthropic</option>
              <option value="openai">OpenAI-совместимый</option>
            </select></div>
          <div className="f-field"><label>URL</label>
            <input value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} /></div>
          <div className="f-field"><label>Модель</label>
            <input value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} /></div>
          <div className="f-field"><label>API-токен</label>
            <input type="password" value={form.token} onChange={(e) => setForm({ ...form, token: e.target.value })} /></div>
          <div className="flex mt12">
            <button className="btn" onClick={async () => {
              try {
                const res = await fetch('/api/v1/connections/check', {
                  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(form) })
                const body = await res.json()
                setMessage(res.ok ? { text: 'Подключение успешно', bad: false }
                  : { text: `${body.message}${body.techDetail ? ` — ${body.techDetail}` : ''}`, bad: true })
              } catch (err) { setMessage({ text: String(err), bad: true }) }
            }}>Проверить</button>
            <button className="btn primary" onClick={async () => {
              const res = editingId
                ? await fetch(`/api/v1/connections/${editingId}`, {
                    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(form) })
                : await fetch('/api/v1/connections', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(form) })
              const body = await res.json().catch(() => ({}))
              if (!res.ok) setMessage({ text: body.message, bad: true })
              else {
                setMessage({ text: editingId ? 'Правки сохранены' : 'Сохранено (не проверено)', bad: false })
                setForm({ name: '', protocol: form.protocol, url: '', model: '', token: '' })
                setEditingId(null); reload()
              }
            }}>Сохранить</button>
          </div>
          {message && <div className={`check-row ${message.bad ? 'err' : 'ok'}`}>{message.text}</div>}
        </div>
      </div>
    </div>
  )
}

/* ==================== Агенты и матрица ==================== */

function AgentsAndMatrix() {
  const [agents, setAgents] = useState<{ id: string; name: string; role: string; skillMd: string; connectionId: string; isPreset: boolean }[]>([])
  const [users, setUsers] = useState<{ id: string; name: string; userType: string }[]>([])
  const [editor, setEditor] = useState<{ id?: string; name: string; role: string; skillMd: string } | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const reload = async () => {
    setAgents(await api.agents())
    setUsers(await api.users())
  }
  useEffect(() => { void reload() }, [])

  const clone = async (id: string) => {
    const res = await fetch(`/api/v1/agents/${id}/clone`, { method: 'POST' })
    const body = await res.json().catch(() => ({}))
    if (!res.ok) setNote(body.message)
    else { toast(`Клонирован: ${body.name}`, 'ok'); void reload() }
  }
  const remove = async (id: string, name: string) => {
    const res = await fetch(`/api/v1/agents/${id}`, { method: 'DELETE' })
    const body = await res.json().catch(() => ({}))
    if (!res.ok) setNote(body.message)
    else { toast(`Агент ${name} удалён`, 'ok'); void reload() }
  }
  const saveEditor = async () => {
    if (!editor) return
    const res = editor.id
      ? await fetch(`/api/v1/agents/${editor.id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: editor.name, role: editor.role, skillMd: editor.skillMd }) })
      : await fetch('/api/v1/agents', { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: editor.name, role: editor.role, skillMd: editor.skillMd }) })
    const body = await res.json().catch(() => ({}))
    if (!res.ok) { setNote(body.message); return }
    setEditor(null); setNote(null); void reload()
  }

  return (
    <div className="set-body">
      {note && <div className="check-row err">{note}</div>}
      <div className="flow-toolbar">
        <div className="q-sec" style={{ margin: 0 }}>Пользователи-агенты</div>
        <span className="sp" />
        <button className="btn primary small" onClick={() => setEditor({
          name: '', role: '', skillMd: '## Роль и цель\nОдин абзац: за что агент отвечает.\n\n## Процедура\n1. …\n\n## Критерии качества\n- …\n\n## Формат результата\n- …\n\n## Ограничения\n- …',
        })}>＋ Агент</button>
      </div>
      <div className="agents-grid">
        {agents.map((a) => (
          <div key={a.id} className="agent-card">
            <div className="flex">
              <span className="eve-ava" style={{ background: 'var(--surface3)', color: 'var(--text2)' }}>{a.name.slice(0, 1)}</span>
              <b>{a.name}</b>
              {a.isPreset && <span className="mini-chip">предустановленный</span>}
              <span className="sp" />
              <button className="link" style={{ fontSize: 12 }} onClick={() => setEditor({ id: a.id, name: a.name, role: a.role, skillMd: a.skillMd })}>править</button>
              <span className="muted">·</span>
              <button className="link" style={{ fontSize: 12 }} onClick={() => void clone(a.id)}>клонировать</button>
              <span className="muted">·</span>
              <button className="link" style={{ fontSize: 12, color: 'var(--danger)' }} onClick={() => void remove(a.id, a.name)}>удалить</button>
            </div>
            <div className="muted" style={{ fontSize: 12.5, marginTop: 6 }}>{a.role}</div>
            <div className="flex mt8" style={{ flexWrap: 'wrap' }}>
              <span className="mini-chip">{a.connectionId ? 'своё подключение' : 'активное подключение'}</span>
            </div>
          </div>
        ))}
      </div>
      {editor && (
        <div className="agent-editor mt12">
          <div className="q-sec">{editor.id ? 'Правка агента' : 'Новый агент'}</div>
          <div className="ag-fields">
            <div className="f-field"><label>Название</label>
              <input value={editor.name} onChange={(e) => setEditor({ ...editor, name: e.target.value })} /></div>
            <div className="f-field"><label>Роль (за что отвечает)</label>
              <input value={editor.role} onChange={(e) => setEditor({ ...editor, role: e.target.value })} /></div>
            <div className="f-field" style={{ gridColumn: '1 / -1' }}><label>Скилл (markdown: роль, процедура, критерии, формат, ограничения)</label>
              <textarea rows={12} value={editor.skillMd} onChange={(e) => setEditor({ ...editor, skillMd: e.target.value })} /></div>
          </div>
          <div className="flex mt12">
            <button className="btn primary" onClick={() => void saveEditor()}>Сохранить</button>
            <button className="btn" onClick={() => setEditor(null)}>Отмена</button>
          </div>
        </div>
      )}

      <Matrix agentsAndUsers={users} />
    </div>
  )
}

function Matrix({ agentsAndUsers }: { agentsAndUsers: { id: string; name: string; userType: string }[] }) {
  const [typeKey, setTypeKey] = useState('common_task')
  const [statuses, setStatuses] = useState<{ key: string; label: string; stageDesc?: string }[]>([])
  const [matrix, setMatrix] = useState<Record<string, { userId: string; name: string; mode: string }[]>>({})
  const [note, setNote] = useState<string | null>(null)

  useEffect(() => {
    void api.flow(typeKey).then((f) => setStatuses(f.statuses.map((s) => ({ key: s.key, label: s.label, stageDesc: s.stageDesc }))))
    void api.matrix(typeKey).then((m) => setMatrix(m.matrix))
  }, [typeKey])

  const setEntries = async (statusKey: string, entries: { userId: string; mode: string }[]) => {
    try {
      await api.setMatrix(typeKey, statusKey, entries)
      setMatrix((m) => ({ ...m, [statusKey]: entries.map((e) => ({
        userId: e.userId, name: agentsAndUsers.find((p) => p.id === e.userId)?.name ?? '?', mode: e.mode })) }))
      setNote(null)
    } catch (err) { setNote((err as Error).message) }
  }

  return (
    <>
      <div className="q-sec" style={{ marginTop: 24 }}>Матрица назначений — кто работает на каждом статусе</div>
      <div className="flow-toolbar">
        <div className="seg">
          {FLOW_TYPES.map(([k, l]) => (
            <button key={k} className={typeKey === k ? 'active' : ''} onClick={() => setTypeKey(k)}>{l}</button>
          ))}
        </div>
        <span className="muted">несколько агентов — «параллельно» или «замещение»</span>
        {note && <span className="check-row err">{note}</span>}
      </div>
      <table className="tasks mx">
        <thead><tr><th className="mx-c1">Статус</th><th>Что происходит</th><th className="mx-c3">Агенты</th><th className="mx-c4">Режим</th></tr></thead>
        <tbody>
          {statuses.map((s) => {
            const entries = matrix[s.key] ?? []
            const mode = entries[0]?.mode ?? 'replacement'
            return (
              <tr key={s.key}>
                <td><b>{s.label}</b><br /><span className="muted mono" style={{ fontSize: 10 }}>{s.key}</span></td>
                <td className="muted">{s.stageDesc ?? ''}</td>
                <td>
                  <div className="ag-cell">
                    {entries.map((e) => (
                      <span key={e.userId} className="mini-chip" style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
                        {e.name}
                        <button title="Снять назначение" style={{ color: 'inherit' }}
                          onClick={() => void setEntries(s.key, entries.filter((x) => x.userId !== e.userId))}>✕</button>
                      </span>
                    ))}
                    <AgCellPopover statusKey={s.key} people={agentsAndUsers} entries={entries}
                      defaultMode={mode} onApply={(next) => void setEntries(s.key, next)} />
                  </div>
                </td>
                <td>
                  <select value={mode} onChange={(e) =>
                    void setEntries(s.key, entries.map((x) => ({ userId: x.userId, mode: e.target.value })))}
                    disabled={entries.length === 0}>
                    <option value="replacement">замещение</option>
                    <option value="parallel">параллельно</option>
                  </select>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </>
  )
}

/* ==================== Очередь и журнал ==================== */

function Queue() {
  const [snap, setSnap] = useState<Awaited<ReturnType<typeof api.queue>> | null>(null)
  useEffect(() => { void api.queue().then(setSnap) }, [])
  if (!snap) return <div className="empty"><b>Загрузка…</b></div>
  return (
    <div className="set-body">
      <div className="q-sec">В работе у агентов</div>
      {snap.working.map((w) => (
        <div key={w.code} className="q-row" onClick={() => { window.location.hash = `#${w.code}` }}>
          <span className="code">{w.code}</span><span className="q-t">{w.agent}</span>
          <span className="muted">{w.minutes ?? 0} мин</span>
        </div>
      ))}
      <div className="q-sec">Ожидают</div>
      {snap.waiting.map((w) => (
        <div key={w.code} className="q-row" onClick={() => { window.location.hash = `#${w.code}` }}>
          <span className="code">{w.code}</span><span className="q-t">{w.status}</span>
          <span className="muted">попыток {w.attempts}</span>
        </div>
      ))}
      <div className="q-sec">Заблокированы</div>
      {snap.blocked.map((b) => (
        <div key={b.code} className="q-row" onClick={() => { window.location.hash = `#${b.code}` }}>
          <span className="code">{b.code}</span><span className="q-t">{b.reason}</span>
        </div>
      ))}
    </div>
  )
}

function Journal() {
  const [rows, setRows] = useState<{ who: string; entity: string; summary: string; diff: { field: string; old: string; new: string }[]; at: string }[]>([])
  useEffect(() => { void fetch('/api/v1/settings-journal').then((r) => r.json()).then(setRows) }, [])
  return (
    <div className="set-body">
      {rows.map((r, i) => (
        <div key={i} className="jr-row">
          <time>{r.at.slice(0, 16).replace('T', ' ')}</time>
          <div className="jr-b">
            <b>{r.who}</b> · {r.summary}
            <div className="jr-diff">
              {(r.diff ?? []).map((d, j) => (
                <span key={j} className={j % 2 ? 'new' : 'old'}>{d.field}: {String(d.old ?? '—')} → {String(d.new ?? '—')}</span>
              ))}
            </div>
          </div>
        </div>
      ))}
      {rows.length === 0 && <div className="empty"><b>Журнал пуст</b>правки настроек появятся здесь</div>}
    </div>
  )
}


/* ==================== Менеджер колонок доски ==================== */

function ColumnManager({ onClose }: { onClose: () => void }) {
  const [cols, setCols] = useState<{ id: string; label: string; color: string; position: number }[]>([])
  const [usage, setUsage] = useState<Record<string, number>>({})
  const [newLabel, setNewLabel] = useState('')
  const reload = () => {
    void api.aliasColumns().then((c) => setCols([...c].sort((a, b) => a.position - b.position)))
  }
  useEffect(reload, [])

  return (
    <div className="colmap-panel" aria-label="Колонки доски">
      <div className="blk-h"><h3>Колонки доски</h3><span className="fill" />
        <button className="icon-btn" onClick={onClose}>✕</button></div>
      <div className="col-mgr">
        {cols.map((c) => (
          <div key={c.id} className="cm-row">
            <span className="cdot" style={{ background: c.color }} />
            <input className="cm-name" defaultValue={c.label}
              onBlur={(e) => e.target.value !== c.label &&
                void api.updateColumn(c.id, { label: e.target.value }).then(reload)} />
            <button className="colh-x" title="Удалить" onClick={async () => {
              try {
                await api.deleteColumn(c.id); reload()
              } catch (err) { toast((err as Error).message, 'bad') }
            }}>✕</button>
          </div>
        ))}
      </div>
      <div className="cl-add">
        <input placeholder="Новая колонка…" value={newLabel}
          onChange={(e) => setNewLabel(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && newLabel.trim()) {
              void api.createColumn({ label: newLabel.trim() }).then(() => { setNewLabel(''); reload() })
            }
          }} />
      </div>
      <div className="muted mt8">Колонка без статусов удаляется автоматически; статус живёт ровно в одной колонке.</div>
    </div>
  )
}

/* ==================== Мастер нового типа задач ==================== */

function TypeWizard({ onClose, onCreated }: { onClose: () => void; onCreated: (key: string) => void }) {
  const [key, setKey] = useState('')
  const [label, setLabel] = useState('')
  const [cloneFrom, setCloneFrom] = useState('common_task')
  const [note, setNote] = useState<string | null>(null)

  const create = async () => {
    const res = await fetch('/api/v1/task-types', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key, label, cloneFrom }),
    })
    const body = await res.json().catch(() => ({}))
    if (!res.ok) { setNote(body.message); return }
    toast(`Тип «${label}» создан, flow опубликован`, 'ok')
    onCreated(key)
  }

  return (
    <div className="colmap-panel" aria-label="Новый тип задач">
      <div className="blk-h"><h3>Новый тип задач</h3><span className="fill" />
        <button className="icon-btn" onClick={onClose}>✕</button></div>
      <div className="f-field"><label>Ключ (строчные латиница, цифры, _)</label>
        <input className="mono" value={key} onChange={(e) => setKey(e.target.value.toLowerCase())} /></div>
      <div className="f-field"><label>Название на интерфейсе</label>
        <input value={label} onChange={(e) => setLabel(e.target.value)} /></div>
      <div className="f-field"><label>Собрать из пресета</label>
        <select value={cloneFrom} onChange={(e) => setCloneFrom(e.target.value)}>
          {FLOW_TYPES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select></div>
      {note && <div className="check-row err">{note}</div>}
      <div className="edit-actions">
        <button className="btn primary small" onClick={() => void create()}>Создать тип</button>
        <button className="btn small" onClick={onClose}>Отмена</button>
      </div>
      <div className="muted mt8">Автомат подхватит новый тип сам: сборка flow из пресета, задачи — в alias-колонках.</div>
    </div>
  )
}


function AgCellPopover({ statusKey, people, entries, defaultMode, onApply }: {
  statusKey: string
  people: { id: string; name: string; userType: string }[]
  entries: { userId: string; name: string; mode: string }[]
  defaultMode: string
  onApply: (entries: { userId: string; mode: string }[]) => void
}) {
  const [open, setOpen] = useState(false)
  const [picked, setPicked] = useState<Record<string, boolean>>(
    Object.fromEntries(entries.map((e) => [e.userId, true])))

  return (
    <span style={{ position: 'relative' }}>
      <button className="btn small" onClick={() => setOpen(!open)}>＋ назначить</button>
      {open && (
        <div className="ag-pop" onClick={(e) => e.stopPropagation()}>
          {people.map((p) => (
            <label key={p.id} className="f-check" style={{ display: 'flex' }}>
              <input type="checkbox" checked={Boolean(picked[p.id])}
                onChange={(e) => setPicked((prev) => ({ ...prev, [p.id]: e.target.checked }))} />
              {p.name} <span className="muted">({p.userType === 'agent' ? 'агент' : 'человек'})</span>
            </label>
          ))}
          <div className="edit-actions">
            <button className="btn small primary" onClick={() => {
              onApply(Object.entries(picked).filter(([, on]) => on)
                .map(([userId], i) => ({ userId, mode: defaultMode })))
              setOpen(false)
            }}>Применить</button>
            <button className="btn small" onClick={() => setOpen(false)}>Отмена</button>
          </div>
          <div className="muted" style={{ fontSize: 11 }}>Статус: {statusKey}</div>
        </div>
      )}
    </span>
  )
}
