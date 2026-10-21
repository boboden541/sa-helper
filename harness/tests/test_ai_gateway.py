"""Тесты шлюза протоколов (СТ FNR-10, задачи 4.4.1–4.4.2): перевод,
стриминг, жизненный цикл, сквозной прогон через локальный апстрим."""

from __future__ import annotations

import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ai_gateway as gw  # noqa: E402


class OpenAIStub(BaseHTTPRequestHandler):
    """Локальный OpenAI-совместимый провайдер: /chat/completions (json|sse)."""
    mode = "json"           # "json" | "stream"
    status = 200
    content = "Привет от стаба"
    tool_call = False

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        self.server.last_request = body  # для инспекции перевода
        if self.status != 200:
            payload = json.dumps({"error": {"message": "invalid api key"}}).encode()
            self.send_response(self.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.mode == "stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            chunks = [
                {"choices": [{"delta": {"role": "assistant", "content": "Пл"}, "index": 0}]},
                {"choices": [{"delta": {"content": "ривет"}, "index": 0}]},
            ]
            if self.tool_call:
                chunks += [
                    {"choices": [{"index": 0, "delta": {"content": None}}]},
                    {"choices": [{"index": 0, "delta": {"tool_calls": [
                        {"index": 0, "id": "call_1", "type": "function",
                         "function": {"name": "get_weather",
                                      "arguments": '{"city":'}}]}}]},
                    {"choices": [{"index": 0, "delta": {"tool_calls": [
                        {"index": 0, "function": {"arguments": '"Москва"}'}}]}}]},
                ]
            chunks.append({"choices": [{"delta": {}, "index": 0,
                                        "finish_reason": "tool_calls" if self.tool_call
                                        else "stop"}]})
            chunks.append({"choices": [], "usage": {"prompt_tokens": 12,
                                                    "completion_tokens": 7}})
            for c in chunks:
                self.wfile.write(f"data: {json.dumps(c)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        else:
            message: dict = {"role": "assistant", "content": self.content}
            if self.tool_call:
                message = {"role": "assistant", "content": None,
                           "tool_calls": [{"id": "call_9", "type": "function",
                                           "function": {"name": "get_weather",
                                                        "arguments": '{"city": "Москва"}'}}]}
            doc = {"id": "chatcmpl-1",
                   "choices": [{"index": 0, "message": message,
                                "finish_reason": "tool_calls" if self.tool_call
                                else "stop"}],
                   "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
            payload = json.dumps(doc).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    def log_message(self, *args):
        pass


class GatewayFixture(unittest.TestCase):
    def setUp(self):
        self.upstream = ThreadingHTTPServer(("127.0.0.1", 0), OpenAIStub)
        threading.Thread(target=self.upstream.serve_forever, daemon=True).start()
        self.up_port = self.upstream.server_address[1]
        self.gw_srv = gw.start({"upstream_base_url": f"http://127.0.0.1:{self.up_port}",
                                "upstream_token": "sk-upstream-secret",
                                "model": "stub"})
        self.gw_port = self.gw_srv.server_address[1]

    def tearDown(self):
        self.gw_srv.shutdown()
        self.gw_srv.server_close()
        self.upstream.shutdown()
        self.upstream.server_close()

    def post_messages(self, body, stream=False):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.gw_port}/v1/messages",
            data=json.dumps(body).encode(), method="POST",
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                if stream:
                    return 200, r.read().decode("utf-8")
                return 200, json.loads(r.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())


class TestTranslation(unittest.TestCase):
    def test_system_and_plain_message(self):
        out = gw.build_openai_payload({
            "model": "m", "max_tokens": 100, "system": "Ты аккуратен.",
            "messages": [{"role": "user", "content": "привет"}]})
        self.assertEqual(out["messages"][0], {"role": "system",
                                              "content": "Ты аккуратен."})
        self.assertEqual(out["messages"][1], {"role": "user", "content": "привет"})
        self.assertEqual(out["max_tokens"], 100)
        self.assertNotIn("tools", out)

    def test_tools_and_choice_any(self):
        out = gw.build_openai_payload({
            "model": "m", "max_tokens": 10,
            "tools": [{"name": "get_weather", "description": "Погода",
                       "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}}}],
            "tool_choice": {"type": "any"},
            "messages": [{"role": "user", "content": "x"}]})
        self.assertEqual(out["tools"][0]["type"], "function")
        self.assertEqual(out["tools"][0]["function"]["name"], "get_weather")
        self.assertEqual(out["tool_choice"], "required")

    def test_assistant_tool_use_and_tool_result(self):
        out = gw.build_openai_payload({
            "model": "m", "max_tokens": 10,
            "messages": [
                {"role": "user", "content": "Погода?"},
                {"role": "assistant", "content": [
                    {"type": "tool_use", "id": "call_1", "name": "get_weather",
                     "input": {"city": "Москва"}}]},
                {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": "call_1",
                     "content": "+5"},
                    {"type": "text", "text": "И что скажешь?"}]},
            ]})
        msgs = out["messages"]
        self.assertEqual(msgs[1]["role"], "assistant")
        self.assertEqual(msgs[1]["tool_calls"][0]["function"]["name"], "get_weather")
        self.assertEqual(json.loads(msgs[1]["tool_calls"][0]["function"]["arguments"]),
                         {"city": "Москва"})
        self.assertEqual(msgs[2]["role"], "tool")
        self.assertEqual(msgs[2]["tool_call_id"], "call_1")
        self.assertEqual(msgs[2]["content"], "+5")
        self.assertEqual(msgs[3], {"role": "user", "content": "И что скажешь?"})

    def test_response_text_and_usage(self):
        res = gw.anthropic_response_from_openai(
            {"choices": [{"message": {"role": "assistant", "content": "ок"},
                          "finish_reason": "stop"}],
             "usage": {"prompt_tokens": 3, "completion_tokens": 2}}, "m", "msg_1")
        self.assertEqual(res["content"], [{"type": "text", "text": "ок"}])
        self.assertEqual(res["stop_reason"], "end_turn")
        self.assertEqual(res["usage"], {"input_tokens": 3, "output_tokens": 2})

    def test_response_tool_calls_to_tool_use(self):
        res = gw.anthropic_response_from_openai(
            {"choices": [{"message": {"role": "assistant", "content": None,
                                      "tool_calls": [{"id": "c1", "type": "function",
                                                      "function": {"name": "f",
                                                                   "arguments": '{"a": 1}'}}]},
                          "finish_reason": "tool_calls"}], "usage": {}}, "m", "msg_2")
        self.assertEqual(res["stop_reason"], "tool_use")
        self.assertEqual(res["content"][0]["type"], "tool_use")
        self.assertEqual(res["content"][0]["input"], {"a": 1})


class TestStreamTranslator(unittest.TestCase):
    def feed(self, chunks):
        tr = gw.StreamTranslator("m", "msg_x")
        for c in chunks:
            tr.translate(c)
        tr.finish("stop", {"completion_tokens": 4})
        return tr.events

    def test_text_stream_canonical_order(self):
        events = self.feed([
            {"choices": [{"delta": {"content": "Од"}, "index": 0}]},
            {"choices": [{"delta": {"content": "нако"}, "index": 0}]},
        ])
        names = [n for n, _ in events]
        self.assertEqual(names[0], "message_start")
        self.assertIn("content_block_start", names)
        self.assertEqual(names.count("content_block_delta"), 2)
        self.assertIn("message_delta", names)
        self.assertEqual(names[-1], "message_stop")
        text = "".join(e["delta"]["text"] for n, e in events
                       if n == "content_block_delta")
        self.assertEqual(text, "Однако")

    def test_tool_call_fragments_input_json_delta(self):
        events = self.feed([
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "c1", "function": {"name": "f",
                                                      "arguments": '{"a":'}}]}}]},
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "function": {"arguments": '1}'}}]}}]},
        ])
        starts = [e for n, e in events if n == "content_block_start"]
        self.assertEqual(starts[0]["content_block"]["type"], "tool_use")
        self.assertEqual(starts[0]["content_block"]["name"], "f")
        partial = "".join(e["delta"]["partial_json"] for n, e in events
                          if n == "content_block_delta")
        self.assertEqual(json.loads(partial), {"a": 1})
        delta_stop = [e for n, e in events if n == "message_delta"][0]
        self.assertEqual(delta_stop["delta"]["stop_reason"], "tool_use" if False else "end_turn")
        # finish_reason здесь "stop" — stop_reason должен быть end_turn

    def test_empty_stream_still_closes(self):
        events = self.feed([])
        names = [n for n, _ in events]
        self.assertEqual(names[0], "message_start")
        self.assertEqual(names[-1], "message_stop")


