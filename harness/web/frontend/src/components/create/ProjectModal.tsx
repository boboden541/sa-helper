import { useState } from "react";
import type { Project } from "../../types";
import { api } from "../../api";
import { toast } from "../common/toasts";

/** Проект: добавление (имя + путь, пустая папка инициализируется — СТ 4.1.3)
 *  или правка alias/описания с удалением (СТ 4.1.2/5.1.1). */
export function ProjectModal({ project, onClose, onAdded }: {
  project?: Project;                       // режим правки
  onClose: () => void;
  onAdded: (name: string) => void;
}) {
  const [name, setName] = useState(project?.name ?? "");
  const [path, setPath] = useState(project?.path ?? "");
  const [alias, setAlias] = useState(project?.alias ?? "");
  const [descr, setDescr] = useState(project?.description ?? "");
  const [msg, setMsg] = useState("");

  const editMode = !!project;

  const submitEdit = () => {
    if (!project) return;
    setMsg("сохраняю…");
    api.patchProject(project.name, {
      alias: alias.trim(), description: descr.trim(),
    }).then(() => {
      toast.ok(`Проект ${project.name} обновлён`);
      setMsg("");
      onAdded(project.name);
      onClose();
    }).catch((e) => setMsg(e.message));
  };

  const submitAdd = () => {
    if (!name.trim() || !path.trim()) { setMsg("нужны имя и путь"); return; }
    setMsg("добавляю…");
    api.addProject(name.trim(), path.trim(), alias.trim() || undefined,
                   descr.trim() || undefined).then((d) => {
      if (d.ok) {
        toast.ok(d.info);
        setMsg("");
        onAdded(name.trim());
        onClose();
      } else setMsg(d.info);
    }).catch((e) => setMsg(e.message));
  };

  const submitDelete = () => {
    if (!project) return;
    const p = project;
    api.deleteProject(p.name, false, p.auto_registered).then((r) => {
      if (r.ok) {
        toast.info(r.deferred
          ? `${p.name}: живая стадия дорабатывает — проект стирается после неё`
          : `${p.name} удалён`);
        onAdded(p.name);
        onClose();
      } else if (r.cascade) {
        if (window.confirm(`${r.error}\n\nСтереть безвозвратно?`)) {
          api.deleteProject(p.name, true, p.auto_registered).then((r2) => {
            if (r2.ok) {
              toast.info(r2.deferred
                ? `${p.name}: живая стадия дорабатывает — проект стирается после неё`
                : `${p.name} удалён`);
              onAdded(p.name);
              onClose();
            } else toast.err(r2.error || "Не удалось удалить");
          });
        } else setMsg("");
      } else {
        toast.err(r.error || "Не удалось удалить");
        setMsg("");
      }
    });
  };

  return (
    <div className="modal-bg" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal">
        <h3>{editMode ? `Проект ${project!.name}` : "Добавить проект"}</h3>
        {!editMode && (
          <>
            <label>Название проекта</label>
            <input type="text" value={name} autoFocus onChange={(e) => setName(e.target.value)}
              placeholder="Например: vitrina" />
            <label>Путь к каталогу воркспейса на компьютере</label>
            <input type="text" value={path} onChange={(e) => setPath(e.target.value)}
              placeholder="/Users/you/projects/my-workspace" />
            <div className="hint">Пустая папка получит базовую структуру (README, .gitignore,
              репозиторий). Демон и витрина подхватят проект автоматически.</div>
          </>
        )}
        <label>Псевдоним (alias)</label>
        <input type="text" value={alias} onChange={(e) => setAlias(e.target.value)}
          placeholder="короткое имя для витрины" />
        <label>Описание</label>
        <input type="text" value={descr} onChange={(e) => setDescr(e.target.value)}
          placeholder="что это за проект" />
        <div className="mrow">
          <button className="ghost" onClick={onClose}>Отмена</button>
          {!editMode && <button className="primary" onClick={submitAdd}>Добавить</button>}
          {editMode && (
            <>
              <button style={{ color: "var(--bad)" }}
                onClick={submitDelete}>🗑 Удалить проект</button>
              <button className="primary" onClick={submitEdit}>Сохранить</button>
            </>
          )}
        </div>
        {msg && <div className="hint">{msg}</div>}
      </div>
    </div>
  );
}
