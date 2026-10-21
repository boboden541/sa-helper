"""Тесты «Подключение ИИ» (СТ FNR-10): резолвер, БД, API витрины, инъекция."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "web"))

import db as dbmod  # noqa: E402
import server as web  # noqa: E402
import ai_provider as aip  # noqa: E402

ENV_KEYS = ("AI_BASE_URL", "AI_MODEL", "AI_TOKEN")


class StubProvider(BaseHTTPRequestHandler):
    """Локальный антропик-совместимый провайдер для теста проверки."""
    status = 200
    body = b'{"model": "stub-model"}'

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        self.send_response(self.status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"model": "stub-model"}).encode())

    def log_message(self, *args):  # тишина в тестовом выводе
        pass


class StreamUpstream(BaseHTTPRequestHandler):
    """Мини-стаб OpenAI-стрима (chat/completions) для openai-ветки проверки."""

    def do_POST(self):  # noqa: N802
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for c in [{"choices": [{"delta": {"role": "assistant", "content": "ок"},
                                "index": 0}]},
                  {"choices": [{"delta": {}, "index": 0,
                                "finish_reason": "stop"}]},
                  {"choices": [], "usage": {"prompt_tokens": 3,
                                            "completion_tokens": 2}}]:
            self.wfile.write(f"data: {json.dumps(c)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")

    def log_message(self, *args):
        pass


class AiFixture(unittest.TestCase):
    def setUp(self):
        self._env_backup = {k: os.environ.get(k) for k in ENV_KEYS}
        for k in ENV_KEYS:
            os.environ.pop(k, None)
        self._td = tempfile.TemporaryDirectory()
        self.conn = dbmod.connect(Path(self._td.name) / "t.db")
        web.STATE["conn"] = self.conn
        web.STATE["default_project"] = None
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        web.STATE["conn"] = None
        self.conn.close()
        self._td.cleanup()
        for k, v in self._env_backup.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=5) as r:
            return json.loads(r.read())

    def post(self, path, body=None):
        """Возвращает (код, тело); HTTPError не роняет тест."""
        req = urllib.request.Request(
            self.base + path, method="POST",
            data=json.dumps(body or {}).encode(),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())


class TestResolver(AiFixture):
    def test_priority_saved_over_env_over_unset(self):
        # модель не сохранена → берётся из окружения; остальное — сохранённое
        dbmod.ai_settings_set(self.conn, "anthropic", None,
                              "https://saved.example/anthropic", None,
                              token="sk-saved-abc")
        os.environ["AI_BASE_URL"] = "https://env.example/anthropic"
        os.environ["AI_MODEL"] = "env-model"
        eff = aip.effective(self.conn)
        self.assertEqual(eff["protocol"], "anthropic")
        self.assertEqual(eff["base_url"], "https://saved.example/anthropic")
        self.assertEqual(eff["sources"]["base_url"], "saved")
        self.assertEqual(eff["model"], "env-model")
        self.assertEqual(eff["sources"]["model"], "env")
        self.assertEqual(eff["sources"]["token"], "saved")
        self.assertEqual(eff["token_source"], "saved")

    def test_unset_when_nothing(self):
        eff = aip.effective(self.conn)
        self.assertIsNone(eff["protocol"])
        self.assertEqual(eff["sources"]["base_url"], "unset")
        self.assertEqual(eff["token_source"], "none")

    def test_mask_and_mask_text(self):
        self.assertIsNone(aip.mask(None))
        self.assertIsNone(aip.mask(""))
        self.assertEqual(aip.mask("sk-secret-1234"), "…1234")
        text = "invalid key sk-secret-1234 given"
        self.assertNotIn("sk-secret-1234", aip.mask_text(text, "sk-secret-1234"))
        self.assertIn("1234", aip.mask_text(text, "sk-secret-1234"))

    def test_session_env_anthropic_partial(self):
        dbmod.ai_settings_set(self.conn, "anthropic", None,
                              "https://saved.example", None)
        env = aip.session_env(self.conn)
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "https://saved.example")
        self.assertNotIn("ANTHROPIC_MODEL", env)
        self.assertNotIn("ANTHROPIC_AUTH_TOKEN", env)

    def test_session_env_empty_and_openai_gateway(self):
        self.assertEqual(aip.session_env(self.conn), {})
        dbmod.ai_settings_set(self.conn, "openai", None,
                              "https://api.openai.com/v1", "gpt-x")
        env = aip.session_env(self.conn)
        # Фаза 2: сессии получают адрес шлюза, не реальный провайдер
        self.assertTrue(env.get("ANTHROPIC_BASE_URL", "").startswith("http://127.0.0.1:"))
        self.assertEqual(env.get("ANTHROPIC_AUTH_TOKEN"), "gateway-local")
        self.assertEqual(env.get("ANTHROPIC_MODEL"), "gpt-x")
        # и шлюз действительно поднят
        import ai_gateway as gw
        self.assertTrue(gw.is_running())
        gw._ACTIVE.clear()  # не тащить синглтон в другие тесты

    def test_apply_env_does_not_mutate_on_error(self):
        self.conn.close()  # хранилище «недоступно»
        env = {"PATH": os.environ["PATH"]}
        out = aip.apply_env(env, self.conn)
        self.assertEqual(out, {"PATH": os.environ["PATH"]})
        self.conn = dbmod.connect(Path(self._td.name) / "t.db")


class TestDbSettings(AiFixture):
    def test_singleton_upsert(self):
        dbmod.ai_settings_set(self.conn, "anthropic", "z.ai (GLM)",
                              "https://a", "m1", token="sk-1")
        dbmod.ai_settings_set(self.conn, "anthropic", "z.ai (GLM)",
                              "https://b", "m2")
        rows = self.conn.execute("SELECT COUNT(*) c FROM ai_settings").fetchone()
        self.assertEqual(rows["c"], 1)
        row = dbmod.ai_settings_get(self.conn)
        self.assertEqual(row["base_url"], "https://b")
        self.assertEqual(row["token"], "sk-1")  # пустой токен = «без изменений»

    def test_clear_token(self):
        dbmod.ai_settings_set(self.conn, "anthropic", None, "https://a", None,
                              token="sk-1")
        dbmod.ai_settings_set(self.conn, "anthropic", None, "https://a", None,
                              clear_token=True)
        row = dbmod.ai_settings_get(self.conn)
        self.assertIsNone(row["token"])

    def test_protocol_check(self):
        with self.assertRaises(sqlite3.IntegrityError):
            dbmod.ai_settings_set(self.conn, "gpt4", None, None, None)


class TestRoutes(AiFixture):
    def test_get_empty_snapshot(self):
        code, doc = 200, self.get("/api/settings/ai")
        self.assertEqual(code, 200)
        self.assertEqual(doc["saved"]["protocol"], None)
        self.assertFalse(doc["hasToken"])
        self.assertIsNone(doc["tokenMask"])
        self.assertEqual(doc["sources"]["baseUrl"], "unset")
        self.assertGreaterEqual(len(doc["presets"]), 6)

    def test_get_never_returns_full_token(self):
        secret = "sk-full-secret-value-9876"
        dbmod.ai_settings_set(self.conn, "anthropic", None, "https://a", "m",
                              token=secret)
        doc = self.get("/api/settings/ai")
        self.assertTrue(doc["hasToken"])
        self.assertNotIn(secret, json.dumps(doc))
        self.assertEqual(doc["tokenMask"], "…9876")

    def test_get_contract_keys_camelcase(self):
        # контракт СТ 4.2.1: saved/sources используют baseUrl (camelCase)
        dbmod.ai_settings_set(self.conn, "anthropic", "z.ai (GLM)",
                              "https://api.z.ai/api/anthropic", "glm-4.5")
        doc = self.get("/api/settings/ai")
        self.assertEqual(doc["saved"]["baseUrl"], "https://api.z.ai/api/anthropic")
        self.assertEqual(doc["saved"]["provider"], "z.ai (GLM)")
        self.assertEqual(doc["sources"]["baseUrl"], "saved")
        self.assertEqual(doc["sources"]["protocol"], "saved")
        self.assertNotIn("base_url", json.dumps(doc))

    def test_save_and_rules(self):
        code, doc = self.post("/api/settings/ai", {
            "protocol": "anthropic", "provider": "z.ai (GLM)",
            "baseUrl": "https://api.z.ai/api/anthropic", "model": "glm-4.5",
            "token": "sk-new-5555"})
        self.assertEqual(code, 200)
        self.assertNotIn("warning", doc)
        row = dbmod.ai_settings_get(self.conn)
        self.assertEqual(row["token"], "sk-new-5555")
        # пустой токен не меняет сохранённый
        self.post("/api/settings/ai", {"protocol": "anthropic",
                                       "baseUrl": "https://api.z.ai/api/anthropic"})
        row = dbmod.ai_settings_get(self.conn)
        self.assertEqual(row["token"], "sk-new-5555")
        # clearToken возвращает к окружению
        self.post("/api/settings/ai", {"protocol": "anthropic", "clearToken": True})
        self.assertIsNone(dbmod.ai_settings_get(self.conn)["token"])

    def test_save_validation(self):
        code, _ = self.post("/api/settings/ai", {"protocol": "gpt4"})
        self.assertEqual(code, 400)
        code, _ = self.post("/api/settings/ai",
                            {"protocol": "anthropic", "baseUrl": "ftp://x"})
        self.assertEqual(code, 400)
        code, _ = self.post("/api/settings/ai", {"protocol": "anthropic"})
        self.assertEqual(code, 400)

    def test_save_openai_served(self):
        # Фаза 2: openai обслуживается — сохранение без предупреждения
        code, doc = self.post("/api/settings/ai", {
            "protocol": "openai", "baseUrl": "https://api.openai.com/v1"})
        self.assertEqual(code, 200)
        self.assertNotIn("warning", doc)

    def test_test_endpoint_success(self):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), StubProvider)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            port = srv.server_address[1]
            code, doc = self.post("/api/settings/ai/test", {
                "protocol": "anthropic",
                "baseUrl": f"http://127.0.0.1:{port}", "model": "stub-model"})
            self.assertEqual(code, 200)
            self.assertTrue(doc["ok"])
            self.assertEqual(doc["model"], "stub-model")
            self.assertIn("latencyMs", doc)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_test_endpoint_bad_token(self):
        class Denied(StubProvider):
            status = 401
            body = b'{"error": "invalid api key sk-secret-7777"}'

        srv = ThreadingHTTPServer(("127.0.0.1", 0), Denied)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            port = srv.server_address[1]
            code, doc = self.post("/api/settings/ai/test", {
                "protocol": "anthropic", "baseUrl": f"http://127.0.0.1:{port}",
                "model": "m", "token": "sk-secret-7777"})
            self.assertEqual(code, 200)
            self.assertFalse(doc["ok"])
            self.assertIn("токен", doc["human"])
            # токен замаскирован и в тех-причине
            self.assertNotIn("sk-secret-7777", doc["tech"])
        finally:
            srv.shutdown()
            srv.server_close()

    def test_test_endpoint_unreachable(self):
        code, doc = self.post("/api/settings/ai/test", {
            "protocol": "anthropic",
            "baseUrl": "http://127.0.0.1:9", "model": "m"})  # порт discard
        self.assertEqual(code, 200)
        self.assertFalse(doc["ok"])
        self.assertIn("human", doc)
        self.assertIn("tech", doc)

    def test_test_endpoint_openai_via_gateway(self):
        # Фаза 2: тест openai идёт через шлюз (стриминг + tool-определение)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), StreamUpstream)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            port = srv.server_address[1]
            code, doc = self.post("/api/settings/ai/test", {
                "protocol": "openai", "baseUrl": f"http://127.0.0.1:{port}",
                "model": "stub-model"})
            self.assertEqual(code, 200)
            self.assertTrue(doc["ok"], doc)
            self.assertIn("latencyMs", doc)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_test_endpoint_incomplete(self):
        code, _ = self.post("/api/settings/ai/test", {"protocol": "anthropic"})
        self.assertEqual(code, 400)


if __name__ == "__main__":
    unittest.main()