class TestEndToEnd(GatewayFixture):
    def test_non_stream_message(self):
        code, res = self.post_messages({
            "model": "stub", "max_tokens": 50,
            "messages": [{"role": "user", "content": "привет"}]})
        self.assertEqual(code, 200)
        self.assertEqual(res["type"], "message")
        self.assertEqual(res["content"][0]["text"], "Привет от стаба")
        self.assertEqual(res["stop_reason"], "end_turn")
        # перевод ушёл апстриму: модель и сообщение дошли
        sent = self.upstream.last_request
        self.assertEqual(sent["model"], "stub")
        self.assertEqual(sent["messages"][-1]["content"], "привет")

    def test_non_stream_tool_call(self):
        type(self).upstream_has_tool = True
        OpenAIStub.tool_call = True
        try:
            code, res = self.post_messages({
                "model": "stub", "max_tokens": 50,
                "messages": [{"role": "user", "content": "Погода?"}]})
            self.assertEqual(code, 200)
            self.assertEqual(res["stop_reason"], "tool_use")
            block = res["content"][0]
            self.assertEqual(block["type"], "tool_use")
            self.assertEqual(block["input"], {"city": "Москва"})
        finally:
            OpenAIStub.tool_call = False

    def test_stream_message(self):
        OpenAIStub.mode = "stream"
        try:
            code, raw = self.post_messages({
                "model": "stub", "max_tokens": 50, "stream": True,
                "messages": [{"role": "user", "content": "привет"}]}, stream=True)
            self.assertEqual(code, 200)
            self.assertIn("event: message_start", raw)
            self.assertIn("event: content_block_delta", raw)
            self.assertIn('"text_delta"', raw)
            self.assertIn("event: message_stop", raw)
            self.assertIn("ривет", raw)
        finally:
            OpenAIStub.mode = "json"

    def test_stream_tool_call_fragments(self):
        OpenAIStub.mode = "stream"
        OpenAIStub.tool_call = True
        try:
            code, raw = self.post_messages({
                "model": "stub", "max_tokens": 50, "stream": True,
                "messages": [{"role": "user", "content": "Погода?"}]}, stream=True)
            self.assertEqual(code, 200)
            self.assertIn('"input_json_delta"', raw)
            self.assertIn('"city":', raw.replace("\\", ""))
            self.assertIn('"stop_reason": "tool_use"', raw)
        finally:
            OpenAIStub.mode = "json"
            OpenAIStub.tool_call = False

    def test_upstream_401_becomes_anthropic_error(self):
        OpenAIStub.status = 401
        try:
            code, res = self.post_messages({
                "model": "stub", "max_tokens": 10,
                "messages": [{"role": "user", "content": "x"}]})
            self.assertEqual(code, 401)
            self.assertEqual(res["type"], "error")
            self.assertEqual(res["error"]["type"], "authentication_error")
        finally:
            OpenAIStub.status = 200

    def test_count_tokens_stub(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.gw_port}/v1/messages/count_tokens",
            data=b"{}", method="POST",
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            doc = json.loads(r.read())
        self.assertIn("input_tokens", doc)


if __name__ == "__main__":
    unittest.main()
