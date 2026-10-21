"""Шлюз протоколов (СТ FNR-10, задача 4.4.1): Anthropic Messages → OpenAI.

Локальный HTTP-сервер на stdlib: сессия головного агента обращается к шлюзу
как к обычному антропик-совместимому провайдеру, шлюз переводит запросы в
OpenAI-совместимый протокол (OpenAI, OpenRouter, Ollama, vLLM, Gemini —
https://ai.google.dev/gemini-api/docs/openai) и передаёт настоящему
провайдеру. Жизненный цикл привязан к породившему процессу: сервер живёт в
daemon-потоке того же процесса и умирает вместе с ним (модификация 3
вердикта дебатов).

Перевод:
  - system / messages / tools / tool_choice / max_tokens / temperature / stop
  - блоки tool_use ↔ tool_calls (input_json_delta в стриме — по частям)
  - stop_reason: tool_calls→tool_use, length→max_tokens, stop→end_turn
  - поток: message_start → content_block_* → message_delta → message_stop
  - ошибки провайдера → антропик-формат error (ретраи конвейера работают)

Только stdlib; журналирование — без токенов (СТ 4.4.1, правило 6).
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG_PREFIX = "AI gateway:"


# --- чистые переводчики (покрываются юнит-тестами напрямую) -----------------

def build_openai_payload(body: dict) -> dict:
    """Тело Anthropic /v1/messages → тело OpenAI /chat/completions."""
    out: dict = {
        "model": body.get("model"),
        "max_tokens": body.get("max_tokens"),
        "messages": [],
    }
    system = body.get("system")
    if system:
        text = system if isinstance(system, str) else "".join(
            b.get("text", "") for b in system if isinstance(b, dict))
        out["messages"].append({"role": "system", "content": text})
    for msg in body.get("messages") or []:
        role = msg.get("role")
        content = msg.get("content")
        if isinstance(content, str):
            out["messages"].append({"role": role, "content": content})
            continue
        text_parts, tool_calls, tool_results = [], [], []
        for block in content or []:
            btype = block.get("type")
            if btype == "text":
                text_parts.append(block.get("text", ""))
            elif btype == "tool_use":
                tool_calls.append({"id": block.get("id"),
                                   "type": "function",
                                   "function": {"name": block.get("name"),
                                                "arguments": json.dumps(
                                                    block.get("input") or {},
                                                    ensure_ascii=False)}})
            elif btype == "tool_result":
                inner = block.get("content")
                if isinstance(inner, list):
                    inner = "".join(b.get("text", "") for b in inner
                                    if isinstance(b, dict))
                tool_results.append({"tool_call_id": block.get("tool_use_id"),
                                     "content": inner if isinstance(inner, str)
                                     else json.dumps(inner, ensure_ascii=False)})
        if role == "assistant" and tool_calls:
            m = {"role": "assistant",
                 "content": "\n".join(text_parts) or None,
                 "tool_calls": tool_calls}
            out["messages"].append(m)
        elif role == "assistant":
            out["messages"].append({"role": "assistant",
                                    "content": "\n".join(text_parts)})
        elif tool_results:
            for tr in tool_results:
                out["messages"].append({"role": "tool", **tr})
            if text_parts:
                out["messages"].append({"role": "user",
                                        "content": "\n".join(text_parts)})
        else:
            out["messages"].append({"role": role, "content": "\n".join(text_parts)})
    if body.get("tools"):
        out["tools"] = [{"type": "function",
                         "function": {"name": t.get("name"),
                                      "description": t.get("description") or "",
                                      "parameters": t.get("input_schema") or
                                      {"type": "object"}}}
                        for t in body["tools"]]
    tc = body.get("tool_choice")
    if isinstance(tc, dict):
        ttype = tc.get("type")
        if ttype == "auto":
            out["tool_choice"] = "auto"
        elif ttype == "any":
            out["tool_choice"] = "required"
        elif ttype == "tool" and tc.get("name"):
            out["tool_choice"] = {"type": "function",
                                  "function": {"name": tc["name"]}}
    if body.get("temperature") is not None:
        out["temperature"] = body["temperature"]
    if body.get("stop_sequences"):
        out["stop"] = body["stop_sequences"]
    return out


STOP_REASON = {"tool_calls": "tool_use", "length": "max_tokens",
               "stop": "end_turn", "function_call": "tool_use"}


def _tool_use_blocks(tool_calls: list | None) -> list[dict]:
    blocks = []
    for tc in tool_calls or []:
        fn = tc.get("function") or {}
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except ValueError:
            args = {}
        blocks.append({"type": "tool_use", "id": tc.get("id") or f"call_{int(time.time()*1000)}",
                       "name": fn.get("name") or "", "input": args})
    return blocks


def anthropic_response_from_openai(resp: dict, model: str, msg_id: str) -> dict:
    """Ответ OpenAI chat.completions → ответ Anthropic /v1/messages."""
    choice = (resp.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content: list[dict] = []
    if message.get("content"):
        content.append({"type": "text", "text": message["content"]})
    content.extend(_tool_use_blocks(message.get("tool_calls")))
    if not content:
        content = [{"type": "text", "text": ""}]
    usage = resp.get("usage") or {}
    return {
        "id": msg_id, "type": "message", "role": "assistant", "model": model,
        "content": content,
        "stop_reason": STOP_REASON.get(choice.get("finish_reason"), "end_turn"),
        "stop_sequence": None,
        "usage": {"input_tokens": int(usage.get("prompt_tokens") or 0),
                  "output_tokens": int(usage.get("completion_tokens") or 0)},
    }


class StreamTranslator:
    """OpenAI-чанки → события Anthropic SSE (порядок канонический).

    Употребление: translate(chunk_dict) на каждый data:-чанк апстрима,
    затем finish() — хвостовые события. usage в message_delta — кумулятив
    (выходные токены оцениваются по длине текста: include_usage не
    запрашиваем, чтобы не ловить 400 от провайдеров без поддержки).
    """

    def __init__(self, model: str, msg_id: str) -> None:
        self.model, self.msg_id = model, msg_id
        self.started = False
        self.block_idx = -1          # индекс открытого блока (-1 — нет)
        self.block_kind = None       # "text" | "tool"
        self.tool_args: dict[int, str] = {}
        self.out_chars = 0
        self.events: list[tuple[str, dict]] = []

    def _emit(self, name: str, data: dict) -> None:
        self.events.append((name, data))

    def _start_message(self) -> None:
        self._emit("message_start", {
            "type": "message_start",
            "message": {"id": self.msg_id, "type": "message", "role": "assistant",
                        "model": self.model, "content": [], "stop_reason": None,
                        "stop_sequence": None,
                        "usage": {"input_tokens": 0, "output_tokens": 1}}})
        self.started = True

    def _close_block(self) -> None:
        if self.block_idx >= 0:
            self._emit("content_block_stop",
                       {"type": "content_block_stop", "index": self.block_idx})
            self.block_idx, self.block_kind = -1, None

    def _open_block(self, content_block: dict) -> int:
        self._close_block()
        self.block_idx += 1
        self._emit("content_block_start",
                   {"type": "content_block_start", "index": self.block_idx,
                    "content_block": content_block})
        return self.block_idx

    def translate(self, chunk: dict) -> None:
        if not self.started:
            self._start_message()
        choice = (chunk.get("choices") or [{}])[0]
        delta = choice.get("delta") or {}
        if delta.get("content"):
            if self.block_kind != "text":
                self._close_block()
            if self.block_kind != "text":
                idx = self._open_block({"type": "text", "text": ""})
                self.block_kind = "text"
            else:
                idx = self.block_idx
            text = delta["content"]
            self.out_chars += len(text)
            self._emit("content_block_delta",
                       {"type": "content_block_delta", "index": idx,
                        "delta": {"type": "text_delta", "text": text}})
        for tc in delta.get("tool_calls") or []:
            idx_s = tc.get("index", 0)
            fn = tc.get("function") or {}
            if idx_s not in self.tool_args:  # новый вызов инструмента
                self._close_block()
                self.tool_args[idx_s] = ""
                idx = self._open_block({"type": "tool_use",
                                        "id": tc.get("id") or f"call_{idx_s}",
                                        "name": fn.get("name") or "",
                                        "input": {}})
                self.block_kind = "tool"
            frag = fn.get("arguments")
            if frag:
                self.tool_args[idx_s] += frag
                self.out_chars += len(frag)
                self._emit("content_block_delta",
                           {"type": "content_block_delta",
                            "index": self.block_idx,
                            "delta": {"type": "input_json_delta",
                                      "partial_json": frag}})
        return None

    def finish(self, finish_reason: str | None, upstream_usage: dict | None) -> None:
        if not self.started:  # пустой поток — всё равно закрыться корректно
            self._start_message()
            self._open_block({"type": "text", "text": ""})
            self.block_kind = "text"
        self._close_block()
        usage = upstream_usage or {}
        out_tokens = int(usage.get("completion_tokens") or 0) or max(
            1, round(self.out_chars / 4))
        self._emit("message_delta", {
            "type": "message_delta",
            "delta": {"stop_reason": STOP_REASON.get(finish_reason, "end_turn"),
                      "stop_sequence": None},
            "usage": {"output_tokens": out_tokens}})
        self._emit("message_stop", {"type": "message_stop"})


# --- HTTP-сервер шлюза -------------------------------------------------------

def _err_body(etype: str, message: str) -> dict:
    return {"type": "error", "error": {"type": etype, "message": message}}


class GatewayHandler(BaseHTTPRequestHandler):
    """Принимает Anthropic-запросы, апстриму отдаёт OpenAI (конфиг в server)."""

    server_version = "sa-helper-gateway/1"

    @property
    def cfg(self) -> dict:
        return self.server.config  # upstream_base_url, upstream_token, model

    def log_message(self, fmt, *args):  # журнал без токенов
        print(f"{LOG_PREFIX} {self.address_string()} {fmt % args}", flush=True)

    def _json(self, code: int, doc: dict) -> None:
        payload = json.dumps(doc, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):  # noqa: N802 — readiness (СТ 4.4.1, правило 4)
        if self.path in ("/health", "/healthz"):
            self._json(200, {"ok": True, "gateway": True})
        else:
            self._json(404, _err_body("not_found_error", "неизвестный путь"))

    def _upstream(self, payload: dict, stream: bool):
        url = self.cfg["upstream_base_url"].rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.cfg.get("upstream_token"):
            headers["Authorization"] = f"Bearer {self.cfg['upstream_token']}"
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                     headers=headers, method="POST")
        return urllib.request.urlopen(req, timeout=600)

    def do_POST(self):  # noqa: N802
        if self.path.endswith("/count_tokens"):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            self._json(200, {"input_tokens": max(1, len(body) // 4)})
            return
        if not self.path.endswith("/messages"):
            self._json(404, _err_body("not_found_error",
                                      "ожидается /v1/messages"))
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except ValueError:
            self._json(400, _err_body("invalid_request_error", "битый JSON"))
            return
        try:
            payload = build_openai_payload(body)
        except Exception as exc:  # некорректное тело антропик-запроса
            self._json(400, _err_body("invalid_request_error",
                                      f"{LOG_PREFIX} не удалось перевести запрос: {exc}"))
            return
        try:
            upstream = self._upstream(payload, bool(body.get("stream")))
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:600]
            except Exception:
                pass
            etype = {401: "authentication_error", 403: "permission_error",
                     404: "not_found_error", 429: "rate_limit_error",
                     529: "overloaded_error"}.get(exc.code, "api_error")
            self._json(exc.code if exc.code < 500 else 500,
                       _err_body(etype, f"{LOG_PREFIX} провайдер вернул "
                                        f"{exc.code}: {detail}"))
            return
        except (urllib.error.URLError, OSError) as exc:
            self._json(502, _err_body("api_error",
                                      f"{LOG_PREFIX} провайдер недоступен: {exc}"))
            return
        try:
            if body.get("stream"):
                self._stream_response(upstream, body)
            else:
                self._plain_response(upstream, body)
        except (BrokenPipeError, ConnectionResetError):
            pass  # клиент-сессия умер раньше — нормально для конвейера

    def _plain_response(self, upstream, body: dict) -> None:
        doc = json.loads(upstream.read().decode("utf-8", errors="replace") or "{}")
        self._json(200, anthropic_response_from_openai(
            doc, body.get("model") or self.cfg.get("model") or "",
            f"msg_gw_{int(time.time()*1000)}"))

    def _stream_response(self, upstream, body: dict) -> None:
        model = body.get("model") or self.cfg.get("model") or ""
        tr = StreamTranslator(model, f"msg_gw_{int(time.time()*1000)}")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        def emit(name: str, data: dict) -> None:
            chunk = f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            self.wfile.write(chunk.encode("utf-8"))

        emit("ping", {"type": "ping"})
        finish_reason = None
        usage = None
        for raw in upstream:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except ValueError:
                continue
            tr.translate(chunk)
            for name, doc in tr.events:
                emit(name, doc)
            tr.events.clear()
            choice = (chunk.get("choices") or [{}])[0]
            if choice.get("finish_reason"):
                finish_reason = choice["finish_reason"]
            if chunk.get("usage"):
                usage = chunk["usage"]
        tr.finish(finish_reason, usage)
        for name, doc in tr.events:
            emit(name, doc)
        self.wfile.flush()


class Gateway(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False


def start(config: dict) -> Gateway:
    """Поднять шлюз на 127.0.0.1:<эфемерный порт>; готов сразу после bind."""
    srv = Gateway(("127.0.0.1", 0), GatewayHandler)
    srv.config = dict(config)
    threading.Thread(target=srv.serve_forever, name="ai-gateway", daemon=True).start()
    host, port = srv.server_address[:2]
    print(f"{LOG_PREFIX} слушает http://{host}:{port} → "
          f"{config.get('upstream_base_url')}", flush=True)
    return srv


# --- синглтон для демона/витрины (модификация 3: живёт с владельцем) --------

_ACTIVE: dict = {}  # {"sig": str, "srv": Gateway}
_GATEWAY_LOCK = threading.Lock()   # СТ FNR-11: параллельные спавны — без гонки


def _sig(eff: dict) -> str:
    return "|".join(str(eff.get(k) or "") for k in ("base_url", "token", "model"))


def ensure_for(eff: dict) -> str | None:
    """Гарантировать шлюз для эффективных openai-настроек; вернуть base URL.

    Конфигурация (адрес/токен/модель) сменилась — шлюз перезапускается.
    Ошибка старта → None (сессия получит понятную ошибку, конвейер не падает).
    """
    with _GATEWAY_LOCK:
        return _ensure_for_locked(eff)


def _ensure_for_locked(eff: dict) -> str | None:
    if eff.get("protocol") != "openai" or not eff.get("base_url"):
        return None
    sig = _sig(eff)
    active = _ACTIVE.get("srv")
    if _ACTIVE.get("sig") == sig and active is not None:
        host, port = active.server_address[:2]
        return f"http://{host}:{port}"
    if active is not None:
        try:
            active.shutdown()
            active.server_close()
        except Exception:
            pass
        _ACTIVE.clear()
    try:
        srv = start({"upstream_base_url": eff["base_url"],
                     "upstream_token": eff.get("token") or "",
                     "model": eff.get("model") or ""})
    except Exception as exc:
        print(f"{LOG_PREFIX} не удалось запустить: {exc}", flush=True)
        return None
    _ACTIVE.update(sig=sig, srv=srv)
    host, port = srv.server_address[:2]
    return f"http://{host}:{port}"


def is_running() -> bool:
    return _ACTIVE.get("srv") is not None
