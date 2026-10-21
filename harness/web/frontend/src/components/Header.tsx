import { useEffect, useRef, useState } from "react";
import type { BoardState, Project, Story } from "../types";
import { fmtTokens, fmtUsd } from "./common/ui";

function timeAgo(iso?: string): string {
  if (!iso) return "";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  const s = Math.max(1, Math.round((Date.now() - t) / 1000));
  if (s < 60) return `${s}с назад`;
  return `${Math.round(s / 60)}м назад`;
}

/** Переключатель тёмной/светлой темы (макет v3): 🌙/☀, выбор — в localStorage. */
function ThemeToggle() {
  const [theme, setTheme] = useState(
    document.documentElement.dataset.theme === "light" ? "light" : "dark",
  );
  const toggle = () => {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("theme", next);
    setTheme(next);
  };
  return (
    <button onClick={toggle} title="Переключить тему">
      {theme === "dark" ? "🌙" : "☀"}
    </button>
  );
}

/** Шапка-пульт: лого, селектор Story (обзор внутри), вид, метрики, действия. */
export function Header({ fnr, stories, projects, activeProject, state, conn = "…",
  onOpenStory, onOpenProject, onAllStories, onAddProject, onOpenTask,
  onCreate, onMetrics, view, setView, onFlag, onOpenSettings,
  onEditProject, onDeleteProject, onOpenReview }: {
  fnr: string | null;
  stories: Story[];
  projects: Project[];
  activeProject: string | null;
  state: BoardState | null;
  conn?: string;
  onOpenStory: (fnr: string) => void;
  onOpenProject: (name: string) => void;
  onAllStories: () => void;
  onAddProject: () => void;
  onOpenTask: (id: string) => void;
  onCreate: () => void;
  onMetrics: () => void;
  view: "board" | "list";
  setView: (v: "board" | "list") => void;
  onFlag: (name: string, method?: "POST" | "DELETE") => void;
  onOpenSettings: () => void;
  onEditProject: (name: string) => void;
  onDeleteProject: (name: string) => void;
  onOpenReview: () => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [storiesOpen, setStoriesOpen] = useState(false);
  const [bellOpen, setBellOpen] = useState(false);
  const [gearOpen, setGearOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const storiesRef = useRef<HTMLDivElement>(null);
  const gearRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
      if (storiesRef.current && !storiesRef.current.contains(e.target as Node)) {
        setStoriesOpen(false);
      }
      if (gearRef.current && !gearRef.current.contains(e.target as Node)) {
        setGearOpen(false);
      }
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const flags = state?.flags || [];
  const attention = (state?.manifest.tasks || [])
    .filter((t) => ["NEEDS_HUMAN", "BLOCKED"].includes(t.pipeline || "")).length;

  return (
    <header>
      <span className="logo">{">"}</span>

      <div className="story-select" ref={menuRef}>
        <button onClick={() => setMenuOpen((v) => !v)} title="Сменить проект">
          📋 {activeProject || "Все проекты"} ▾
        </button>
        {menuOpen && (
          <div className="story-menu">
            <div className="s-head meta">Проекты (multi-repo)</div>
            {projects.map((prj) => (
              <div className="s-item" key={prj.name}
                onClick={() => { onOpenProject(prj.name); setMenuOpen(false); }}>
                <span className="fnr">{prj.alias || prj.name}</span>
                {prj.auto_registered && <span className="meta"> · авто</span>}
                {prj.deleted && <span className="meta" style={{ color: "var(--warn)" }}> · удаляется…</span>}
                <span style={{ flex: 1, minWidth: 0 }}>
                  <span className="meta">{prj.task_count} задач · 🪙 {fmtTokens(prj.usage.tokens_total)} · {fmtUsd(prj.usage.cost_usd)}</span>
                </span>
                <span className="bar"><i style={{
                  width: `${prj.task_count ? Math.round(100 * (prj.stories.reduce((a, s) => a + (s.counts.DONE || 0) + (s.counts.VERIFIED || 0), 0) / prj.task_count)) : 0}%` }} /></span>
                <button title="Изменить проект"
                  onClick={(e) => { e.stopPropagation(); onEditProject(prj.name); }}>✎</button>
                <button title="Удалить проект" style={{ color: "var(--bad)" }}
                  onClick={(e) => { e.stopPropagation(); onDeleteProject(prj.name); }}>🗑</button>
              </div>
            ))}
            {activeProject && stories.length > 0 && (
              <>
                <div className="s-head meta" style={{ borderTop: "1px solid var(--line)" }}>
                  Stories · {activeProject}
                </div>
                {stories.map((s) => (
                  <div className="s-item" key={s.fnr}
                    onClick={() => { onOpenStory(s.fnr); setMenuOpen(false); }}>
                    <span className="fnr">{s.fnr}</span>
                    <span style={{ flex: 1, minWidth: 0, overflow: "hidden",
                      textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.title}</span>
                  </div>
                ))}
              </>
            )}
            <div className="s-item" onClick={() => { onAllStories(); setMenuOpen(false); }}>
              <span className="meta">📊 Обзор всех проектов и Story</span>
            </div>
            <div className="s-item" onClick={() => { onAddProject(); setMenuOpen(false); }}>
              <span className="meta">＋ Добавить проект (путь на компьютере)…</span>
            </div>
            <div className="s-item" onClick={() => { onCreate(); setMenuOpen(false); }}>
              <span className="meta">＋ Новая Story…</span>
            </div>
          </div>
        )}
      </div>

      {fnr && (
        <div className="story-select" ref={storiesRef}>
          <button className="crumb-nav" title="Сменить Story" onClick={() => setStoriesOpen((v) => !v)}>
            / {fnr}
          </button>
          {storiesOpen && (
            <div className="story-menu" style={{ width: 340 }}>
              <div className="s-head meta">Stories · {activeProject || "—"}</div>
              {stories.map((s) => (
                <div className="s-item" key={s.fnr}
                  onClick={() => { onOpenStory(s.fnr); setStoriesOpen(false); }}>
                  <span className="fnr">{s.fnr}</span>
                  <span style={{ flex: 1, minWidth: 0, overflow: "hidden",
                    textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.title}</span>
                </div>
              ))}
              <div className="s-item" onClick={() => { onAllStories(); setStoriesOpen(false); }}>
                <span className="meta">📊 Обзор всех проектов и Story</span>
              </div>
            </div>
          )}
        </div>
      )}
      {fnr && (
        <span className="meta mono" title="свежесть живой стадии">
          {timeAgo(state?.manifest.tasks?.find((t) => t.live)?.pipeline_since)}
        </span>
      )}

      <span className="spacer" />
      <span className="kbd">⌘K</span>

      <div className="seg">
        <button className={view === "board" ? "on" : ""} onClick={() => setView("board")}>KANBAN</button>
        <button className={view === "list" ? "on" : ""} onClick={() => setView("list")}>LIST</button>
      </div>

      <ThemeToggle />
      <div className="story-select" ref={gearRef}>
        <button title="Настройки" onClick={() => setGearOpen((v) => !v)}>⚙</button>
        {gearOpen && (
          <div className="story-menu" style={{ left: "auto", right: 0, minWidth: 200 }}>
            <div className="s-head meta">Настройки</div>
            <div className="s-item" onClick={() => { onOpenSettings(); setGearOpen(false); }}>
              <span className="meta">⚡ Подключение ИИ</span>
            </div>
          </div>
        )}
      </div>
      <button onClick={onMetrics} title="Метрики расхода">📊 METRICS</button>
      <div className="story-select">
        <button title="Задачи, требующие вашего участия"
          style={attention ? { color: "var(--warn)", borderColor: "var(--warn)" } : undefined}
          onClick={() => setBellOpen((v) => !v)}>
          🔔 {attention || ""}
        </button>
        {bellOpen && (
          <div className="story-menu" style={{ left: "auto", right: 0, width: 340 }}>
            <div className="s-head meta">Требуют вашего участия</div>
            {(state?.manifest.tasks || []).filter((t) =>
              ["NEEDS_HUMAN", "BLOCKED"].includes(t.pipeline || "")).map((t) => (
              <div className="s-item" key={t.id}
                onClick={() => { onOpenTask(t.id); setBellOpen(false); }}>
                <span className="fnr">{t.id}</span>
                <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis",
                  whiteSpace: "nowrap" }}>{t.title}</span>
                <span className="meta">{t.pipeline === "BLOCKED" ? "блок" : "решение"}</span>
              </div>
            ))}
            {attention === 0 && <div className="s-item empty">ничего не требует участия</div>}
          </div>
        )}
      </div>

      <span id="flags">
        {flags.filter((f) => !f.startsWith("TASK_")).map((f) => (
          <span className="flag-chip" key={f}>{f === "APPROVE_PLAN" ? "ждёт утверждения плана" : f}</span>
        ))}
      </span>
      {fnr && state?.manifest.status === "AWAITING_APPROVAL" && (
        <button title="Ревью состава плана до апрува (СТ FNR-11 5.1.2)"
          onClick={onOpenReview}>🔎 Ревью плана</button>
      )}
      {fnr && (
        <>
          <button className="ghost" disabled={flags.includes("APPROVE_PLAN")}
            onClick={() => onFlag("APPROVE_PLAN")}>✓ План</button>
          <button className="ghost" onClick={() => onFlag("PAUSE",
            flags.includes("PAUSE") ? "DELETE" : "POST")}>
            {flags.includes("PAUSE") ? "▶" : "⏸"}
          </button>
        </>
      )}
      <button className="primary" onClick={onCreate}>+ Создать</button>
      <span className={`conn ${conn === "live" ? "on" : ""}`}>{conn}</span>
    </header>
  );
}

export { timeAgo };
