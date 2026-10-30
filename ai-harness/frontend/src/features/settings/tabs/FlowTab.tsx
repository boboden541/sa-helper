// Вкладка «Status-flow» — полноценный редактор: seg типов, граф (fs-card + edges +
// fs-conn протягивание) и таблица (tr-chip) одной рабочей копии, flow-panel,
// publish-panel. Перенесено из монолита Settings.tsx разметка 1:1.

import { useEffect, useRef, useState } from 'react'
import { api } from '../../../api/client'
import { FLOW_TYPES } from '../shared'

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

export function FlowEditor({ reload }: { reload: () => void }) {
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

  const flowPanel = (
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
              <div className="muted">Кликните по карточке статуса, стрелке или строке таблицы — здесь откроется редактирование. Новый переход: потяните за «+» на краю карточки.</div>
            )}
          </div>
  )

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
                  // двунаправленная пара: дуги разводятся по разные стороны
                  // линии между статусами (решение владельца 28.10.2026)
                  const reverse = data.transitions.some((o) => o.from === t.to && o.to === t.from)
                  let ax = a.x, ay = a.y, bx = b.x, by = b.y, mx = (a.x + b.x) / 2
                  if (reverse) {
                    const dx = b.x - a.x, dy = b.y - a.y
                    const len = Math.hypot(dx, dy) || 1
                    const sgn = t.from < t.to ? 1 : -1
                    const ox = (-dy / len) * 20 * sgn, oy = (dx / len) * 20 * sgn
                    ax += ox; ay += oy; bx += ox; by += oy; mx += ox
                  }
                  const color = t.runner === 'auto' ? '#c9821f'
                    : t.runner === 'agent' ? '#9a74e0' : '#93a0b4'
                  const dirx = Math.sign(bx - mx) || 1
                  const ex = bx - dirx * 8   // линия не наезжает на наконечник
                  const d = `M ${ax} ${ay} C ${mx} ${ay}, ${mx} ${by}, ${ex} ${by}`
                  return (
                    <g key={i}>
                      <path className="line" style={{ stroke: color }} d={d}
                        onClick={() => setSel({ kind: 'edge', id: `${t.from}→${t.to}` })} />
                      <path className="hit" d={d} onClick={() => setSel({ kind: 'edge', id: `${t.from}→${t.to}` })} />
                      <polygon points="-7,-4.5 3,0 -7,4.5"
                        transform={`translate(${bx} ${by})${dirx < 0 ? ' rotate(180)' : ''}`}
                        fill={color} />
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
          {flowPanel}
        </div>
      ) : (
        <div className="flow-body">
                <div className="flow-canvas flow-table">
          <table className="tasks">
            <thead><tr>
              <th>Статус</th><th>Что происходит на этапе</th><th>Чеклист-гейт</th><th>Флаги</th>
              <th>Возможные переходы</th><th>Alias-колонка</th>
            </tr></thead>
              <tbody>
                {data.statuses.map((s) => (
                  <tr key={s.key} className={sel?.kind === 'status' && sel.id === s.key ? 'sel-row' : ''}
                    style={{ cursor: 'pointer' }} onClick={() => setSel({ kind: 'status', id: s.key })}>
                    <td><b>{s.label}</b> <span className="key mono muted">{s.key}</span></td>
                    <td className="muted">{s.stageDesc || '—'}</td>
                    <td>{s.gate
                      ? <span className="mini-chip mc-accent">{GATE_LABELS[s.gate] ?? s.gate}</span>
                      : <span className="muted">—</span>}</td>
                    <td>{(s.entry || s.terminal || s.blocking) ? (
                      <span>
                        {s.entry && <span className="mini-chip mc-accent">вход</span>}{' '}
                        {s.terminal && <span className="mini-chip mc-green">терм.</span>}{' '}
                        {s.blocking && <span className="mini-chip mc-red">блок.</span>}
                      </span>
                    ) : <span className="muted">—</span>}</td>
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
                    <td>{columns.find((c) => c.id === s.aliasColumnId)?.label
                      ?? <span style={{ color: 'var(--danger)' }}>— не назначена —</span>}</td>
                  </tr>
                ))}
              </tbody>
          </table>
          </div>
          {flowPanel}
        </div>
      )}
    </div>
  )
}
