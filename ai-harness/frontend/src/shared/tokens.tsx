// Разбивка расхода токенов (фича 30.10.2026): клик по сумме раскрывает
// блок «вход / выход / кэш». Сумма не меняется — раскрывается состав.
// Переключение у каждого места своё (карточка/список/шапка), хук useTokToggle
// удалён как неиспользуемый.

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
