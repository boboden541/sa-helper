import { useEffect, useRef, useState } from "react";

/** Модульный dirty-guard: backdrop и Escape спрашивают редактор перед закрытием. */
let dirtyGuard: (() => boolean) | null = null;
export function cardEditorConfirmClose(): boolean {
  return !dirtyGuard || dirtyGuard();
}

/* ═══════════════ чистые функции: markdown ⇄ редакционный DOM ═══════════════ */

function esc(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/** Инлайн-markdown → HTML (без декоративных классов — для contentEditable). */
function inlineHtml(s: string): string {
  return esc(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/\*([^*\n]+)\*/g, "<i>$1</i>")
    .replace(/\[([^\]]+)\]\((https?:[^)\s"<>]+)\)/g,
      '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
}

const GLYPH: Record<string, string> = {
  " ": "○", "~": "⟳", "x": "✓", "r": "🔍", "b": "⛔", "f": "✗",
};

/** Секции чек-листа markdown-строки — зеркало серверного parse_checklist_sections. */
export function extractChecklistSections(md: string): string[] {
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

/** markdown → редакционный HTML. Таблицы, fenced-код и чек-лист-секции —
 *  read-only острова (contenteditable=false): их сериализация обратима байт-в-байт. */
export function mdToEditorHtml(src: string): string {
  const lines = (src || "").split("\n");
  const out: string[] = [];
  let i = 0;
  const flushList = (items: string[], ordered: boolean) => {
    if (!items.length) return;
    const tag = ordered ? "ol" : "ul";
    out.push(`<${tag}>${items.map((t) => `<li>${t}</li>`).join("")}</${tag}>`);
  };
  while (i < lines.length) {
    const line = lines[i];
    if (line.trim().startsWith("```")) {           // fenced → остров
      const lang = line.trim().slice(3).trim();
      const buf: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) buf.push(lines[i++]);
      i++; // закрывающий фенс
      out.push(`<pre class="ced-island" contenteditable="false"><code data-lang="${esc(lang)}">${esc(buf.join("\n"))}</code></pre>`);
      continue;
    }
    if (/^\s*\|/.test(line.trim())) {              // таблица → остров
      const rows: string[] = [];
      while (i < lines.length && /^\s*\|/.test(lines[i].trim())) rows.push(lines[i++].trim());
      const cells = (r: string) => r.replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      if (rows.length >= 2) {
        const body = rows.filter((r) => !/^\|?\s*:?-{2,}/.test(r));
        out.push(`<table class="ced-island" contenteditable="false"><thead><tr>${
          cells(body[0]).map((c) => `<th>${inlineHtml(c)}</th>`).join("")}</tr></thead><tbody>${
          body.slice(1).map((r) => `<tr>${cells(r).map((c) => `<td>${inlineHtml(c)}</td>`).join("")}</tr>`).join("")
        }</tbody></table>`);
      }
      continue;
    }
    const head = line.match(/^(#{1,4})\s+(.*)$/);
    if (head && !/чек-лист/i.test(head[2])) {      // заголовок вне чек-лист-секции
      out.push(`<h${head[1].length}>${inlineHtml(head[2])}</h${head[1].length}>`);
      i++; continue;
    }
    if (head && /чек-лист/i.test(head[2])) {       // чек-лист-секция → остров целиком
      const title = head[2];
      const items: Array<{ st: string; text: string }> = [];
      i++;
      while (i < lines.length) {
        const b = lines[i].match(/^\s*-\s+\[( |~|x|r|b|f)\]\s*(.*)$/);
        if (!b) break;
        items.push({ st: b[1], text: b[2] });
        i++;
      }
      out.push(`<div class="ced-island" data-kind="checklist" contenteditable="false">`
        + `<h2>${inlineHtml(title)}</h2>`
        + `<ul>${items.map((it) =>
            `<li data-state="${it.st}"><span class="ced-glyph">${GLYPH[it.st] || "○"}</span> `
            + inlineHtml(it.text) + `</li>`).join("")}</ul></div>`);
      continue;
    }
    if (/^\s*-\s+\[( |~|x|r|b|f)\]/.test(line)) {  // чекбоксы вне секции → остров
      const items: Array<{ st: string; text: string }> = [];
      while (i < lines.length) {
        const b = lines[i].match(/^\s*-\s+\[( |~|x|r|b|f)\]\s*(.*)$/);
        if (!b) break;
        items.push({ st: b[1], text: b[2] });
        i++;
      }
      out.push(`<div class="ced-island" data-kind="checklist" contenteditable="false"><ul>${
        items.map((it) => `<li data-state="${it.st}"><span class="ced-glyph">${GLYPH[it.st] || "○"}</span> `
          + inlineHtml(it.text) + `</li>`).join("")}</ul></div>`);
      continue;
    }
    if (/^---+$/.test(line.trim())) { out.push("<hr>"); i++; continue; }
    if (/^\s*[-*]\s+/.test(line) || /^\s*\d+\.\s+/.test(line)) {   // обычный список
      const ordered = /^\s*\d+\./.test(line);
      const items: string[] = [];
      while (i < lines.length) {
        const m = lines[i].match(/^(\s*)([-*]|\d+\.)\s+(.*)$/);
        if (!m || (/^\s*\d+\./.test(lines[i]) !== ordered && !m[1])) break;
        if (!m[1] && /^\s*-\s+\[/.test(lines[i])) break;
        items.push(inlineHtml(m[3]));
        i++;
      }
      flushList(items, ordered);
      continue;
    }
    if (/^\s*>\s?/.test(line)) {                   // цитата
      const buf: string[] = [];
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
        buf.push(inlineHtml(lines[i].replace(/^\s*>\s?/, "")));
        i++;
      }
      out.push(`<blockquote>${buf.join("<br>")}</blockquote>`);
      continue;
    }
    if (line.trim() === "") { i++; continue; }
    const buf: string[] = [];                      // абзац до пустой строки
    while (i < lines.length && lines[i].trim() !== ""
        && !/^(#{1,4}\s|\s*[-*]\s|\s*\d+\.\s|\s*>|\s*\||```|---)/.test(lines[i])) {
      buf.push(inlineHtml(lines[i]));
      i++;
    }
    if (buf.length) out.push(`<p>${buf.join("<br>")}</p>`);
    else i++; // защита от зависания на нестандартной строке
  }
  return out.join("\n");
}

/** DOM редактора → markdown. Инвариант: текст не теряется никогда — неизвестные
 *  узлы разворачиваются рекурсией в детей. */
export function domToMarkdown(root: HTMLElement): string {
  const inlineOf = (node: Node): string => {
    let s = "";
    node.childNodes.forEach((n) => {
      if (n.nodeType === Node.TEXT_NODE) {
        s += (n.textContent || "").replace(/ /g, " ");
        return;
      }
      if (n.nodeType !== Node.ELEMENT_NODE) return;
      const e = n as HTMLElement;
      const tag = e.tagName;
      const inner = inlineOf(e);
      if (tag === "B" || tag === "STRONG") s += `**${inner}**`;
      else if (tag === "I" || tag === "EM") s += `*${inner}*`;
      else if (tag === "CODE") {
        s += inner.includes("`") ? "``" + inner + "``" : "`" + inner + "`";
      }
      else if (tag === "A") s += `[${inner}](${e.getAttribute("href") || ""})`;
      else if (tag === "BR") s += "\n";
      else s += inner; // SPAN/U/FONT и прочее — рекурсия
    });
    return s;
  };
  const stateOf = (li: HTMLElement) =>
    (li.dataset.state ?? " ") === " " ? " " : (li.dataset.state as string);
  const blocks: string[] = [];
  const walk = (el: HTMLElement, depth: number): void => {
    el.childNodes.forEach((n) => {
      if (n.nodeType === Node.TEXT_NODE) {
        const t = (n.textContent || "").trim();
        if (t) blocks.push(t.replace(/ /g, " "));
        return;
      }
      if (n.nodeType !== Node.ELEMENT_NODE) return;
      const e = n as HTMLElement;
      const tag = e.tagName;
      if (/^H[1-6]$/.test(tag)) {
        blocks.push(`${"#".repeat(Number(tag[1]))} ${inlineOf(e).trim()}`);
      } else if (tag === "P") {
        const t = inlineOf(e).trim();
        if (t) blocks.push(t);
      } else if (tag === "UL" || tag === "OL") {
        const lines: string[] = [];
        const emit = (list: HTMLElement, lvl: number) => {
          const orderedHere = list.tagName === "OL";
          let num = 1;
          list.childNodes.forEach((li) => {
            if ((li as HTMLElement).tagName !== "LI") return;
            const L = li as HTMLElement;
            const pad = "  ".repeat(lvl);
            const clone = L.cloneNode(true) as HTMLElement;
            clone.querySelectorAll("ul,ol").forEach((x) => x.remove());
            const text = inlineOf(clone).trim();
            if (L.dataset.state !== undefined) {         // пункт чек-листа
              lines.push(`${pad}- [${stateOf(L)}] ${text}`);
            } else {
              lines.push(orderedHere ? `${pad}${num++}. ${text}` : `${pad}- ${text}`);
            }
            L.childNodes.forEach((c) => {
              const ce = c as HTMLElement;
              if (c.nodeType === Node.ELEMENT_NODE
                  && (ce.tagName === "UL" || ce.tagName === "OL")) {
                emit(ce, lvl + 1);
              }
            });
          });
        };
        emit(e, Math.min(depth, 1)); // глубже 2 — развёртка в плоский список
      } else if (tag === "BLOCKQUOTE") {
        blocks.push(inlineOf(e).trim().split("\n").map((l) => `> ${l}`).join("\n"));
      } else if (tag === "PRE") {
        const code = e.querySelector("code");
        const lang = code?.getAttribute("data-lang") || "";
        blocks.push("```" + lang + "\n" + (code?.textContent || e.textContent || "") + "\n```");
      } else if (tag === "TABLE") {
        const rows = Array.from(e.querySelectorAll("tr"));
        const cellsOf = (tr: HTMLElement) =>
          Array.from(tr.querySelectorAll("th,td"))
            .map((c) => (c.textContent || "").trim().replace(/\|/g, "\\|").replace(/\n/g, " "));
        if (rows.length) {
          const head = cellsOf(rows[0] as HTMLElement);
          blocks.push(`| ${head.join(" | ")} |\n|${head.map(() => "---").join("|")}|`
            + rows.slice(1).map((r) => `\n| ${cellsOf(r as HTMLElement).join(" | ")} |`).join(""));
        }
      } else if (tag === "HR") {
        blocks.push("---");
      } else if (tag === "DIV" && e.dataset.kind === "checklist") {
        walk(e, depth); // остров чек-листа: h2 + ul обработаются выше по детям
      } else if (tag === "DIV" || tag === "SPAN") {
        walk(e, depth); // paste-контейнеры и прочее — рекурсия в детей
      } else {
        const t = inlineOf(e).trim();
        if (t) blocks.push(t);
      }
    });
  };
  walk(root, 0);
  return blocks.join("\n\n") + "\n";
}

/* ═══════════════════════ сам редактор ═══════════════════════ */

/** Редактор описания задачи (карточка = единый источник).
 *  «Визуальный» — contentEditable WYSIWYG с островами; «Текст» — markdown.
 *  dirty — флаг по событию ввода (не diff строк: round-trip даёт шум). */
export function CardEditor({ cardMd, liveRunning, onSave, onCancel }: {
  cardMd: string;
  liveRunning: boolean;
  onSave: (cardMd: string, opts: { force: boolean }) => void;
  onCancel: () => void;
}) {
  const [mode, setModeState] = useState<"visual" | "text">("visual");
  const [text, setText] = useState(cardMd);
  const [dirty, setDirty] = useState(false);
  const areaRef = useRef<HTMLTextAreaElement>(null);
  const editRef = useRef<HTMLDivElement>(null);
  const mdRef = useRef(cardMd);   // актуальный md для эффектов переключения режимов
  mdRef.current = text;

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

  // вход в визуальный режим: перерендер текущего md (после монтирования div'а)
  useEffect(() => {
    if (mode === "visual" && editRef.current) {
      editRef.current.innerHTML = mdToEditorHtml(mdRef.current);
    }
  }, [mode]);

  const touch = () => setDirty(true);

  /** Переключение режима: визуал→текст сериализует DOM, текст→визуал — рендер. */
  const switchMode = (m: "visual" | "text") => {
    if (m === mode) return;
    if (m === "text" && editRef.current) {
      setText(domToMarkdown(editRef.current));
    }
    setModeState(m);
  };

  const cmd = (name: string, val?: string) => {
    editRef.current?.focus();
    try {
      document.execCommand("styleWithCSS", false, "false");
      document.execCommand(name, false, val);
    } catch { /* экзотический браузер — просто не применяем */ }
    touch();
  };

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
    if (mode === "visual") cmd("createLink", url);
    else wrap("[", `](${url})`, "текст ссылки");
  };

  const addInlineCode = () => {
    if (mode !== "visual") return wrap("`", "`", "код");
    const sel = window.getSelection()?.toString() || "код";
    cmd("insertHTML", `<code>${esc(sel.replace(/`/g, ""))}</code>`);
  };

  const addCodeBlock = () => {
    if (mode !== "visual") {
      wrap("```\n", "\n```", "код");
      return;
    }
    const sel = window.getSelection()?.toString() || "код";
    cmd("insertHTML",
      `<pre class="ced-island" contenteditable="false"><code data-lang="">${esc(sel)}</code></pre><p><br></p>`);
  };

  const cancel = () => {
    if (!dirty || window.confirm("Отменить несохранённые правки описания?")) onCancel();
  };

  const save = () => {
    const md = mode === "visual" && editRef.current
      ? domToMarkdown(editRef.current) : text;
    if (md === cardMd) { onCancel(); return; }  // без изменений — просто выходим
    if (liveRunning && !window.confirm(
      "Сессия агента сейчас работает — правка карточки может затереться "
      + "её изменениями. Сохранить принудительно?")) return;
    if (!liveRunning
        && JSON.stringify(extractChecklistSections(cardMd))
            !== JSON.stringify(extractChecklistSections(md))
        && !window.confirm(
          "Вы изменили чек-лист-секции карточки. Их ведут исполнитель и ревьюер "
          + "(«План работ», «Доработка по ревью») — потеря ломает петлю доработки. "
          + "Сохранить?")) return;
    onSave(md, { force: liveRunning });
  };

  // клик по глифу чек-лист-острова: toggle ○/✓ — единственная правка чек-листа в визуале
  const onVisualClick = (e: React.MouseEvent) => {
    const t = e.target as HTMLElement;
    if (t.classList?.contains("ced-glyph")) {
      e.preventDefault();
      const li = t.closest("li[data-state]") as HTMLElement | null;
      if (li) {
        const next = li.dataset.state === "x" ? " " : "x";
        li.dataset.state = next;
        t.textContent = GLYPH[next] || "○";
        touch();
      }
    }
  };

  const pastePlain = (e: React.ClipboardEvent) => {
    e.preventDefault();
    const txt = e.clipboardData.getData("text/plain");
    document.execCommand("insertText", false, txt);
    touch();
  };

  return (
    <div className="ced">
      <div className="ced-bar">
        {mode === "visual" ? (
          <>
            <select className="ced-style" title="Стиль"
              defaultValue="" onChange={(e) => { if (e.target.value) cmd("formatBlock", e.target.value); }}>
              <option value="" disabled>Стиль</option>
              <option value="P">Абзац</option>
              <option value="H2">Заголовок 2</option>
              <option value="H3">Заголовок 3</option>
              <option value="H4">Заголовок 4</option>
              <option value="BLOCKQUOTE">Цитата</option>
            </select>
            <button className="ced-btn" title="Жирный" onMouseDown={(e) => e.preventDefault()}
              onClick={() => cmd("bold")}><b>B</b></button>
            <button className="ced-btn" title="Курсив" onMouseDown={(e) => e.preventDefault()}
              onClick={() => cmd("italic")}><i>I</i></button>
            <button className="ced-btn" title="Ссылка" onMouseDown={(e) => e.preventDefault()}
              onClick={addLink}>🔗</button>
            <button className="ced-btn" title="Список" onMouseDown={(e) => e.preventDefault()}
              onClick={() => cmd("insertUnorderedList")}>≡</button>
            <button className="ced-btn" title="Нумерованный список" onMouseDown={(e) => e.preventDefault()}
              onClick={() => cmd("insertOrderedList")}>1.</button>
            <button className="ced-btn" title="Код в строке" onMouseDown={(e) => e.preventDefault()}
              onClick={addInlineCode}>&lt;&gt;</button>
            <button className="ced-btn" title="Блок кода" onMouseDown={(e) => e.preventDefault()}
              onClick={addCodeBlock}>▤</button>
          </>
        ) : (
          <>
            <button className="ced-btn" title="Заголовок раздела" onClick={() => prefixLines("## ")}>H2</button>
            <button className="ced-btn" title="Подзаголовок" onClick={() => prefixLines("### ")}>H3</button>
            <button className="ced-btn" title="Жирный" onClick={() => wrap("**", "**", "жирный")}><b>B</b></button>
            <button className="ced-btn" title="Курсив" onClick={() => wrap("*", "*", "курсив")}><i>I</i></button>
            <button className="ced-btn" title="Ссылка" onClick={addLink}>🔗</button>
            <button className="ced-btn" title="Список" onClick={() => prefixLines("- ")}>≡</button>
            <button className="ced-btn" title="Нумерованный список" onClick={() => prefixLines("1. ")}>1.</button>
            <button className="ced-btn" title="Чекбокс" onClick={() => wrap("- [ ] ", "", "пункт")}>☑</button>
            <button className="ced-btn" title="Код в строке" onClick={addInlineCode}>&lt;&gt;</button>
            <button className="ced-btn" title="Блок кода" onClick={addCodeBlock}>▤</button>
            <button className="ced-btn" title="Цитата" onClick={() => prefixLines("> ")}>❝</button>
          </>
        )}
        <span className="spacer" />
        {liveRunning && <span className="ced-live">⚠ сессия агента работает</span>}
      </div>

      {mode === "visual" ? (
        <div ref={editRef} className="ced-visual post" contentEditable
          suppressContentEditableWarning
          onInput={touch} onClick={onVisualClick} onPaste={pastePlain} />
      ) : (
        <textarea ref={areaRef} className="ced-text" value={text} spellCheck={false}
          onChange={(e) => { setText(e.target.value); touch(); }} />
      )}

      <div className="ced-foot">
        <div className="ced-modes">
          <button className={`ced-tab ${mode === "visual" ? "on" : ""}`}
            onClick={() => switchMode("visual")}>Визуальный</button>
          <button className={`ced-tab ${mode === "text" ? "on" : ""}`}
            onClick={() => switchMode("text")}>Текст</button>
        </div>
        <span className="spacer" />
        <button className="ghost" onClick={cancel}>Отмена</button>
        <button className="primary" onClick={save}>Сохранить</button>
      </div>
    </div>
  );
}
