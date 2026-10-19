import { useEffect, useRef, useState } from "react";

/** Модульный dirty-guard: backdrop и Escape спрашивают редактор перед закрытием. */
let dirtyGuard: (() => boolean) | null = null;
export function cardEditorConfirmClose(): boolean {
  return !dirtyGuard || dirtyGuard();
}

/** Секции чек-листа markdown-строки — зеркало серверного parse_checklist_sections:
 *  секция = любой «## …», после которого есть ≥1 чекбокса канона `- [ ~xrbf ]`.
 *  Нужно для предупреждения при правке чек-лист-секций («План работ (чек-лист)»
 *  ведёт исполнитель, «Доработка по ревью (чек-лист)» — ревьюер). */
function checklistSections(md: string): string[] {
  const sections: string[] = [];
  let cur: string[] | null = null;
  let hasBox = false;
  for (const line of md.split("\n")) {
    if (/^##\s+/.test(line)) {
      if (cur && hasBox) sections.push(cur.join("\n"));
      cur = [line];
      hasBox = false;
    } else if (cur) {
      if (/^\s*-\s+\[( |~|x|r|b|f)\]/.test(line)) hasBox = true;
      cur.push(line);
    }
  }
  if (cur && hasBox) sections.push(cur.join("\n"));
  return sections;
}

/** Редактор описания задачи (карточка = единый источник).
 *  Д2: режим «Текст» (markdown + тулбар вставки); «Визуальный» — в Д3.
 *  dirty — флаг по событию ввода (не diff строк: round-trip даёт шум). */
export function CardEditor({ cardMd, liveRunning, onSave, onCancel }: {
  cardMd: string;
  liveRunning: boolean;
  onSave: (cardMd: string, opts: { force: boolean }) => void;
  onCancel: () => void;
}) {
  const [text, setText] = useState(cardMd);
  const [dirty, setDirty] = useState(false);
  const areaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    dirtyGuard = () => {
      if (!dirty) return true;
      return window.confirm("Есть несохранённые правки описания. Закрыть без сохранения?");
    };
    const onUnload = (e: BeforeUnloadEvent) => {
      if (dirty) { e.preventDefault(); e.returnValue = ""; }
    };
    window.addEventListener("beforeunload", onUnload);
    return () => {
      dirtyGuard = null;
      window.removeEventListener("beforeunload", onUnload);
    };
  }, [dirty]);

  const touch = () => setDirty(true);

  /** Вставка markdown-конструкции вокруг выделения (тулбар текстового режима). */
  const wrap = (before: string, after = "", placeholder = "") => {
    const el = areaRef.current;
    if (!el) return;
    const s = el.selectionStart, e = el.selectionEnd;
    const sel = text.slice(s, e) || placeholder;
    setText(text.slice(0, s) + before + sel + after + text.slice(e));
    touch();
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(s + before.length, s + before.length + sel.length);
    });
  };

  const prefixLines = (prefix: string) => {
    const el = areaRef.current;
    if (!el) return;
    const s = el.selectionStart, e = el.selectionEnd;
    const start = text.lastIndexOf("\n", s - 1) + 1;
    const end = text.indexOf("\n", e) === -1 ? text.length : text.indexOf("\n", e);
    const block = text.slice(start, end).split("\n")
      .map((l) => (l.trim() ? (l.startsWith(prefix) ? l : prefix + l) : l))
      .join("\n");
    setText(text.slice(0, start) + block + text.slice(end));
    touch();
    requestAnimationFrame(() => { el.focus(); el.setSelectionRange(start, start + block.length); });
  };

  const addLink = () => {
    const url = window.prompt("Адрес ссылки (https://…)");
    if (!url || !/^https?:\/\//.test(url)) return;
    wrap("[", `](${url})`, "текст ссылки");
  };

  const cancel = () => {
    if (!dirty || window.confirm("Отменить несохранённые правки описания?")) onCancel();
  };

  const save = () => {
    if (liveRunning && !window.confirm(
      "Сессия агента сейчас работает — правка карточки может затереться "
      + "её изменениями. Сохранить принудительно?")) return;
    if (!liveRunning
        && JSON.stringify(checklistSections(cardMd)) !== JSON.stringify(checklistSections(text))
        && !window.confirm(
          "Вы изменили чек-лист-секции карточки. Их ведут исполнитель и ревьюер "
          + "(«План работ», «Доработка по ревью») — потеря ломает петлю доработки. "
          + "Сохранить?")) return;
    onSave(text, { force: liveRunning });
  };

  return (
    <div className="ced">
      <div className="ced-bar">
        <button className="ced-btn" title="Заголовок раздела" onClick={() => prefixLines("## ")}>H2</button>
        <button className="ced-btn" title="Подзаголовок" onClick={() => prefixLines("### ")}>H3</button>
        <button className="ced-btn" title="Жирный" onClick={() => wrap("**", "**", "жирный")}><b>B</b></button>
        <button className="ced-btn" title="Курсив" onClick={() => wrap("*", "*", "курсив")}><i>I</i></button>
        <button className="ced-btn" title="Ссылка" onClick={addLink}>🔗</button>
        <button className="ced-btn" title="Список" onClick={() => prefixLines("- ")}>≡</button>
        <button className="ced-btn" title="Нумерованный список" onClick={() => prefixLines("1. ")}>1.</button>
        <button className="ced-btn" title="Чекбокс" onClick={() => wrap("- [ ] ", "", "пункт")}>☑</button>
        <button className="ced-btn" title="Код в строке" onClick={() => wrap("`", "`", "код")}>&lt;&gt;</button>
        <button className="ced-btn" title="Цитата" onClick={() => prefixLines("> ")}>❝</button>
        <span className="spacer" />
        {liveRunning && <span className="ced-live">⚠ сессия агента работает</span>}
      </div>
      <textarea ref={areaRef} className="ced-text" value={text} spellCheck={false}
        onChange={(e) => { setText(e.target.value); touch(); }} />
      <div className="ced-foot">
        <div className="ced-modes">
          <button className="ced-tab on">Текст</button>
          <button className="ced-tab" disabled title="Появится в следующей порции">Визуальный</button>
        </div>
        <span className="spacer" />
        <button className="ghost" onClick={cancel}>Отмена</button>
        <button className="primary" onClick={save}>Сохранить</button>
      </div>
    </div>
  );
}
