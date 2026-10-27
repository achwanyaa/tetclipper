"""Studio chat on an API model: one editing agent, any provider.

The admin picks the provider, model and API key once (Studio → AI model);
it is stored server-side in ~/.tetclipper/ai.json and applies to every user.
Keys never go back to the browser, only a masked hint.

Providers:
- claude-code: the Claude Code CLI on this PC (studio_chat.py), no key.
- anthropic: Claude through the Anthropic SDK.
- deepseek, nvidia, custom: OpenAI-compatible chat completions through the
  OpenAI SDK pointed at that provider's base URL.

Every API provider gets the same tools. The agent never writes files: each
edit goes through store.save(), which validates first, so an invalid edit is
rejected with its problems and the model can fix it in the same turn.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from ..spec import store

# ---------- providers and settings ----------

PROVIDERS: dict[str, dict[str, Any]] = {
    "claude-code": {
        "label": "Claude Code (this PC)",
        "kind": "cli",
        "note": "Uses the Claude plan signed in on this computer. No API key. Only works in the desktop app.",
        "models": [],
    },
    "anthropic": {
        "label": "Claude (Anthropic API)",
        "kind": "anthropic",
        "key_url": "https://console.anthropic.com/settings/keys",
        "default": "claude-haiku-5-5",
        "models": ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"],
    },
    "deepseek": {
        "label": "DeepSeek",
        "kind": "openai",
        "base_url": "https://api.deepseek.com",
        "key_url": "https://platform.deepseek.com/api_keys",
        "default": "deepseek-chat",
        "models": ["deepseek-chat", "deepseek-reasoner"],
    },
    "nvidia": {
        "label": "NVIDIA (build.nvidia.com)",
        "kind": "openai",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "key_url": "https://build.nvidia.com/settings/api-keys",
        "default": "meta/llama-3.3-70b-instruct",
        "models": ["meta/llama-3.3-70b-instruct"],
        "note": "Pick a model that supports tool calling; many NVIDIA models don't.",
    },
    "custom": {
        "label": "Other (OpenAI-compatible)",
        "kind": "openai",
        "note": "Any OpenAI-compatible endpoint, such as OpenRouter or Groq. Enter its base URL.",
        "models": [],
    },
}

# $ per million tokens (input, output), Claude API first-party prices.
ANTHROPIC_PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-fable-5-1": (10.0, 50.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-4-6": (3.0, 15.0),
}
# Models that take `effort` and adaptive thinking; older ones reject `effort`.
EFFORT_MODELS = {"claude-haiku-5-5", "claude-sonnet-5-5", "claude-sonnet-5", "claude-opus-5-5", "claude-opus-5", "claude-fable-5-1"}
# Models with server-side refusal fallback ("default" routing).
FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-1"}

DEFAULT = {"provider": "claude-code", "model": "", "base_url": "", "keys": {}, "prices": {}}


def _path() -> Path:
    from .app import home_dir  # lazy: app imports studio, which imports this module

    return home_dir() / "ai.json"


def load_settings() -> dict:
    from .app import _read_json

    data = {**DEFAULT, **(_read_json(_path()) or {})}
    if data["provider"] not in PROVIDERS:
        data["provider"] = "claude-code"
    return data


def _mask(key: str) -> str:
    return f"{key[:6]}…{key[-4:]}" if len(key) > 12 else "set"


def public_settings() -> dict:
    """Settings for the browser: masked keys, never the keys themselves."""
    s = load_settings()
    return {
        "provider": s["provider"],
        "model": s["model"] or PROVIDERS[s["provider"]].get("default", ""),
        "base_url": s["base_url"],
        "prices": s["prices"],
        "known_prices": ANTHROPIC_PRICES,
        "providers": [
            {
                "id": pid,
                "label": p["label"],
                "kind": p["kind"],
                "note": p.get("note"),
                "key_url": p.get("key_url"),
                "default": p.get("default", ""),
                "models": p["models"],
                "key": _mask(s["keys"][pid]) if s["keys"].get(pid) else None,
            }
            for pid, p in PROVIDERS.items()
        ],
    }


def save_settings(provider: str, model: str = "", key: str | None = None, clear_key: bool = False,
                  base_url: str | None = None, price_in: float | None = None, price_out: float | None = None) -> dict:
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider {provider}")
    s = load_settings()
    s["provider"] = provider
    s["model"] = model.strip()
    if base_url is not None:
        s["base_url"] = base_url.strip().rstrip("/")
    keys = dict(s["keys"])
    if clear_key:
        keys.pop(provider, None)
    elif key and key.strip():
        keys[provider] = key.strip()
    s["keys"] = keys
    if price_in is not None or price_out is not None:
        s["prices"] = {**s["prices"], provider: {"in": price_in, "out": price_out}}
    if PROVIDERS[provider]["kind"] != "cli":
        if not keys.get(provider):
            raise ValueError("Add an API key for this provider.")
        if not s["model"]:
            raise ValueError("Pick a model.")
        if provider == "custom" and not s["base_url"]:
            raise ValueError("Enter the provider's base URL.")
    _path().write_text(json.dumps(s, indent=1), encoding="utf-8")
    return public_settings()


def engine_label(s: dict | None = None) -> dict:
    s = s or load_settings()
    p = PROVIDERS[s["provider"]]
    model = s["model"] or p.get("default", "")
    ready = p["kind"] == "cli" or bool(s["keys"].get(s["provider"]))
    return {"provider": s["provider"], "model": model, "label": "Claude Code" if p["kind"] == "cli" else model, "ready": ready}


def _base_url(provider: str, s: dict, override: str | None = None) -> str:
    return (override or (s["base_url"] if provider == "custom" else PROVIDERS[provider].get("base_url", ""))).rstrip("/")


def _client(provider: str, key: str, base_url: str):
    kind = PROVIDERS[provider]["kind"]
    if kind == "anthropic":
        import anthropic

        return anthropic.Anthropic(api_key=key, max_retries=2, timeout=120)
    import openai

    return openai.OpenAI(api_key=key, base_url=base_url, max_retries=2, timeout=120)


def list_models(provider: str, key: str | None = None, base_url: str | None = None) -> list[str]:
    """The provider's live model list (needs a key)."""
    s = load_settings()
    key = (key or "").strip() or s["keys"].get(provider)
    if PROVIDERS[provider]["kind"] == "cli":
        return []
    if not key:
        raise ValueError("Enter the API key first.")
    client = _client(provider, key, _base_url(provider, s, base_url))
    try:
        if PROVIDERS[provider]["kind"] == "anthropic":
            ids = [m.id for m in client.models.list(limit=100)]
        else:
            ids = [m.id for m in client.models.list()]
    except Exception as err:  # noqa: BLE001 — shown to the admin as is
        raise ValueError(_api_error(err)) from err
    return sorted(set(ids))


