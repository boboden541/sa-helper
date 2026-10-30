// Разбивка расхода токенов (фича 30.10.2026): клик по сумме раскрывает
// блок «вход / выход / кэш». Сумма не меняется — раскрывается состав.
import { useState } from 'react'

import { fmtTokens, type LiveTask } from './live'

export function TokSplit({ input, output, cache }: { input: number; output: number; cache: number }) {
  return (
    <span className="tok-split">
      <span>вход <b>{fmtTokens(input)}</b></span>
      <span>выход <b>{fmtTokens(output)}</b></span>
      <span>кэш <b>{fmtTokens(cache)}</b></span>
    </span>
  )
}

/** Составляющие суммы: в живом прогоне — значения потока, иначе накопленные. */
export function partsOf(live: LiveTask | null | undefined,
                        input = 0, output = 0, cache = 0): [number, number, number] {
  if (live && live.total) return [live.input, live.output, live.cache]
  return [input, output, cache]
}

/** Клик-переключатель разбивки: оборачивает сумму, возвращает [элемент, блок]. */
export function useTokToggle() {
  const [open, setOpen] = useState(false)
  const toggle = (e: React.MouseEvent) => { e.stopPropagation(); setOpen((v) => !v) }
  return [open, toggle] as const
}
