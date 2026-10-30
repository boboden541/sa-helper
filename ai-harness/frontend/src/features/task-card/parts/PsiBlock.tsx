// ПСИ-блок (.psi-doc): пункты приёмо-сдаточных испытаний, прогон с фактическими
// результатами, протоколы прогонов, новый цикл. Перенесено из TaskView.tsx 1:1.

import { useEffect, useState } from 'react'
import { api } from '../../../api/client'
import { toast } from '../../../shared/toast'

export function PsiBlock({ code, reload, psiPath }: { code: string; reload: () => void; psiPath: string | null }) {
  const [doc, setDoc] = useState<{ items: { position: number; kind: string; text: string; expected?: string; actual?: string; status: string; bugTaskId?: string }[]; runs: { id: string; passed: number; failed: number }[] } | null>(null)
  const [runMode, setRunMode] = useState(false)
  const [results, setResults] = useState<Record<number, { passed: boolean; actual: string }>>({})
  const reloadPsi = () => { void api.psi(code).then(setDoc).catch(() => { /* ПСИ ещё нет — норма */ }) }
  useEffect(reloadPsi, [code])

  const savePath = psiPath?.trim() || `.harness/psi/${code}/psi.md`
  if (!doc || doc.items.length === 0) {
    return <div className="blk"><div className="blk-h"><h3>ПСИ</h3></div>
      <div className="muted" style={{ fontSize: 11, marginBottom: 6 }}>Сохраняется в: <span className="mono">{savePath}</span></div>
      <div className="muted">Документ ПСИ ещё не составлен</div></div>
  }
  const versions = doc.runs.length

  return (
    <div className="blk">
      <div className="blk-h"><h3>ПСИ · приёмо-сдаточные испытания</h3></div>
      <div className="psi-doc">
        <div className="psi-head"><b>ПСИ</b> · пунктов: {doc.items.filter((i) => i.kind === 'item').length} · протоколов: {versions}</div>
        {doc.items.filter((i) => i.kind === 'heading').length > 0 && null}
        {doc.items.filter((i) => i.kind === 'item').map((i) => (
          <div key={i.position} className={`psi-item ${runMode ? 'run' : ''}`}>
            <span className="n num">{i.position}.</span>
            <span className="a">
              {i.text}
              <span className="exp">Ожидаемо: {i.expected}</span>
              {runMode && (
                <>
                  <input className="psi-fact" placeholder="Фактический результат…"
                    value={results[i.position]?.actual ?? ''}
                    onChange={(e) => setResults((r) => ({ ...r, [i.position]: { passed: r[i.position]?.passed ?? true, actual: e.target.value } }))} />
                  <div className="psi-runbtns" style={{ flexDirection: 'row', gap: 6 }}>
                    <button className={`btn small ${results[i.position]?.passed === true ? 'primary' : ''}`}
                      onClick={() => setResults((r) => ({ ...r, [i.position]: { passed: true, actual: r[i.position]?.actual ?? '' } }))}>✓ Пройден</button>
                    <button className={`btn small danger ${results[i.position]?.passed === false ? 'primary' : ''}`}
                      onClick={() => setResults((r) => ({ ...r, [i.position]: { passed: false, actual: r[i.position]?.actual ?? '' } }))}>✗ Не пройден</button>
                  </div>
                </>
              )}
              {!runMode && i.actual && <span className={`fact ${i.status === 'failed' ? '' : 'ok'}`}>Факт: {i.actual}</span>}
            </span>
            <span className={`badge ${''}`} style={{ ['--bc' as string]: i.status === 'failed' ? '#cf4436' : i.status === 'done' ? '#25935b' : '#8792a3' }}>
              {i.status === 'done' ? 'пройден' : i.status === 'failed' ? 'не пройден' : 'не прогонялся'}
            </span>
          </div>
        ))}
        <div className="psi-runs">
          {runMode
            ? <>
                <button className="btn primary small" onClick={async () => {
                  const r = await api.psiRun(code, Object.entries(results).map(([position, v]) => ({
                    position: Number(position), passed: v.passed, actual: v.actual })))
                  toast(`Прогон: ${r.passed} ✓ / ${r.failed} ✗` +
                    (r.bugProposals.length ? ` · предложено багов: ${r.bugProposals.length}` : ''), r.failed ? 'bad' : 'ok')
                  setRunMode(false); setResults({}); reloadPsi(); reload()
                }}>Завершить прогон</button>
                <button className="btn small" onClick={() => { setRunMode(false); setResults({}) }}>Отмена</button>
              </>
            : <>
                <button className="btn small" onClick={() => setRunMode(true)}>▶ Начать прогон</button>
                <button className="btn small" onClick={async () => {
                  await fetch(`/api/v1/stories/${code}/psi/new-cycle`, { method: 'POST' })
                  toast('Новый цикл: пункты сброшены, протоколы целы', 'ok'); reloadPsi()
                }}>Новый цикл</button>
                {doc.runs.map((r) => (
                  <span key={r.id} className="mini-chip">{r.passed}✓/{r.failed}✗</span>
                ))}
              </>}
        </div>
      </div>
    </div>
  )
}
