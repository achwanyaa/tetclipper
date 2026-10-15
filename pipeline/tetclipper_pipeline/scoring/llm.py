"""LLM backends: Gemini (your own key) and Ollama (local). The default
brain is Claude Code (scoring/brain.py), which needs neither.

One interface: generate_json(prompt, schema, images) → dict, with disk
caching keyed on (backend, model, prompt, schema) so re-runs never re-spend
— the M2 gate requires cache hits on identical inputs.

Gemini key resolution: TETCLIPPER_GEMINI_API_KEY env var, then secrets.json
{"gemini_api_key": "..."}. Ollama needs no key — just a running daemon.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import httpx

from .. import config

# The rolling alias, deliberately: Google retires pinned models for NEW api
# keys while still advertising them in ListModels (learned live — 404 "no
# longer available to new users" on gemini-2.5-flash with a fresh key).
GEMINI_MODEL = "gemini-flash-latest"
# Tried in order when Google keeps answering the model above with a 5xx
# ("the model is overloaded"), a 404 (retired for this key) or a quota 429.
# Free-tier keys are shed from the flagship flash alias first, and a
# brand-new key stayed shed for three days straight (Windows report, Oct 7
# 2026: "Gemini call failed after retries: Server error '503'") while the
# lite aliases answered the same key in about a second. Each alias has its
# own quota, so a lite model is a different queue, not the same one again.
GEMINI_FALLBACK_MODELS = (
    "gemini-flash-lite-latest",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash-lite",
)
# Seconds to wait before the 2nd and 3rd try on the same model. The old loop
# retried instantly, so an overloaded model took three hits inside a second
# and the job failed before Google could have let the next request through.
GEMINI_RETRY_WAITS = (3.0, 8.0)
GEMINI_IMAGE_MODEL = "gemini-3.1-flash-image"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com"
GENERATE_PATH = "/v1beta/models/{model}:generateContent"
OLLAMA_URL = "http://localhost:11434"
LLM_TIMEOUT = 120.0

class LlmError(Exception):
    """User-actionable LLM failure (bad key, daemon down, model missing)."""


@dataclass(frozen=True)
class Endpoint:
    """Where a generateContent call goes. The wire format is Gemini's either
    way; `provider` says whose key is on the header and who is billed."""

    provider: str  # 'gemini'
    base_url: str  # everything before /v1beta/...
    key: str
    model: str
    image_model: str

    def url(self, model: str | None = None) -> str:
        return self.base_url.rstrip("/") + GENERATE_PATH.format(model=model or self.model)


def _secrets() -> dict:
    path = config.home_dir() / "secrets.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def gemini_api_key() -> str | None:
    key = os.environ.get("TETCLIPPER_GEMINI_API_KEY")
    if key:
        return key
    return _secrets().get("gemini_api_key") or None


def resolve_endpoint(llm_mode: str) -> Endpoint:
    key = gemini_api_key()
    if not key:
        raise LlmError(
            "No Gemini API key found. Add one in Settings (or set "
            "TETCLIPPER_GEMINI_API_KEY), or switch the brain to Claude Code or Ollama."
        )
    return Endpoint(
        "gemini",
        os.environ.get("TETCLIPPER_GEMINI_BASE_URL") or GEMINI_BASE_URL,
        key.strip(),
        GEMINI_MODEL,
        GEMINI_IMAGE_MODEL,
    )


def _error_message(res: httpx.Response, default: str = "request failed") -> str:
    try:
        return str(res.json()["error"]["message"])
    except Exception:  # noqa: BLE001
        return default


def _parse_answer(res: httpx.Response) -> dict:
    """The JSON object the model wrote, out of a generateContent answer."""
    payload = res.json()
    text = payload["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(_strip_fences(text))


def _cache_dir() -> Path:
    path = config.home_dir() / "llm-cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_key(backend: str, model: str, prompt: str, schema: dict, images: list[bytes]) -> str:
    h = hashlib.sha256()
    h.update(backend.encode())
    h.update(model.encode())
    h.update(prompt.encode())
    h.update(json.dumps(schema, sort_keys=True).encode())
    for img in images:
        h.update(hashlib.sha256(img).digest())
    return h.hexdigest()[:32]


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


class GeminiClient:
    """Gemini's generateContent wire format with the user's own key. The T2
    vision pass and the confidence label key on `backend` (scoring/stage.py)."""

    backend = "gemini"

    def __init__(self, endpoint: Endpoint | None = None, notify: Callable[[str], None] | None = None):
        self.endpoint = endpoint or resolve_endpoint("gemini")
        # The model calls go to right now. Own-key mode moves it down
        # GEMINI_FALLBACK_MODELS when Google keeps refusing, and it stays
        # moved for the rest of the run so moment 2 of 35 doesn't pay the
        # same three-strikes wait moment 1 did.
        self.model = self.endpoint.model
        self.provider = self.endpoint.provider
        # One line per model switch, for the progress panel; None = silent.
        self.notify = notify
        self._models_left: list[str] = [m for m in GEMINI_FALLBACK_MODELS if m != self.model]

    def generate_json(
        self, prompt: str, schema: dict, images: list[bytes] | None = None
    ) -> dict:
        images = images or []
        parts: list[dict[str, Any]] = [{"text": prompt}]
        for img in images:
            import base64

            parts.append(
                {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(img).decode()}}
            )
        body = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": schema,
                "temperature": 0.2,
            },
        }
        # Header transport, never ?key= — a key in the URL leaks through
        # logs and URL scans (Google's own guidance).
        headers = {"x-goog-api-key": self.endpoint.key}
        return self._gemini_call(body, headers, prompt, schema, images)

    def _gemini_call(
        self, body: dict, headers: dict, prompt: str, schema: dict, images: list[bytes]
    ) -> dict:
        """Own-key mode: the current model first, then each fallback, each
        with up to three tries. A model is given up on only for what that
        model did (5xx, quota 429, 404); a dead network fails here, since
        the next model would time out just the same."""
        models = [self.model, *self._models_left]
        failures: list[str] = []
        for idx, model in enumerate(models):
            key = _cache_key(self.backend, model, prompt, schema, images)
            cache_file = _cache_dir() / f"{key}.json"
            if cache_file.exists():
                return json.loads(cache_file.read_text())
            verdict, payload = self._try_model(model, body, headers)
            if verdict == "ok":
                cache_file.write_text(json.dumps(payload))
                self.model = model
                self._models_left = models[idx + 1 :]
                return payload
            failures.append(f"{model}: {payload}")
            if idx + 1 < len(models) and self.notify:
                self.notify(f"Gemini {model} answered {payload}; trying {models[idx + 1]}")
        raise LlmError(
            "Gemini could not answer on any model (" + "; ".join(failures) + "). "
            "Google turns free keys away first when its servers are busy. Wait a few "
            "minutes and run again, or switch the brain to Claude Code in Settings."
        )

    def _try_model(self, model: str, body: dict, headers: dict) -> tuple[str, Any]:
        """Up to three tries on one model. ("ok", data) on success; ("next",
        reason) when this model is the problem and the next one should be
        tried; raises LlmError when trying another model cannot help."""
        url = self.endpoint.url(model)
        last_err: Exception | None = None
        for attempt in range(3):
            if attempt:
                time.sleep(GEMINI_RETRY_WAITS[attempt - 1])
            try:
                res = httpx.post(url, headers=headers, json=body, timeout=LLM_TIMEOUT)
            except httpx.HTTPError as err:
                last_err = err  # the network, not the model
                continue
            status = res.status_code
            if status in (401, 403):
                raise LlmError("Gemini rejected the API key. Check it in Settings.")
            if status == 404:
                # Retired for this key ("no longer available to new users");
                # it will say so again, so straight to the next model.
                return "next", f"404 {_error_message(res, 'model not found')}"
            if status == 429:
                detail = _error_message(res, "rate limited")
                if "credit" in detail.lower() or "billing" in detail.lower():
                    raise LlmError(f"Gemini 429: {detail}")
                last_err = LlmError(f"429 {detail}")
                continue
            if status >= 500:
                last_err = LlmError(f"{status} {_error_message(res, 'server error')}")
                continue
            try:
                res.raise_for_status()
                data = _parse_answer(res)
            except (httpx.HTTPError, KeyError, json.JSONDecodeError, IndexError) as err:
                last_err = err
                continue
            return "ok", data
        if isinstance(last_err, LlmError):
            # three 5xx or quota answers in a row: this model's problem
            return "next", str(last_err)
        raise LlmError(f"Gemini call failed after retries: {last_err}")


class OllamaClient:
    backend = "ollama"

    def __init__(self, model: str | None = None):
        try:
            res = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=5.0)
            res.raise_for_status()
        except httpx.HTTPError as err:
            raise LlmError(
                "Ollama isn't running. Start it (`ollama serve`) or switch to Claude Code or your own Gemini key."
            ) from err
        models = [m["name"] for m in res.json().get("models", [])]
        if not models:
            raise LlmError("Ollama has no models. Pull one, e.g. `ollama pull llama3.1:8b`.")
        self.model = model if model in models else _pick_ollama_model(models)

    def generate_json(
        self, prompt: str, schema: dict, images: list[bytes] | None = None
    ) -> dict:
        if images:
            # Text-only fallback: the caller records visual as signals_missing.
            images = []
        cache_file = _cache_dir() / f"{_cache_key(self.backend, self.model, prompt, schema, [])}.json"
        if cache_file.exists():
            return json.loads(cache_file.read_text())
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "format": schema,
            "stream": False,
            "options": {"temperature": 0.1},
        }
        try:
            res = httpx.post(f"{OLLAMA_URL}/api/chat", json=body, timeout=600.0)
            res.raise_for_status()
            data = json.loads(_strip_fences(res.json()["message"]["content"]))
        except (httpx.HTTPError, KeyError, json.JSONDecodeError) as err:
            raise LlmError(f"Ollama call failed: {err}") from err
        cache_file.write_text(json.dumps(data))
        return data


def _pick_ollama_model(models: list[str]) -> str:
    """Prefer capable general models, and among them the LARGEST — list
    order once handed us qwen2.5:3b while 7b sat right there."""
    import re

    def size_of(name: str) -> float:
        m = re.search(r"(\d+(?:\.\d+)?)b", name.lower())
        return float(m.group(1)) if m else 0.0

    candidates = [
        name
        for prefix in ("llama3.1", "llama3", "qwen2.5", "qwen3", "mistral", "gemma2", "gemma3")
        for name in models
        if name.startswith(prefix)
    ]
    if candidates:
        return max(candidates, key=size_of)
    return models[0]


def make_client(llm_mode: str, notify: Callable[[str], None] | None = None):
    if llm_mode == "claude":
        from .brain import ClaudeHandoffClient

        return ClaudeHandoffClient()
    if llm_mode == "ollama":
        return OllamaClient()
    return GeminiClient(resolve_endpoint(llm_mode), notify=notify)
