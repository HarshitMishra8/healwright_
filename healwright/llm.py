"""LLM providers. Pluggable so tests can run offline (DECISIONS D-006)."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Callable, Protocol

# HTTP codes worth retrying: rate limit (429) and "server busy/broken" (5xx). See D-017.
RETRYABLE = {429, 500, 502, 503, 504}
RETRY_DELAYS = [2, 5, 10]  # seconds between attempts; 4 attempts in total


class LLMError(Exception):
    """An LLM call failed in a way the user should hear about in plain words."""


_HINTS = {
    400: "The request was rejected. Check that the API key is correct.",
    401: "The API key was rejected. Check it, or create a new one.",
    403: "The API key is not allowed to use this model.",
    404: "Model not found. Set HEALWRIGHT_MODEL to a model your provider offers.",
    429: "Rate limit reached (free tiers allow only a few requests per minute). Wait a minute and retry.",
    503: "The provider's servers are busy. Retry later, or try a lighter model via HEALWRIGHT_MODEL.",
}


def post_json(url: str, payload: dict, headers: dict, timeout: float, delays=None) -> dict:
    """POST JSON with retries on 429/5xx. Raises LLMError with a readable message."""
    delays = RETRY_DELAYS if delays is None else delays
    body = json.dumps(payload).encode()
    for attempt in range(len(delays) + 1):
        req = urllib.request.Request(url, data=body, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code in RETRYABLE and attempt < len(delays):
                retry_after = e.headers.get("retry-after") if e.headers else None
                wait = float(retry_after) if retry_after and retry_after.isdigit() else delays[attempt]
                time.sleep(min(wait, 60))
                continue
            detail = ""
            try:
                detail = e.read().decode(errors="replace")[:300]
            except Exception:
                pass
            hint = _HINTS.get(e.code, "")
            tries = f" after {attempt + 1} attempts" if attempt else ""
            raise LLMError(f"HTTP {e.code}{tries}. {hint} {detail}".strip()) from None
        except urllib.error.URLError as e:
            raise LLMError(f"Could not reach {url}: {e.reason}. Check your internet connection "
                           "(or that Ollama is running, for local models).") from None
    raise LLMError("unreachable")  # pragma: no cover


class LLMProvider(Protocol):
    def complete(self, system: str, user: str) -> str: ...


class AnthropicProvider:
    """Calls the Anthropic Messages API with the standard library only.

    Needs ``ANTHROPIC_API_KEY``. Model can be overridden with ``HEALWRIGHT_MODEL``.
    """

    name = "anthropic"
    URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, api_key: str | None = None, model: str | None = None, timeout: float = 60):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        self.model = model or os.environ.get("HEALWRIGHT_MODEL", "claude-sonnet-5-5")
        self.timeout = timeout

    def complete(self, system: str, user: str) -> str:
        data = post_json(self.URL, {
            "model": self.model,
            "max_tokens": 2000,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }, {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }, self.timeout)
        return "".join(b.get("text", "") for b in data.get("content", []))


class OpenAICompatibleProvider:
    """Any API that speaks the OpenAI ``/chat/completions`` format (D-015).

    Covers Google Gemini (free tier), Ollama (free, local), Groq, OpenRouter,
    OpenAI and others, by changing only ``base_url``, ``api_key`` and ``model``.
    """

    def __init__(self, base_url: str, model: str, api_key: str | None = None,
                 name: str = "openai-compatible", timeout: float = 120, retry_delays=None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.name = name
        self.timeout = timeout
        self.retry_delays = retry_delays

    def complete(self, system: str, user: str) -> str:
        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        data = post_json(f"{self.base_url}/chat/completions", {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0,
        }, headers, self.timeout, self.retry_delays)
        return data["choices"][0]["message"]["content"] or ""


# Ready-made settings for popular OpenAI-compatible services.
# The model can always be changed with HEALWRIGHT_MODEL.
PRESETS = {
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
               "model": "gemini-3.8-flash", "key_env": "GEMINI_API_KEY"},
    "ollama": {"base_url": "http://localhost:11434/v1", "model": "llama3.2", "key_env": None},
}


class FakeProvider:
    """Test double: returns whatever ``responder(system, user)`` returns."""

    name = "fake"

    def __init__(self, responder: Callable[[str, str], str]):
        self.responder = responder
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.responder(system, user)


def extract_json(text: str):
    """Pull the first JSON object/array out of an LLM reply (tolerates ```json fences)."""
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    start = min([i for i in (text.find("{"), text.find("[")) if i != -1], default=-1)
    if start == -1:
        raise ValueError(f"No JSON found in LLM reply: {text[:200]!r}")
    return json.JSONDecoder().raw_decode(text[start:])[0]


def default_provider(env: dict | None = None) -> LLMProvider | None:
    """Pick a provider from environment variables (D-015).

    1. ``HEALWRIGHT_PROVIDER`` = anthropic | gemini | ollama | openai-compatible, if set.
       openai-compatible also needs ``HEALWRIGHT_BASE_URL`` and ``HEALWRIGHT_MODEL``
       (and ``HEALWRIGHT_API_KEY`` if the service needs a key).
    2. Otherwise auto-detect: ``ANTHROPIC_API_KEY``, then ``GEMINI_API_KEY``.
    3. Otherwise None: heuristic-only healing, which is free and offline.
    """
    env = os.environ if env is None else env
    choice = env.get("HEALWRIGHT_PROVIDER", "").strip().lower()
    model = env.get("HEALWRIGHT_MODEL")

    if not choice:
        if env.get("ANTHROPIC_API_KEY"):
            choice = "anthropic"
        elif env.get("GEMINI_API_KEY"):
            choice = "gemini"
        else:
            return None

    if choice == "anthropic":
        key = env.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("HEALWRIGHT_PROVIDER=anthropic needs ANTHROPIC_API_KEY")
        return AnthropicProvider(api_key=key, model=model)
    if choice in PRESETS:
        p = PRESETS[choice]
        key = env.get(p["key_env"]) if p["key_env"] else None
        if p["key_env"] and not key:
            raise RuntimeError(f"HEALWRIGHT_PROVIDER={choice} needs {p['key_env']}")
        return OpenAICompatibleProvider(p["base_url"], model or p["model"], key, name=choice)
    if choice == "openai-compatible":
        base = env.get("HEALWRIGHT_BASE_URL")
        if not base or not model:
            raise RuntimeError("openai-compatible needs HEALWRIGHT_BASE_URL and HEALWRIGHT_MODEL")
        return OpenAICompatibleProvider(base, model, env.get("HEALWRIGHT_API_KEY"))
    raise RuntimeError(f"Unknown HEALWRIGHT_PROVIDER: {choice!r}")