def test(provider: str, model: str, key: str | None = None, base_url: str | None = None) -> dict:
    """One tiny request to prove the key and model work."""
    s = load_settings()
    key = (key or "").strip() or s["keys"].get(provider)
    if not key:
        return {"ok": False, "error": "Enter the API key first."}
    started = time.time()
    try:
        client = _client(provider, key, _base_url(provider, s, base_url))
        if PROVIDERS[provider]["kind"] == "anthropic":
            r = client.messages.create(model=model, max_tokens=256, messages=[{"role": "user", "content": "Reply with the single word OK."}])
            reply = " ".join(b.text for b in r.content if b.type == "text").strip()
        else:
            r = client.chat.completions.create(model=model, max_tokens=64, messages=[{"role": "user", "content": "Reply with the single word OK."}])
            reply = (r.choices[0].message.content or "").strip()
    except Exception as err:  # noqa: BLE001
        return {"ok": False, "error": _api_error(err)}
    return {"ok": True, "reply": reply[:80], "ms": round((time.time() - started) * 1000)}


def _api_error(err: Exception) -> str:
    name = type(err).__name__
    msg = getattr(err, "message", None) or str(err)
    if name == "AuthenticationError":
        return "The API key was rejected. Check it and try again."
    if name == "PermissionDeniedError":
        return "This API key isn't allowed to use that model."
    if name == "NotFoundError":
        return "That model wasn't found at this provider."
    if name == "RateLimitError":
        return "The provider is busy or the key hit its rate limit. Try again in a moment."
    if name == "APIConnectionError":
        return "Couldn't reach the provider. Check the internet connection or the base URL."
    return msg[:300]


# ---------- the tools ----------

