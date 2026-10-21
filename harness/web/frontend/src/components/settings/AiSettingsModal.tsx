import { useCallback, useEffect, useState } from "react";
import type { AiProtocol, AiSaveResult, AiSettingsSnapshot, AiTestResult } from "../../types";
import { api } from "../../api";
import { toast } from "../common/toasts";

const PROTOCOL_CARDS: Array<{ id: AiProtocol; title: string; sub: string }> = [
  { id: "anthropic", title: "Anthropic-совместимый", sub: "z.ai (GLM), DeepSeek, Kimi" },
  { id: "openai", title: "OpenAI-совместимый", sub: "OpenAI, OpenRouter, локальные Ollama / vLLM" },
];

const TOKEN_SOURCE_RU: Record<string, string> = {
  saved: "сохранённый токен", env: "токен из окружения", none: "токен не задан",
};

const INPUT_STYLE = {
  width: "100%", boxSizing: "border-box" as const, background: "var(--chip)",
  border: "1px solid var(--line2)", borderRadius: 6, padding: "7px 9px",
  color: "var(--text)", fontSize: 12,
};

/** Поп-ап «Подключение ИИ» (СТ FNR-10, задача 5.1.2; макет reference_ui.png). */
export function AiSettingsModal({ onClose }: { onClose: () => void }) {
  const [snap, setSnap] = useState<AiSettingsSnapshot | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [protocol, setProtocol] = useState<AiProtocol>("anthropic");
  const [provider, setProvider] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [newToken, setNewToken] = useState("");
  const [clearToken, setClearToken] = useState(false);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testResult, setTestResult] = useState<AiTestResult | null>(null);
  const [saveWarn, setSaveWarn] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);

  const mark = useCallback(() => { setDirty(true); setTestResult(null); }, []);

  const load = useCallback(() => {
    setLoadErr(null);
    api.aiSettings().then((s) => {
      setSnap(s);
      setProtocol((s.saved.protocol as AiProtocol) || "anthropic");
      setProvider(s.saved.provider || "");
      setBaseUrl(s.saved.baseUrl || "");
      setModel(s.saved.model || "");
      setNewToken("");
      setClearToken(false);
      setDirty(false);
      setTestResult(null);
      setSaveWarn(null);
    }).catch((e) => setLoadErr(e.message));
  }, []);

  useEffect(() => { load(); }, [load]);

  const presets = (snap?.presets || []).filter((p) => p.protocol === protocol);

  const close = () => {
    if (dirty && !window.confirm("Закрыть без сохранения изменений?")) return;
    onClose();
  };

  const pickPreset = (name: string) => {
    const p = presets.find((x) => x.provider === name);
    setProvider(name);
    setBaseUrl(p?.baseUrl || "");
    setModel(p?.defaultModel || "");
    mark();
  };

  const runTest = () => {
    setTesting(true);
    setTestResult(null);
    api.aiTest({
      protocol, provider: provider || undefined,
      baseUrl: baseUrl || undefined, model: model || undefined,
      token: newToken || undefined,
    }).then(setTestResult)
      .catch((e) => setTestResult({ ok: false, human: "Проверка не выполнена", tech: e.message }))
      .finally(() => setTesting(false));
  };

  const save = () => {
    setSaving(true);
    api.aiSave({
      protocol, provider: provider || undefined,
      baseUrl: baseUrl || undefined, model: model || undefined,
      token: newToken || undefined, clearToken,
    }).then((r: AiSaveResult) => {
      if (r.warning === "protocol_not_served_yet") {
        setSaveWarn("OpenAI-совместимый протокол пока не обслуживается: конфигурация сохранена,"
          + " но сессии продолжат ходить через окружение, пока не включён шлюз протоколов.");
        toast.info("Конфигурация сохранена с предупреждением");
      } else {
        setSaveWarn(null);
        toast.ok("Подключение ИИ сохранено");
      }
      setNewToken("");
      setClearToken(false);
      setDirty(false);
      return api.aiSettings().then(setSnap);
    }).catch((e) => toast.err(`Не сохранено: ${e.message}`))
      .finally(() => setSaving(false));
  };

  const eff = snap?.effective;

  return (
    <div className="modal-bg" onClick={(e) => { if (e.target === e.currentTarget) close(); }}>
      <div className="modal" style={{ width: "min(680px, 94vw)", maxHeight: "92vh", overflow: "auto" }}>
        <h3>⚡ Подключение ИИ</h3>
        <div className="meta" style={{ marginBottom: 10 }}>
          Персональные настройки: ваши проверки идут через ваш провайдер и токен
        </div>

        {loadErr && (
          <div style={{ margin: "8px 0", padding: 10, border: "1px solid var(--bad)",
            borderRadius: 8, color: "var(--bad)" }}>
            Не удалось прочитать настройки: {loadErr}{" "}
            <button onClick={load}>Повторить</button>
          </div>
        )}

        {eff && (
          <div className="meta mono" style={{ background: "var(--surface2)",
            border: "1px solid var(--line)", borderRadius: 8, padding: "7px 10px",
            marginBottom: 14 }}>
            Сейчас проверки через:{" "}
            <span style={{ color: "var(--ok)" }}>●</span>{" "}
            {eff.model || "—"} · {eff.baseUrl || "—"} ·{" "}
            {TOKEN_SOURCE_RU[eff.tokenSource] || "токен не задан"}
          </div>
        )}

        {/* 01 Протокол API */}
        <div className="meta" style={{ margin: "6px 0 6px" }}>
          <b>01&nbsp;&nbsp;Протокол API</b>
        </div>
        <div className="meta" style={{ marginBottom: 8 }}>
          Определяет формат запросов к провайдеру. Если не уверены — оставьте как есть.
        </div>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          {PROTOCOL_CARDS.map((p) => {
            const on = protocol === p.id;
            return (
              <div key={p.id} onClick={() => { setProtocol(p.id); mark(); }}
                style={{ flex: "1 1 240px", cursor: "pointer", padding: "10px 12px",
                  borderRadius: 8, border: `1px solid ${on ? "var(--acc)" : "var(--line2)"}`,
                  background: on ? "var(--acc-dim)" : "var(--surface2)" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ width: 10, height: 10, borderRadius: "50%",
                    border: `1px solid ${on ? "var(--acc)" : "var(--line2)"}`,
                    background: on ? "var(--acc)" : "transparent" }} />
                  <b style={{ fontSize: 12 }}>{p.title}</b>
                </div>
                <div className="meta" style={{ marginTop: 4 }}>{p.sub}</div>
              </div>
            );
          })}
        </div>

        {/* 02 Провайдер и модель */}
        <div className="meta" style={{ margin: "16px 0 6px" }}>
          <b>02&nbsp;&nbsp;Провайдер и модель</b>
        </div>
        <div className="meta" style={{ marginBottom: 8 }}>
          Выбираете пресет — поля заполнятся сами, значения можно поправить руками.
          Оставьте поля пустыми, чтобы взять значения из окружения (AI_BASE_URL / AI_MODEL).
        </div>
        <label>Пресет провайдера</label>
        <select value={provider} onChange={(e) => pickPreset(e.target.value)}
          style={{ ...INPUT_STYLE, color: "var(--text)" }}>
          <option value="">— выбрать —</option>
          {presets.map((p) => <option key={p.provider} value={p.provider}>{p.provider}</option>)}
        </select>
        <div style={{ display: "flex", gap: 10, marginTop: 8 }}>
          <div style={{ flex: 1.4 }}>
            <label>Базовый URL</label>
            <input type="text" value={baseUrl} style={INPUT_STYLE}
              placeholder="пусто — из окружения: AI_BASE_URL"
              onChange={(e) => { setBaseUrl(e.target.value); mark(); }} />
          </div>
          <div style={{ flex: 1 }}>
            <label>Модель</label>
            <input type="text" value={model} style={INPUT_STYLE}
              placeholder="пусто — из окружения: AI_MODEL"
              onChange={(e) => { setModel(e.target.value); mark(); }} />
          </div>
        </div>

        {/* 03 API-токен */}
        <div className="meta" style={{ margin: "16px 0 6px" }}>
          <b>03&nbsp;&nbsp;API-токен</b>
        </div>
        <div className="meta" style={{ marginBottom: 8 }}>
          Хранится в базе и отображается только маской. Оставьте поле пустым — ничего не
          изменится; чтобы вернуться к ключу окружения, удалите сохранённый токен.
        </div>
        {snap?.hasToken && (
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
            <span className="meta mono" style={{ background: "var(--surface2)",
              border: "1px solid var(--line)", borderRadius: 6, padding: "4px 8px" }}>
              Сохранён: {snap.tokenMask}
            </span>
            {clearToken
              ? <button onClick={() => setClearToken(false)}>↩ Не удалять</button>
              : <button className="ghost" onClick={() => { setClearToken(true); mark(); }}>
                  ✖ Удалить сохранённый токен</button>}
            {clearToken && <span className="meta" style={{ color: "var(--warn)" }}>
              удалится при сохранении — вернётся токен из окружения</span>}
          </div>
        )}
        <label>Новый токен</label>
        <input type="password" value={newToken} style={INPUT_STYLE}
          placeholder="введите, чтобы заменить"
          onChange={(e) => { setNewToken(e.target.value); mark(); }} />

        {saveWarn && (
          <div style={{ margin: "12px 0 0", padding: "8px 10px", borderRadius: 8,
            border: "1px solid var(--warn)", color: "var(--warn)", fontSize: 11 }}>
            {saveWarn}
          </div>
        )}

        {/* итог проверки */}
        {testResult && !testing && (testResult.ok ? (
          <div style={{ margin: "12px 0 0", padding: "8px 10px", borderRadius: 8,
            border: "1px solid var(--ok)", color: "var(--ok)", fontSize: 12 }}>
            ✓ Подключение работает — модель {testResult.model} · {testResult.latencyMs} мс
          </div>
        ) : (
          <div style={{ margin: "12px 0 0", padding: "8px 10px", borderRadius: 8,
            border: "1px solid var(--bad)", fontSize: 12 }}>
            <div style={{ color: "var(--bad)" }}>✖ {testResult.human || "Проверка не прошла"}</div>
            {testResult.tech && (
              <details style={{ marginTop: 6 }}>
                <summary className="meta" style={{ cursor: "pointer" }}>техническая причина</summary>
                <pre className="mono" style={{ whiteSpace: "pre-wrap", fontSize: 10,
                  marginTop: 4 }}>{testResult.tech}</pre>
              </details>
            )}
          </div>
        ))}

        <div className="mrow" style={{ display: "flex", justifyContent: "space-between",
          marginTop: 18 }}>
          <button disabled={testing || saving} onClick={runTest}>
            {testing ? "Проверяем…" : "⟳ Проверить подключение"}
          </button>
          <button className="primary" disabled={saving || testing} onClick={save}>
            {saving ? "Сохраняем…" : "Сохранить"}
          </button>
        </div>
      </div>
    </div>
  );
}
