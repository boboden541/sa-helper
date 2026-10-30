// Технические отчёты (.tech details): версии отчёта о ревью / тестирования
// и форма добавления нового. Перенесено из TaskView.tsx 1:1.

import { useEffect, useState } from 'react'
import { api } from '../../../api/client'

export function ArtifactBlock({ code, kind, title }: { code: string; kind: string; title: string }) {
  const [versions, setVersions] = useState<{ version: number; bodyMd: string; at: string }[]>([])
  const [body, setBody] = useState('')
  const reload = () => { void api.artifact(code, kind).then((d) => setVersions(d.versions ?? [])) }
  useEffect(reload, [code, kind])
  return (
    <div className="blk">
      <div className="blk-h"><h3>{title}</h3><span className="progr">{versions.length ? `v${versions[versions.length - 1].version}` : 'нет'}</span></div>
      {versions.map((v) => (
        <details key={v.version} className="tech">
          <summary>Версия v{v.version} · {v.at.slice(0, 16).replace('T', ' ')}</summary>
          <pre>{v.bodyMd}</pre>
        </details>
      ))}
      <textarea className="psi-fact" rows={3} placeholder="Новый отчёт (markdown)…"
        value={body} onChange={(e) => setBody(e.target.value)} />
      <button className="btn small mt8" disabled={!body.trim()} onClick={async () => {
        await api.addArtifact(code, kind, body); setBody(''); reload()
      }}>Добавить отчёт</button>
    </div>
  )
}