TOOLS = [
    {
        "name": "read_transcript",
        "description": "The clip's transcript, phrase by phrase: `[start–end] speaker #first-last: text`. "
        "#first-last are indices into the words list. Read this first to find what the user means.",
        "schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_spec",
        "description": "Current clip spec as JSON. Without `fields` returns everything except `words` and `crop` "
        "(use find_words for words).",
        "schema": {"type": "object", "properties": {"fields": {"type": "array", "items": {"type": "string"}}}},
    },
    {
        "name": "find_words",
        "description": "Word timings as lines `#index start-end text` (~text~ = hidden, ✂ = already cut). "
        "Filter by source time and/or text.",
        "schema": {
            "type": "object",
            "properties": {
                "from_time": {"type": "number", "description": "source seconds"},
                "to_time": {"type": "number", "description": "source seconds"},
                "text": {"type": "string", "description": "words to look for"},
            },
        },
    },
    {
        "name": "update_spec",
        "description": "Change top-level spec fields. Object fields (captions, source, intro, music, progressBar) are "
        "merged with what's there; lists (cuts, effects, doubts) and other values are replaced; null clears "
        "intro or music. The change is validated before it's saved.",
        "schema": {"type": "object", "properties": {"changes": {"type": "object"}}, "required": ["changes"]},
    },
    {
        "name": "edit_words",
        "description": "Fix caption words by index: change text, hide (keeps audio) or emphasise. Never add or "
        "remove words: to replace N misheard words with fewer, put the new words on the first ones and hide the rest.",
        "schema": {
            "type": "object",
            "properties": {
                "edits": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "index": {"type": "integer"},
                            "text": {"type": "string"},
                            "hidden": {"type": "boolean"},
                            "emphasis": {"type": "boolean"},
                        },
                        "required": ["index"],
                    },
                }
            },
            "required": ["edits"],
        },
    },
    {
        "name": "add_items",
        "description": "Append to the `cuts` or `effects` list.",
        "schema": {
            "type": "object",
            "properties": {"field": {"type": "string", "enum": ["cuts", "effects"]}, "items": {"type": "array", "items": {"type": "object"}}},
            "required": ["field", "items"],
        },
    },
    {
        "name": "remove_items",
        "description": "Remove entries from the `cuts` or `effects` list by index (see get_spec).",
        "schema": {
            "type": "object",
            "properties": {"field": {"type": "string", "enum": ["cuts", "effects"]}, "indexes": {"type": "array", "items": {"type": "integer"}}},
            "required": ["field", "indexes"],
        },
    },
    {
        "name": "remove_dead_air",
        "description": "Find long pauses (and um/uh fillers if asked). apply=false only previews. "
        "natural keeps short sentence pauses; tight is snappier.",
        "schema": {
            "type": "object",
            "properties": {"mode": {"type": "string", "enum": ["natural", "tight"]}, "fillers": {"type": "boolean"}, "apply": {"type": "boolean"}},
            "required": ["apply"],
        },
    },
    {
        "name": "remove_stutters",
        "description": "Find repeated words, cut-off words and false starts (keeps deliberate repetition). apply=false only previews.",
        "schema": {"type": "object", "properties": {"fillers": {"type": "boolean"}, "apply": {"type": "boolean"}}, "required": ["apply"]},
    },
]

NOTES = {
    "read_transcript": "reading the transcript…",
    "get_spec": "reading the clip…",
    "find_words": "looking up words…",
    "update_spec": "editing the clip…",
    "edit_words": "fixing captions…",
    "add_items": "editing the clip…",
    "remove_items": "editing the clip…",
    "remove_dead_air": "finding dead air…",
    "remove_stutters": "finding stutters…",
}

MERGE_FIELDS = {"captions", "source", "intro", "music", "progressBar"}


