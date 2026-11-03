// Единственный источник цветов статусов (бывший дубликат в TaskCard.tsx):
// левая полоса карточки, полоса истории, точки в ColmapPanel. progress —
// алиас in_progress, оставлен для совместимости с сида.
export const STATUS_COLORS: Record<string, string> = {
  pending: '#c07d1e', backlog: '#8792a3', todo: '#1f8fb5', progress: '#3d63d2', in_progress: '#3d63d2',
  review_ready: '#7d4fd1', in_review: '#7d4fd1', qa_ready: '#c2601a', in_testing: '#c2601a',
  done: '#25935b', canceled: '#8792a3', blocked: '#cf4436',
}
