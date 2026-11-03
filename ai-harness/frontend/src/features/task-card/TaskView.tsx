// Карточка задачи — DOM design_mockup/app.js:1018-1148 (drawer + полная страница):
// task-head (tcode, h2, pencil), meta-row (st-chip, prio, story-link, даты, тип+агент),
// теги, callouts модерации/блокировки, trans + trans-reasons, desc-view .md / editbar,
// чеклисты .cl с .cbx/.badge/.cl-x и текстовым режимом .cl-text, ПСИ .psi-doc,
// force details, хроники .chron-tabs/.chron-row/.evt/.tech.
// Каркас (TaskView/TaskDrawer/TaskFullPage/TaskBody) здесь; подкомпоненты — в parts/*.

import { useEffect, useState } from 'react'
import { api, type TaskCard } from '../../api/client'
import { S_LABEL } from '../../shared/refs'
import { XIcon } from '../../shared/chips'
import { toast } from '../../shared/toast'
import { TaskHead } from './parts/TaskHead'
import { TransBlock } from './parts/TransBlock'
import { DescBlock } from './parts/DescBlock'
import { ChecklistBlock } from './parts/ChecklistBlock'
import { PsiBlock } from './parts/PsiBlock'
import { ChronicleBlock } from './parts/ChronicleBlock'
import { ArtifactBlock } from './parts/ArtifactBlock'
import { CommentsBlock } from './parts/CommentsBlock'
import { RelationsBlock } from './parts/RelationsBlock'
import type { ChronicleItem, LiveRun } from './parts/common'