class ClipTools:
    def __init__(self, job_dir: Path, clip: int, reason: str, save_spec: Callable[[dict, str], dict]) -> None:
        self.job_dir, self.clip, self.reason, self.save_spec = job_dir, clip, reason, save_spec
        self.changed = False

    def _spec(self) -> dict:
        spec = store.load(self.job_dir, self.clip)
        if spec is None:
            raise ValueError("This clip has no spec.")
        return spec

    def _save(self, spec: dict, what: str) -> str:
        try:
            saved = self.save_spec(spec, f"{self.reason} ({what})")
        except ValueError as err:
            return f"Not saved, the change is invalid: {err}. Fix it and try again."
        self.changed = True
        return f"Saved ({what}). Version {store.history(self.job_dir, self.clip)[-1]['version']}. Cuts: {len(saved.get('cuts', []))}, effects: {len(saved.get('effects', []))}."

    def run(self, name: str, args: dict) -> tuple[str, bool]:
        try:
            fn = getattr(self, f"t_{name}", None)
            if fn is None:
                return f"Unknown tool {name}.", True
            return fn(**(args or {})), False
        except TypeError as err:
            return f"Bad arguments for {name}: {err}", True
        except Exception as err:  # noqa: BLE001 — the model sees the problem and can recover
            return f"{name} failed: {err}", True

    def t_read_transcript(self) -> str:
        from ..spec.transcript import render

        return render(self.job_dir, self._spec())

    def t_get_spec(self, fields: list[str] | None = None) -> str:
        spec = self._spec()
        if fields:
            out = {k: spec.get(k) for k in fields}
        else:
            out = {k: v for k, v in spec.items() if k not in ("words", "crop")}
            out["words"] = f"{len(spec.get('words', []))} words (use find_words)"
            out["crop"] = f"{len(spec.get('crop', {}).get('keyframes', []))} camera keyframes"
        return json.dumps(out, ensure_ascii=False)

    def t_find_words(self, from_time: float | None = None, to_time: float | None = None, text: str | None = None) -> str:
        spec = self._spec()
        words, cuts = spec.get("words", []), spec.get("cuts", [])
        t0 = from_time if from_time is not None else spec["source"]["start"]
        t1 = to_time if to_time is not None else spec["source"]["end"]
        rows = [i for i, w in enumerate(words) if w["end"] > t0 and w["start"] < t1]
        if text:
            from ..spec.glossary import norm

            needle = norm(text)
            hits = [i for i in rows if needle in norm(" ".join(x["text"] for x in words[i : i + len(needle.split())]))]
            rows = sorted({j for i in hits for j in range(max(0, i - 6), min(len(words), i + 10))})
        lines = []
        for i in rows[:400]:
            w = words[i]
            mid = (w["start"] + w["end"]) / 2
            shown = f"~{w['text']}~" if w.get("hidden") else w["text"]
            mark = " ✂" if any(c["start"] <= mid < c["end"] for c in cuts) else ""
            lines.append(f"#{i} {w['start']:.2f}-{w['end']:.2f} {shown}{mark}")
        return "\n".join(lines) or "No words match."

    def t_update_spec(self, changes: dict) -> str:
        spec = self._spec()
        for key, value in changes.items():
            if key == "words":
                return "Use edit_words to change words."
            if key in MERGE_FIELDS and isinstance(value, dict) and isinstance(spec.get(key), dict):
                spec[key] = {**spec[key], **value}
            else:
                spec[key] = value
        return self._save(spec, "set " + ", ".join(changes))

    def t_edit_words(self, edits: list[dict]) -> str:
        spec = self._spec()
        words = spec["words"]
        for e in edits:
            i = int(e["index"])
            if not 0 <= i < len(words):
                return f"No word #{i} (there are {len(words)})."
            for field in ("text", "hidden", "emphasis"):
                if field in e:
                    words[i][field] = e[field]
        return self._save(spec, f"{len(edits)} caption fixes")

    def t_add_items(self, field: str, items: list[dict]) -> str:
        spec = self._spec()
        spec[field] = [*spec.get(field, []), *items]
        if field == "cuts":
            spec[field].sort(key=lambda c: c.get("start", 0))
        return self._save(spec, f"add {len(items)} {field}")

    def t_remove_items(self, field: str, indexes: list[int]) -> str:
        spec = self._spec()
        drop = set(indexes)
        spec[field] = [x for i, x in enumerate(spec.get(field, [])) if i not in drop]
        return self._save(spec, f"remove {len(drop)} {field}")

    def t_remove_dead_air(self, apply: bool, mode: str = "natural", fillers: bool = False) -> str:
        from ..spec import silence

        spec = self._spec()
        found = silence.find(spec, self.job_dir, mode, fillers)
        summary = f"{len(found['cuts'])} pauses, {len(found['filler_words'])} fillers, -{found['saved']:.1f}s"
        if not apply or not (found["cuts"] or found["filler_words"]):
            return f"Preview: {summary}." if found["cuts"] or found["filler_words"] else "Nothing to cut."
        return self._save(silence.apply(spec, found), f"dead air {mode}: {summary}")

    def t_remove_stutters(self, apply: bool, fillers: bool = False) -> str:
        from ..spec import stutters

        spec = self._spec()
        found = stutters.find(spec, fillers)
        if not found["removals"]:
            return "No stutters found."
        listing = "; ".join(f"{r['kind']} '{r['text']}'" for r in found["removals"][:12])
        if not apply:
            return f"Preview: {len(found['removals'])} found, -{found['saved']:.1f}s: {listing}"
        return self._save(stutters.apply(spec, found), f"stutters: {len(found['removals'])}")


