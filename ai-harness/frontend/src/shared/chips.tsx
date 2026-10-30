// Чипы и бейджи как React-компоненты — байтово тот же DOM, что у HTML-хелперов
// из shared/refs.tsx (stChip / prioBadge / typeChip / tagHtml). Нужны доске,
// чтобы собирать карточки и полосы историй без dangerouslySetInnerHTML.
// Эквивалентность разметки закреплена тестом src/tests/chips.test.tsx:
// renderToStaticMarkup(<StChip/>) === stChip(...) для всех значений словарей.

import { PRIO, SC, S_LABEL, TYPE } from './refs'

export function StChip({ st }: { st: string }) {
  return (
    <span className="st-chip" style={{ ['--st' as string]: SC[st] ?? '#8792a3' }}>
      <span className="sdot" />
      {S_LABEL[st] ?? st}
    </span>
  )
}

function prioSvg(p: string) {
  const c = {
    fill: 'none',
    stroke: PRIO[p]?.c ?? '#8792a3',
    strokeWidth: 1.5,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
  }
  if (p === 'critical')
    return <svg width="13" height="13" viewBox="0 0 14 14"><path d="M3 12.5l4-4 4 4M3 7.5l4-4 4 4" {...c} /></svg>
  if (p === 'high')
    return <svg width="13" height="13" viewBox="0 0 14 14"><path d="M3 11.5l4-7 4 7" {...c} /></svg>
  if (p === 'low')
    return <svg width="13" height="13" viewBox="0 0 14 14"><path d="M3 2.5l4 7 4-7" {...c} /></svg>
  return <svg width="13" height="13" viewBox="0 0 14 14"><path d="M3 5.5h8M3 8.5h8" {...c} /></svg>
}

export function PrioBadge({ p, withLabel }: { p: string; withLabel?: boolean }) {
  return (
    <span className={`prio ${p}`} style={{ ['--pc' as string]: PRIO[p]?.c ?? '#8792a3' }}
      title={`Приоритет: ${PRIO[p]?.label ?? p}`}>
      {prioSvg(p)}
      {withLabel ? <span>{PRIO[p]?.label ?? p}</span> : null}
    </span>
  )
}

export function TypeChip({ t }: { t: string }) {
  return (
    <span className="type-chip" style={{ ['--tc' as string]: TYPE[t]?.c ?? '#8792a3' }}>
      {TYPE[t]?.label ?? t}
    </span>
  )
}

export function TagChip({ tag }: { tag: string }) {
  return (
    <span className={`tag ${tag === 'by_human' || tag === 'by_ai' ? 'sys' : ''}`}>#{tag}</span>
  )
}
