// Список всех задач таблицей с сортировкой очереди (ФТ-ah-15)

import type { TaskCard } from '../../api/client'

export function ListView({ tasks }: { tasks: TaskCard[] }) {
  return (
    <div className="listwrap">
      <table className="tasklist">
        <thead><tr><th>Код</th><th>Название</th><th>Тип</th><th>Статус</th><th>Приоритет</th></tr></thead>
        <tbody>
          {tasks.map((t) => (
            <tr key={t.code} onClick={() => { window.location.hash = `#${t.code}` }}>
              <td className="code">{t.code}</td>
              <td>{t.title}</td>
              <td><span className="chip">{t.type}</span></td>
              <td>{t.statusKey}</td>
              <td className={`prio prio-${t.priority}`}>{t.priority}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