SYSTEM = """You edit ONE vertical (9:16) video clip in tetclipper Studio. The user watches a live
preview; every edit you save shows up instantly. You change the clip only through the tools.

Clip: "{title}" (job {job_id}, clip {clip}).

The spec (all times are SOURCE seconds, positions in the media file):
- source {{src, start, end}}: the clip range. Widen or narrow it by changing start/end.
- intro: null or {{src, duration 0.5–5, fit cover|contain}}, a full-screen still before the clip.
- music: null or {{src, volume 0–1, duck 0–1, offset, fadeIn, fadeOut, loop}}.
- cuts [{{start, end}}]: spans removed from the clip. Snap to word boundaries so nothing is clipped.
- words [{{text, start, end, emphasis?, hidden?}}]: the captions. Fix with edit_words. hidden removes a
  word from the captions only; the audio stays.
- doubts [{{from, to, reason, alt?}}]: caption spans the speech model may have misheard (word indexes).
  `alt` is what a Swahili second listen heard. The speaker mixes English, Swahili and Sheng; the English
  model often writes Swahili as English-sounding nonsense ("able to show me" for "ebu tusome"). Pick the
  reading that makes sense; if neither does, don't invent words, tell the user the time to listen to.
- captions {{enabled, style, position 0–1 (0.7 ≈ lower third), maxWords 1–8, size, color, activeColor,
  emphasisColor, uppercase, emoji}}. Styles: classic, beast, hormozi, minimal, karaoke-pop, sermon,
  one-word, boxed, neon.
- effects: each has `type`, `at` (source seconds) and `duration`. Camera: punch-in {{amount 1–2}},
  digital-zoom {{amount}}, vertigo {{amount}}, pull-back {{from, to}}, zoom-through, shake {{intensity}}, flash.
  Graphics: hook {{text, background?, color?}} (title card), checklist {{title?, items[]}},
  headline-wall {{headlines[], look news|scripture}}, chart {{kind bar|line, labels[], values[]}},
  glass-text {{text, subtitle?}}, emoji {{emoji, x?, y?}}. Styles: phone, ui-cards, paper-text, doodle, orbit.
  Behind the speaker (needs `matte`; if it's null tell the user to press "Cut out speaker" in Effects):
  wall-text, frame-break, background {{mode blur|color|image}}, cover.
  Keep graphics short (2–6 s) and use the speaker's own words for text.
- progressBar {{enabled, color}}.

Rules:
- Look before you edit: read_transcript or find_words to locate what the user means.
- Keep edits minimal. Don't invent words that weren't said; caption fixes are for clear mishearings.
- If a save is rejected, read the problems and fix the change.
- If asked for something the spec can't do (voice changes, new footage), say so briefly.
- The user renders with the Render button; you don't render.
- Reply in short plain text, no headings: say what you changed, with times as m:ss.
"""

MAX_STEPS = 12


def _price(provider: str, model: str, s: dict) -> tuple[float, float] | None:
    if PROVIDERS[provider]["kind"] == "anthropic":
        return ANTHROPIC_PRICES.get(model)
    p = s["prices"].get(provider) or {}
    if p.get("in") is None or p.get("out") is None:
        return None
    return float(p["in"]), float(p["out"])


def run_turn(job_dir: Path, clip: int, title: str, prompt: str, history: list[dict],
             emit: Callable[..., None], save_spec: Callable[[dict, str], dict]) -> tuple[list[str], str | None, dict]:
    """One user message: loop the model and its tools until it answers.
    Returns (replies, error, meta with model, tokens and cost)."""
    s = load_settings()
    provider = s["provider"]
    p = PROVIDERS[provider]
    model = s["model"] or p.get("default", "")
    key = s["keys"].get(provider)
    if not key:
        return [], "No API key is set for the AI provider. The admin can add one under AI model.", {}
    system = SYSTEM.format(title=title or job_dir.name, job_id=job_dir.name, clip=clip)
    tools = ClipTools(job_dir, clip, f"claude: {prompt.splitlines()[-1][:50]}", save_spec)
    usage = {"in": 0, "out": 0, "cache_write": 0, "cache_read": 0}
    replies: list[str] = []
    error: str | None = None

    try:
        client = _client(provider, key, _base_url(provider, s))
        if p["kind"] == "anthropic":
            error = _loop_anthropic(client, model, system, history, prompt, tools, emit, replies, usage)
        else:
            error = _loop_openai(client, model, system, history, prompt, tools, emit, replies, usage)
    except Exception as err:  # noqa: BLE001
        error = _api_error(err)

    price = _price(provider, model, s)
    cost = None
    if price:
        cin, cout = price
        cost = ((usage["in"] + usage["cache_write"] * 1.25 + usage["cache_read"] * 0.1) * cin + usage["out"] * cout) / 1e6
    return replies, error, {"model": model, "provider": provider, "tokens": usage, "cost": cost}


