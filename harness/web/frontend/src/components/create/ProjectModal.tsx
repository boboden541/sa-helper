import { useState } from "react";
import { api } from "../../api";

/** Добавление проекта: имя + путь к каталогу воркспейса на компьютере. */
export function ProjectModal({ onClose, onAdded }: {
  onClose: () => void;
  onAdded: (name: string) => void;
}) {
  const [name, setName] = useState("");
  const [path, setPath] = useState("");
  const [msg, setMsg] = useState("");

  const submit = () => {
    if (!name.trim() || !path.trim()) { setMsg("нужны имя и путь"); return; }
    setMsg("добавляю…");
    api.addProject(name.trim(), path.trim()).then((d) => {
      if (d.ok) { setMsg(""); onAdded(name.trim()); onClose(); }
      else setMsg(d.info);
    });
  };

  return (
    <div className="modal-bg" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal">
        <h3>Добавить проект</h3>
        <label>Название проекта</label>
        <input type="text" value={name} autoFocus onChange={(e) => setName(e.target.value)}
          placeholder="Например: vitrina" />
        <label>Путь к каталогу воркспейса на компьютере</label>
        <input type="text" value={path} onChange={(e) => setPath(e.target.value)}
          placeholder="/Users/you/projects/my-workspace" />
        <div className="hint">В каталоге — Stories (sa_documentation/FNR/*) и системы
          из workspaces.yaml. Демон и витрина подхватят проект автоматически.</div>
        <div className="mrow">
          <button className="ghost" onClick={onClose}>Отмена</button>
          <button className="primary" onClick={submit}>Добавить</button>
        </div>
        {msg && <div className="hint">{msg}</div>}
      </div>
    </div>
  );
}
