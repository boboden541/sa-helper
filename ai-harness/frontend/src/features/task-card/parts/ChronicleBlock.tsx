// Хроники — chron-tabs по типам записей, живая строка агента (chron-live),
// chron-row с .evt/.tech, вкладка «Прогоны» (RunLogPanel). Перенесено из
// TaskView.tsx 1:1.

import { useState } from 'react'
import { fmtTokens } from '../../../shared/live'
import { RunLogPanel } from '../RunLogPanel'
import { type ChronicleItem, type LiveRun } from './common'

export function ChronicleBlock({ code, chronicle, liveRun, lastLog }: {
  code: string
  chronicle: ChronicleItem[]
  liveRun: LiveRun | null
  lastLog: string
}) {
  const [chronTab, setChronTab] = useState('all')
  const chronTypes = [
    ['runs', 'Прогоны'], ['all', 'все'], ['field', 'поле'], ['transition', 'переходы'],
    ['force', 'форс'], ['agent', 'агент'], ['psi', 'ПСИ'], ['bug', 'баг'],
  ]
  const chronFiltered = chronicle.filter((c) => chronTab === 'all' || c.type === chronTab)

  return (
    <div className="blk">
      <div className="blk-h"><h3>Хроники</h3></div>
      <div className="chron-tabs">
        {chronTypes.map(([key, label]) => (
          <button key={key} className={chronTab === key ? 'active' : ''} onClick={() => setChronTab(key)}>{label}</button>
        ))}
      </div>
      {chronTab !== 'runs' && liveRun && (
        <div className="chron-live" title="Записи появляются по мере работы агента">
          <span className={`dot ${liveRun.stale ? '' : 'pulse'}`} style={{ background: liveRun.stale ? '#c07d1e' : '#25935b' }} />
          <b>{liveRun.agent}</b> работает{liveRun.minutes ? ` · ${liveRun.minutes} мин` : ''}{liveRun.total ? ` · ${fmtTokens(liveRun.total)} токенов` : ''}
          {lastLog && <span className="ll"> · {lastLog}</span>}
        </div>
      )}
      {chronTab === 'runs' ? <RunLogPanel code={code} /> : chronFiltered.map((c) => (
        <div key={c.id} className={`chron-row ${c.live ? 'chron-new' : ''}`}>
          <time>{c.at.slice(11, 16)} · {c.at.slice(5, 10)}</time>
          <div className="chron-body">
            <span className="evt" style={{ ['--ec' as string]: evtColor(c.type) }}>{c.type}</span>
            {c.ruleCode && <span className="mini-chip mc-accent">{c.ruleCode}</span>} {c.message}
            <div className="who">{c.authorKind}</div>
          </div>
        </div>
      ))}
    </div>
  )
}

function evtColor(type: string): string {
  return { field: '#8792a3', transition: '#3d63d2', force: '#c2601a', agent: '#7d4fd1',
    denied: '#cf4436', psi: '#1f8fb5', bug: '#cf4436' }[type] ?? '#8792a3'
}