def _loop_anthropic(client, model, system, history, prompt, tools: ClipTools, emit, replies, usage) -> str | None:
    import anthropic

    defs = [{"name": t["name"], "description": t["description"], "input_schema": t["schema"]} for t in TOOLS]
    messages: list[dict] = [*({"role": m["role"], "content": m["text"]} for m in history), {"role": "user", "content": prompt}]
    for _ in range(MAX_STEPS):
        kwargs: dict[str, Any] = dict(model=model, max_tokens=8000, system=system, tools=defs, messages=messages,
                                      cache_control={"type": "ephemeral"})
        if model in EFFORT_MODELS:
            kwargs["output_config"] = {"effort": "medium"}
        try:
            if model in FALLBACK_MODELS:
                resp = client.beta.messages.create(**kwargs, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
            else:
                resp = client.messages.create(**kwargs)
        except anthropic.APIError as err:
            return _api_error(err)
        u = resp.usage
        usage["in"] += u.input_tokens or 0
        usage["out"] += u.output_tokens or 0
        usage["cache_write"] += getattr(u, "cache_creation_input_tokens", 0) or 0
        usage["cache_read"] += getattr(u, "cache_read_input_tokens", 0) or 0
        for b in resp.content:
            if b.type == "text" and b.text.strip():
                replies.append(b.text.strip())
                emit("text", text=b.text.strip())
        if resp.stop_reason == "refusal":
            return "Claude declined this request."
        if resp.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": resp.content})
            continue
        calls = [b for b in resp.content if b.type == "tool_use"]
        if not calls:
            return "The reply was cut off (too long)." if resp.stop_reason == "max_tokens" else None
        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for c in calls:
            emit("tool", text=NOTES.get(c.name, "working…"))
            out, failed = tools.run(c.name, c.input)
            results.append({"type": "tool_result", "tool_use_id": c.id, "content": out, **({"is_error": True} if failed else {})})
        messages.append({"role": "user", "content": results})
    return "Stopped after too many steps. Try a smaller request."


def _loop_openai(client, model, system, history, prompt, tools: ClipTools, emit, replies, usage) -> str | None:
    import openai

    defs = [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["schema"]}} for t in TOOLS]
    messages: list[dict] = [
        {"role": "system", "content": system},
        *({"role": m["role"], "content": m["text"]} for m in history),
        {"role": "user", "content": prompt},
    ]
    for _ in range(MAX_STEPS):
        try:
            resp = client.chat.completions.create(model=model, messages=messages, tools=defs, max_tokens=4096)
        except openai.BadRequestError as err:
            msg = _api_error(err)
            return f"{msg} (If this model can't use tools, pick another one.)" if "tool" in msg.lower() else msg
        except openai.APIError as err:
            return _api_error(err)
        if resp.usage:
            usage["in"] += resp.usage.prompt_tokens or 0
            usage["out"] += resp.usage.completion_tokens or 0
        msg = resp.choices[0].message
        if msg.content and msg.content.strip():
            replies.append(msg.content.strip())
            emit("text", text=msg.content.strip())
        calls = msg.tool_calls or []
        if not calls:
            return "The reply was cut off (too long)." if resp.choices[0].finish_reason == "length" else None
        # Only role, content and tool_calls go back: some providers reject their own reasoning fields.
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [{"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments}} for c in calls],
        })
        for c in calls:
            emit("tool", text=NOTES.get(c.function.name, "working…"))
            try:
                args = json.loads(c.function.arguments or "{}")
            except ValueError:
                out, _ = "The arguments weren't valid JSON. Try again.", True
            else:
                out, _ = tools.run(c.function.name, args)
            messages.append({"role": "tool", "tool_call_id": c.id, "content": out})
    return "Stopped after too many steps. Try a smaller request."
