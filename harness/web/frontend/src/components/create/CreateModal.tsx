import { useEffect, useState } from "react";
import type { Story } from "../../types";
import { api } from "../../api";

export function CreateModal({ onClose, onCreated, stories, preselectedFnr, initialType = "story" }: {
  onClose: () => void;
  onCreated: () => void;
  stories: Story[];
  preselectedFnr?: string | null;
  initialType?: "story" | "task";
}) {
  const [type, setType] = useState<"story" | "task">(initialType);
  const [title, setTitle] = useState("");
  const [source, setSource] = useState("");
  const preTitle = preselectedFnr
    ? stories.find((s) => s.fnr === preselectedFnr)?.title || ""
    : "";
  const [storyQuery, setStoryQuery] = useState(
    preselectedFnr ? `${preselectedFnr} — ${preTitle}` : "");
  const [picked, setPicked] = useState<string | null>(preselectedFnr ?? null);
  const [showPicks, setShowPicks] = useState(false);
  const [taskTitle, setTaskTitle] = useState("");
  const [desc, setDesc] = useState("");
  const [system, setSystem] = useState("");
  const [msg, setMsg] = useState("");
  useEffect(() => { setType(initialType); }, [initialType]);

  const hits = storyQuery.trim()
    ? stories.filter((s) =>
        s.fnr.toLowerCase().includes(storyQuery.toLowerCase()) ||
        s.title.toLowerCase().includes(storyQuery.toLowerCase())).slice(0, 8)
    : [];

  const pick = (s: Story) => {
    setPicked(s.fnr);
    setStoryQuery(`${s.fnr} — ${s.title}`);
    setShowPicks(false);
    const systems = [...new Set(s.task_list.map((t) => t.system).filter((x): x is string => !!x))];
    if (systems.length) setSystem(systems[0]);
  };

  const submit = () => {
    if (type === "story") {
      if (!title.trim() || !source.trim()) { setMsg("нужны название и описание"); return; }
      setMsg("создаю…");
      api.createStory(title.trim(), source.trim()).then((d) => {
        if (d.ok) { setMsg(""); onCreated(); onClose(); }
        else setMsg(d.info);
      });
    } else {
      if (!picked) { setMsg("выберите Story"); return; }
      if (!taskTitle.trim()) { setMsg("нужно название задачи"); return; }
      api.createTask(picked, {
        title: taskTitle.trim(),
        description: desc.trim() || undefined,
        system: system.trim() || undefined,
      }).then(() => { setMsg(""); onCreated(); onClose(); });
    }
  };

  return (
    <div className="modal-bg" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal">
        <h3>Создать</h3>
        <div className="type-seg">
          <button className={type === "story" ? "active" : ""}
            onClick={() => setType("story")}>Story — требования → план</button>
          <button className={type === "task" ? "active" : ""}
            onClick={() => setType("task")}>Task — в рамках Story</button>
        </div>

        {type === "story" ? (
          <>
            <label>Название Story</label>
            <input type="text" value={title} autoFocus
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Например: Перевод импорта на draft_db" />
            <label>Описание / системные требования (markdown)</label>
            <textarea value={source} onChange={(e) => setSource(e.target.value)}
              placeholder="Текст СТ…" />
            <div className="hint">Демон построит план (/impl-handoff). Если требований не
              хватает — честный gap-report появится на карточке Story.</div>
          </>
        ) : (
          <>
            <label>Story</label>
            <input type="text" value={storyQuery} autoFocus
              onChange={(e) => { setStoryQuery(e.target.value); setShowPicks(true); }}
              placeholder="Начните вводить название или FNR…" />
            {showPicks && hits.length > 0 && (
              <div className="pick-list">
                {hits.map((s) => (
                  <div className="pick-item" key={s.fnr} onClick={() => pick(s)}>
                    <span className="fnr">{s.fnr}</span>{s.title}
                  </div>
                ))}
              </div>
            )}
            <label>Название задачи</label>
            <input type="text" value={taskTitle}
              onChange={(e) => setTaskTitle(e.target.value)}
              placeholder="Что нужно сделать" />
            <label>Описание</label>
            <textarea value={desc} onChange={(e) => setDesc(e.target.value)}
              placeholder="Детали: что и зачем, критерии приёмки…" />
            <label>Система</label>
            <input type="text" value={system} onChange={(e) => setSystem(e.target.value)}
              placeholder="— берётся из Story по умолчанию" />
            <div className="hint">Задача войдёт в бэклог Story (origin: manual); конвейер
              поставит её в очередь по зависимостям.</div>
          </>
        )}

        <div className="mrow">
          <button className="ghost" onClick={onClose}>Отмена</button>
          <button className="primary" onClick={submit}>Создать</button>
        </div>
        {msg && <div className="hint">{msg}</div>}
      </div>
    </div>
  );
}
