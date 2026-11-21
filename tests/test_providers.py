"""Provider selection + the OpenAI-compatible HTTP client, against a local stub server.

No internet or API key needed: a tiny HTTP server on 127.0.0.1 plays the part of
Gemini / Ollama / any OpenAI-compatible API.
"""

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from healwright.llm import AnthropicProvider, OpenAICompatibleProvider, default_provider
from healwright.runner import run_file


@pytest.fixture
def stub_server():
    """Yields (base_url, requests_seen, set_reply)."""
    seen = []
    state = {"reply": lambda body: "{}"}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            seen.append({"path": self.path, "auth": self.headers.get("authorization"), "body": body})
            content = state["reply"](body)
            out = json.dumps({"choices": [{"message": {"role": "assistant", "content": content}}]}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):  # keep test output clean
            pass

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/v1", seen, lambda f: state.update(reply=f)
    srv.shutdown()


# ---- choosing a provider from env vars --------------------------------------

def test_no_keys_means_heuristic_only():
    assert default_provider({}) is None


def test_gemini_key_auto_detected():
    p = default_provider({"GEMINI_API_KEY": "g-key"})
    assert isinstance(p, OpenAICompatibleProvider)
    assert p.name == "gemini" and p.api_key == "g-key"
    assert "generativelanguage.googleapis.com" in p.base_url


def test_anthropic_wins_auto_detect_when_both_set():
    p = default_provider({"ANTHROPIC_API_KEY": "a", "GEMINI_API_KEY": "g"})
    assert isinstance(p, AnthropicProvider)


def test_explicit_choice_and_model_override():
    p = default_provider({"HEALWRIGHT_PROVIDER": "ollama", "HEALWRIGHT_MODEL": "qwen2.5"})
    assert p.name == "ollama" and p.model == "qwen2.5" and p.api_key is None


def test_misconfiguration_gives_clear_error():
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        default_provider({"HEALWRIGHT_PROVIDER": "gemini"})
    with pytest.raises(RuntimeError, match="Unknown"):
        default_provider({"HEALWRIGHT_PROVIDER": "nope"})


# ---- the real HTTP client, against the stub --------------------------------

def test_openai_compatible_request_shape(stub_server):
    base, seen, set_reply = stub_server
    set_reply(lambda body: "hello")
    p = OpenAICompatibleProvider(base, "some-model", api_key="secret")
    assert p.complete("sys", "hi") == "hello"
    req = seen[0]
    assert req["path"] == "/v1/chat/completions"
    assert req["auth"] == "Bearer secret"
    assert req["body"]["model"] == "some-model"
    assert [m["role"] for m in req["body"]["messages"]] == ["system", "user"]


def test_llm_heal_end_to_end_over_http(stub_server, tmp_path, v2_url):
    """Full path: runner -> LLMHealer -> HTTP -> 'model' picks the submit button."""
    base, seen, set_reply = stub_server

    def pick_submit(body):
        user = body["messages"][1]["content"]
        idx = next(int(m.group(1)) for m in re.finditer(r"^(\d+): (.*)$", user, re.M)
                   if "Log in to Acme" in m.group(2))
        return f'```json\n{{"index": {idx}, "confidence": 0.9, "reason": "submit"}}\n```'

    set_reply(pick_submit)
    spec = tmp_path / "t.yaml"
    spec.write_text(
        "name: llm\nsteps:\n"
        "- {action: goto, intent: open, value: login.html}\n"
        "- {action: click, intent: the primary action}\n"
    )
    provider = OpenAICompatibleProvider(base, "stub-model", name="stub")
    report = run_file(spec, base_url=v2_url, provider=provider)
    assert report.passed and report.steps[1].method == "llm"
    assert len(seen) == 1


# ---- retries and readable errors (D-017) -----------------------------------

@pytest.fixture
def flaky_server():
    """Answers with the given status codes in order, then 200 with 'ok'."""
    state = {"codes": [], "hits": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["content-length"]))
            state["hits"] += 1
            code = state["codes"].pop(0) if state["codes"] else 200
            out = (json.dumps({"choices": [{"message": {"content": "ok"}}]}) if code == 200
                   else '{"error": "busy"}').encode()
            self.send_response(code)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/v1", state
    srv.shutdown()


def test_retries_on_503_then_succeeds(flaky_server):
    base, state = flaky_server
    state["codes"] = [503, 429]
    p = OpenAICompatibleProvider(base, "m", retry_delays=[0, 0, 0])
    assert p.complete("s", "u") == "ok"
    assert state["hits"] == 3


def test_gives_up_with_readable_error(flaky_server):
    from healwright.llm import LLMError
    base, state = flaky_server
    state["codes"] = [503] * 10
    p = OpenAICompatibleProvider(base, "m", retry_delays=[0, 0])
    with pytest.raises(LLMError, match="HTTP 503 after 3 attempts.*busy"):
        p.complete("s", "u")


def test_no_retry_on_bad_key(flaky_server):
    from healwright.llm import LLMError
    base, state = flaky_server
    state["codes"] = [401]
    p = OpenAICompatibleProvider(base, "m", retry_delays=[0, 0])
    with pytest.raises(LLMError, match="API key was rejected"):
        p.complete("s", "u")
    assert state["hits"] == 1


def test_unreachable_server_is_explained():
    from healwright.llm import LLMError
    p = OpenAICompatibleProvider("http://127.0.0.1:9/v1", "m", retry_delays=[])
    with pytest.raises(LLMError, match="Could not reach"):
        p.complete("s", "u")


def test_llm_failure_is_shown_in_step_error(flaky_server, tmp_path, v2_url):
    base, state = flaky_server
    state["codes"] = [503] * 10
    spec = tmp_path / "t.yaml"
    spec.write_text(
        "name: llm\nsteps:\n"
        "- {action: goto, intent: open, value: login.html}\n"
        "- {action: click, intent: the primary action}\n"
    )
    provider = OpenAICompatibleProvider(base, "m", retry_delays=[0])
    report = run_file(spec, base_url=v2_url, provider=provider)
    assert not report.passed
    assert "LLM error: HTTP 503" in report.steps[1].error