function useTaskCode(): string | null {
  const hash = window.location.hash.replace(/^#/, '')
  const m = hash.match(/^([A-Za-z]{2,10}-\d+)/)
  return m ? m[1].toUpperCase() : null
}

export function TaskView() {
  const code = useTaskCode()
  const [page, setPage] = useState(window.location.hash.endsWith('/page'))
  useEffect(() => {
    const onHash = () => setPage(window.location.hash.endsWith('/page'))
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  if (!code) return <div className="empty"><b>Задача не открыта</b>выберите задачу на доске или в поиске</div>
  return page
    ? <TaskFullPage code={code} />
    : <TaskDrawer code={code} />
}

function TaskDrawer({ code }: { code: string }) {
  return (
    <>
      <div className="scrim show" onClick={() => { window.location.hash = '#board' }} />
      <aside className="drawer show" aria-label="Карточка задачи">
        <div className="drawer-head">
          <span className="crumb">Проект · <b>{code}</b></span>
          <span className="sp" />
          <button className="btn small" onClick={() => { window.location.hash = `#${code}/page` }}>Полная страница</button>
          <button className="icon-btn" aria-label="Закрыть" onClick={() => { window.location.hash = '#board' }}><span><XIcon /></span></button>
        </div>
        <div className="drawer-body"><TaskBody code={code} /></div>
      </aside>
    </>
  )
}

function TaskFullPage({ code }: { code: string }) {
  return (
    <section className="taskpage" aria-label="Полная страница задачи">
      <div className="tp-head">
        <span className="crumb"><b>{code}</b> · полная страница</span>
        <button className="btn small" onClick={() => { window.location.hash = `#${code}` }}>← К доске</button>
      </div>
      <div className="tp-body"><div className="tp-inner"><TaskBody code={code} /></div></div>
    </section>
  )
}

function TaskBody({ code }: { code: string }) {
  const [card, setCard] = useState<TaskCard | null>(null)
  const [chronicle, setChronicle] = useState<ChronicleItem[]>([])
  const [liveRun, setLiveRun] = useState<LiveRun | null>(null)
  const [lastLog, setLastLog] = useState('')

  // подпись статуса: точная — из flow-версии задачи (gate.labels),
  // фолбэк — канонический словарь; кастомные статусы владельца не показываются ключами
  const L = (key: string): string =>
    (card as { gate?: { labels?: Record<string, string> } } | null)?.gate?.labels?.[key]
      ?? S_LABEL[key] ?? key
  const reload = () => {
    void api.task(code).then((c) => { setCard(c) })
      .catch(() => toast(`Задача ${code} не найдена`, 'bad'))
    void api.chronicle(code).then((r) => setChronicle(r.items))
      .catch(() => { /* хроника не критична: тихий фолбэк */ })
  }
  useEffect(reload, [code])

  // живой поток карточки (решение владельца 27.10.2026): активный прогон, токены,
  // строки лога и новые записи хроники появляются в реальном времени
  useEffect(() => {
    const es = new EventSource(`/api/v1/tasks/${code}/live`)
    es.addEventListener('run', (e) => {
      try {
        const d = JSON.parse((e as MessageEvent).data) as { agent?: string; minutes?: number; total?: number; stale?: boolean }
        setLiveRun(d.agent ? { agent: d.agent, minutes: d.minutes ?? 0, total: d.total ?? 0, stale: Boolean(d.stale) } : null)
        if (d.agent) reload()
      } catch { /* пустое событие — прогон завершён */ }
    })
    es.addEventListener('log', (e) => {
      try {
        const d = JSON.parse((e as MessageEvent).data) as { kind: string; text: string | null }
        if (d.text && d.kind !== 'prompt') setLastLog((d.text ?? '').slice(0, 140))
      } catch { /* ignore */ }
    })
    es.addEventListener('chronicle', (e) => {
      try {
        const item = JSON.parse((e as MessageEvent).data) as ChronicleItem
        setChronicle((cur) => cur.some((x) => x.id === item.id) ? cur : [{ ...item, live: true }, ...cur])
      } catch { /* ignore */ }
    })
    es.onerror = () => { /* браузер переподключится сам */ }
    return () => es.close()
    // reload пересоздаётся каждым рендером — SSE-поток живёт по code
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code])

  if (!card) return <div className="empty"><b>Загрузка…</b></div>

  const typeVisible = {
    developer: ['common_task', 'bug'].includes(card.type),
    reviewer: ['common_task', 'analyse_task'].includes(card.type),
    tester: ['common_task', 'qa_task', 'bug', 'story'].includes(card.type),
  }

  return (
    <>
      <TaskHead code={code} card={card} liveRun={liveRun} reload={reload} />

      {/* панель модерации «Одобрить/Отклонить» удалена (замечание владельца
        03.11.2026): рудимент старой реализации — «Одобрить» вела в статус
        backlog, которого в актуальных flow нет; переходы по статусам —
        кнопки TransBlock из gate.allowed ниже */}
      {card.statusKey === 'blocked' && (
        <div className="callout bad">
          <span className="ci">⛔</span>
          <div className="body">{card.blockedReason || 'Работа заблокирована'}</div>
        </div>
      )}

      <TransBlock code={code} card={card} L={L} reload={reload} />

      <DescBlock code={code} card={card} reload={reload} />

      <RelationsBlock code={code} relations={card.relations ?? []} reload={reload} />

      {typeVisible.developer && <ChecklistBlock code={code} kind="developer" title="Smart чек-лист разработчика" />}
      {typeVisible.reviewer && <ChecklistBlock code={code} kind="reviewer" title="Чек-лист ревьюера" />}
      {typeVisible.tester && <ChecklistBlock code={code} kind="tester" title="Чек-лист тестировщика" />}

      {card.type === 'story' && <PsiBlock code={code} reload={reload} psiPath={card.psiPath ?? null} />}

      {typeVisible.reviewer && <ArtifactBlock code={code} kind="review_report" title="Отчёт о ревью" />}
      {typeVisible.tester && card.type !== 'story' && <ArtifactBlock code={code} kind="qa_report" title="Отчёт о тестировании" />}

      <CommentsBlock code={code} />

      <ChronicleBlock code={code} chronicle={chronicle} liveRun={liveRun} lastLog={lastLog} />
    </>
  )
}
