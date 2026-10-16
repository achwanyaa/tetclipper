"""Studio chat: Claude Code edits one clip's spec.json while the user watches.

Each message runs the user's own `claude` CLI headless (their Claude plan, no
API key) with the clip's folder (jobs/<id>/studio/clip_NN/) as its working
directory. It may read anything there but only edit spec.json, plus run
`tetclipper spec validate`. The editor previews spec.json live: a watcher in
server/studio.py publishes every valid change while the turn is running, and
at the end of the turn the spec is validated — an invalid edit is rolled back
and Claude gets one automatic chance to fix it.

Replies stream as {"event": "studio-chat", job_id, clip, kind: text|delta|tool|done}.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

from ..spec import store
from .chat import _claude

PIPELINE_DIR = Path(__file__).resolve().parents[2]
MAX_TURNS = 30
ALLOWED_TOOLS = [
    "Read",
    "Grep",
    "Edit(./spec.json)",
    "Write(./spec.json)",
    "Bash(uv run tetclipper spec validate:*)",
    "Bash(uv run tetclipper spec show:*)",
    "Bash(uv run tetclipper audio list:*)",
    "Bash(uv run tetclipper spec dead-air:*)",
    "Bash(uv run tetclipper spec stutters:*)",
    "Bash(uv run tetclipper spec words:*)",
]
# With "Let Claude run scripts" on (Studio chat panel; off by default): write
# helper scripts under ./scripts/ and run them. This runs arbitrary code on
# the user's PC, so it is the user's explicit choice.
SCRIPT_TOOLS = [
    "Write(./scripts/**)",
    "Edit(./scripts/**)",
    "Bash(uv run python:*)",
    "Bash(python:*)",
    "Bash(node:*)",
]

GUIDE = """# Studio clip editor

You are editing ONE vertical (9:16) clip in tetclipper Studio. The user watches
a live preview of `spec.json` next to this chat; every valid save shows up
instantly. You change the video ONLY by editing `spec.json` in this folder.

Job {job_id}, clip {clip}: "{title}".

## Files here
- `spec.json` — the clip. Edit it with the Edit tool (small, targeted edits).
- `transcript.md` — phrase-by-phrase view: `[start–end] speaker #i-j: text`.
  `#i-j` are indices into `spec.json` → `words`. Read this first to find things.
- `assets/` — images and audio the user uploaded (intro photos, b-roll, music). Reference them
  as `studio/clip_{clip:02d}/assets/<name>` (paths are relative to the job dir).

## The spec (all times are SOURCE seconds — positions in the media file)
- `source`: `{{src, start, end, width, height}}` — the clip range. Widen/narrow
  by changing start/end (stay inside the media; the analysis covers it).
- `intro`: `null` or `{{src, duration: 0.5–5, fit: "cover"|"contain"}}` — a
  full-screen still before the clip.
- `music`: `null` or `{{src, volume: 0–1, duck: 0–1, offset, fadeIn, fadeOut, loop}}`
  — a music bed under the whole clip; `duck` multiplies the volume while anyone
  speaks (0.35 = speech stays clear). Tracks the user added live in `assets/`;
  the user's music library is listed by `uv run tetclipper audio list --kind music`
  (copy a track into assets by asking the user to pick it in the Music tab).
- To read word timings without opening the big spec, run
  `uv run tetclipper spec words {job_id} --clip {clip} [--from S --to S] [--find TEXT]`
  → `#index start-end text` per word (~hidden~, ✂ = already cut).
- To edit out stutters, repeated words and false starts, run
  `uv run tetclipper spec stutters {job_id} --clip {clip} [--fillers] --apply`
  (without --apply it only lists them). It keeps deliberate repetition
  ("Choose life. Choose life."). The transcript may have tidied some stutters
  away, so for ones the user points at, find the words with `spec words` and
  cut them yourself (hide the words + add a cut ending just before the kept word).
{scripts_note}
- To remove silences / dead air, run
  `uv run tetclipper spec dead-air {job_id} --clip {clip} [--mode natural|tight] [--fillers] --apply`
  (without --apply it only previews). natural keeps short sentence pauses,
  tight is snappier; both keep pauses near laughter. Report cuts and seconds saved.
- `cuts`: `[{{start, end}}]` — spans removed from the middle of the clip. Snap
  to word boundaries (word.start / previous word.end) so nothing is clipped.
- `words`: `[{{text, start, end, emphasis?, hidden?, speaker?}}]` — captions.
  Fix a misheard word by changing `text`. NEVER add or remove entries in
  `words`: to replace N misheard words with fewer, put the new words on the
  first ones and set `hidden: true` on the rest (you may spread start/end over
  the span). `hidden: true` removes a word from captions only (audio stays).
  `emphasis: true` = highlighted colour. Every fix is learned automatically and
  applied to future clips.
- `doubts`: `[{{from, to, reason, alt?}}]` — caption spans the speech model may
  have misheard (listed under "To check" in transcript.md). `alt` is what a
  second listen with the model forced to Swahili heard. The speaker mixes
  English, Swahili and Sheng mid-sentence: the English model often writes
  Swahili as English-sounding nonsense ("able to show me" for "ebu tusome").
  Use your Swahili/Sheng knowledge and the context to pick the reading that
  makes sense; if neither does, don't invent words — tell the user the time
  (m:ss) to listen to. Fixing a span's words resolves its doubt.
- `captions`: `{{enabled, style, position?, maxWords?, size?, color?,
  activeColor?, emphasisColor?, uppercase?, emoji?}}`
  - style: classic | beast | hormozi | minimal | karaoke-pop | sermon |
    one-word | boxed | neon
  - position: 0–1 vertical centre (0.7 ≈ lower third). maxWords: 1–8 per line.
- `crop.keyframes`: `[{{t, x, y, zoom, cut?}}]` — the smart-camera path (x/y =
  crop centre as a fraction of the source frame, zoom ≥ 1). Usually leave it;
  to re-frame a moment, adjust the keyframes around that time.
- `effects`: list of timed effects; every one has `at` (source seconds) and `duration`:
  - camera: `punch-in {{amount 1–2}}`, `digital-zoom {{amount}}` (hard zoom + glitch),
    `vertigo {{amount}}` (dolly zoom), `pull-back {{from 1–4, to 0.5–1}}` (to<1 ends on a
    framed card), `zoom-through` (transition — set `at` to the start of the part after
    a cut), `shake {{intensity}}`, `flash`
  - graphics: `checklist {{title?, items[], ticks[]? (source s per item), y?, accent?}}`,
    `headline-wall {{headlines[], look: news|scripture}}`,
    `chart {{kind: bar|line, title?, labels[], values[], unit?, color?, y?}}`,
    `glass-text {{text, subtitle?, y?}}`, `hook {{text, background?, color?}}`,
    `emoji {{emoji, x?, y?, size?}}`, `image {{src, layout: full|top}}`
  - styles: `phone {{tilt?, background?}}`, `ui-cards {{cards: [{{kind: notification|like|comment|verse, title, text?}}]}}`,
    `paper-text {{text, color?, y?}}`, `doodle {{shape: arrow|circle|underline|star|heart|sparkle, x, y, size?, rotation?, color?}}`,
    `orbit {{items[] (words/emoji), x?, y?, radius?}}`
  - behind the speaker (need the speaker cut out — `matte` in the spec; if `matte` is
    null tell the user to press "Cut out speaker" in the Effects tab):
    `wall-text {{text, color?, y?}}`, `frame-break {{color?}}`,
    `background {{mode: blur|color|image, color?, src?}}` (green screen),
    `cover {{title, lines[], issue?, color?}}` (magazine cover)
  - x/y are fractions of the frame (0–1). Use the speaker's words for text; keep
    graphics short (2–6 s) and don't stack many at once.
- `progressBar`: `{{enabled, color}}`

## Rules
- After editing, run `uv run tetclipper spec validate {job_id} --clip {clip}`.
  If it reports problems, it has restored the last good version: fix and retry.
- Keep edits minimal; don't rewrite the whole file or drop fields you don't touch.
- Don't invent words that weren't said. Caption fixes = obvious mishearings only.
- If asked for something the spec can't express (voice changes, new footage,
  sound effects), say so briefly.
- The user renders with the Render button; you don't render.
- Replies: short plain text, no headings. Say what you changed, with times as m:ss.
"""


def _fmt(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:04.1f}"


SCRIPTS_ON = """- You may write helper scripts in ./scripts/ and run them with `uv run python
  scripts/<name>.py` (numpy is available) — e.g. to compute cuts from word
  timings. Scripts may read anything here but must change the clip only by
  writing spec.json; always run `spec validate` afterwards."""
SCRIPTS_OFF = """- You can't run scripts in this session (the user hasn't allowed it). Use the
  commands above; if a task really needs a script, say so — the user can turn
  on "Let Claude run scripts" in the chat panel."""


def write_guide(job_dir: Path, clip: int, title: str, allow_scripts: bool = False) -> Path:
    path = store.clip_dir(job_dir, clip) / "CLAUDE.md"
    path.write_text(GUIDE.format(job_id=job_dir.name, clip=clip, title=title or job_dir.name,
                                 scripts_note=SCRIPTS_ON if allow_scripts else SCRIPTS_OFF), encoding="utf-8")
    return path


def _chat_file(job_dir: Path, clip: int) -> Path:
    return store.clip_dir(job_dir, clip) / "chat.json"


def history(job_dir: Path, clip: int) -> dict:
    try:
        return json.loads(_chat_file(job_dir, clip).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"session_id": None, "messages": []}


def _save(job_dir: Path, clip: int, data: dict) -> None:
    _chat_file(job_dir, clip).write_text(json.dumps(data, indent=1), encoding="utf-8")


def reset(job_dir: Path, clip: int) -> None:
    _chat_file(job_dir, clip).unlink(missing_ok=True)


def _tool_note(block: dict) -> str:
    name = block.get("name", "")
    inp = block.get("input") or {}
    if name in ("Edit", "Write", "MultiEdit"):
        return "editing the clip…"
    if name == "Read":
        f = str(inp.get("file_path", ""))
        return "reading the transcript…" if f.endswith("transcript.md") else "reading the spec…"
    if name == "Bash" and "validate" in str(inp.get("command", "")):
        return "checking the edit…"
    return f"{name or 'working'}…"


def context_line(ctx: dict | None) -> str:
    """What the user is looking at, prepended to their message."""
    if not ctx:
        return ""
    bits = []
    if ctx.get("playhead") is not None:
        bits.append(f"playhead at source {float(ctx['playhead']):.2f}s ({_fmt(float(ctx['playhead']))})")
    if ctx.get("selection"):
        a, b = ctx["selection"]
        bits.append(f"selected words #{a}-{b}")
    return f"[editor: {', '.join(bits)}]\n" if bits else ""


_busy: set[str] = set()
_lock = threading.Lock()


def busy(job_dir: Path, clip: int) -> bool:
    return f"{job_dir.name}/{clip}" in _busy


def send(job_dir: Path, clip: int, title: str, message: str, ctx: dict | None,
         publish: Callable[[dict], None], on_turn_end: Callable[[], list[str]], allow_scripts: bool = False) -> None:
    """Start one chat turn on a thread. `on_turn_end` validates the spec and
    returns problems (it restores the last good version itself)."""
    key = f"{job_dir.name}/{clip}"
    claude = _claude()
    if claude is None:
        raise RuntimeError("Studio chat needs the Claude Code CLI installed and logged in on this machine.")
    with _lock:
        if key in _busy:
            raise RuntimeError("Claude is still working on the last message.")
        _busy.add(key)

    cwd = store.clip_dir(job_dir, clip)
    write_guide(job_dir, clip, title, allow_scripts)
    tools = [*ALLOWED_TOOLS, *(SCRIPT_TOOLS if allow_scripts else [])]
    data = history(job_dir, clip)
    data["messages"].append({"role": "user", "text": message, "ts": time.time()})
    _save(job_dir, clip, data)

    def emit(kind: str, **fields) -> None:
        publish({"event": "studio-chat", "job_id": job_dir.name, "clip": clip, "kind": kind, **fields})

    def run_turn(prompt: str, session_id: str | None) -> tuple[str | None, list[str], str | None]:
        args = [
            claude, "-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
            "--max-turns", str(MAX_TURNS), "--allowedTools", *tools,
        ]
        if session_id:
            args += ["--resume", session_id]
        replies: list[str] = []
        error: str | None = None
        env = {**os.environ, "UV_PROJECT": str(PIPELINE_DIR)}
        child = subprocess.Popen(
            args, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
            creationflags=0x08000000 if sys.platform == "win32" else 0,
        )
        assert child.stdin is not None and child.stdout is not None
        child.stdin.write(prompt)  # the user's words go in on stdin, never argv
        child.stdin.close()
        for line in child.stdout:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            session_id = ev.get("session_id") or session_id
            kind = ev.get("type")
            if kind == "stream_event":
                delta = ((ev.get("event") or {}).get("delta") or {})
                if delta.get("type") == "text_delta" and delta.get("text"):
                    emit("delta", text=delta["text"])
            elif kind == "assistant":
                for block in (ev.get("message") or {}).get("content", []):
                    if block.get("type") == "text" and block.get("text", "").strip():
                        replies.append(block["text"].strip())
                        emit("text", text=block["text"].strip())
                    elif block.get("type") == "tool_use":
                        emit("tool", text=_tool_note(block))
            elif kind == "result" and ev.get("is_error"):
                error = ev.get("result") or ev.get("subtype") or "Claude stopped with an error."
        code = child.wait()
        if code != 0 and not replies and error is None:
            err = (child.stderr.read() if child.stderr else "")[-400:]
            error = err.strip() or f"claude exited with code {code}"
        return session_id, replies, error

    def work() -> None:
        session_id = data.get("session_id")
        replies: list[str] = []
        error: str | None = None
        try:
            session_id, replies, error = run_turn(context_line(ctx) + message, session_id)
            problems = on_turn_end()
            if problems and not error:
                # One automatic repair round: Claude sees exactly what was wrong.
                emit("tool", text="fixing an invalid edit…")
                fix = (
                    "Your last edit made spec.json invalid, so it was restored to the previous version. "
                    "Problems:\n- " + "\n- ".join(problems[:10]) + "\nRe-apply the change correctly."
                )
                session_id, more, error = run_turn(fix, session_id)
                replies += more
                problems = on_turn_end()
                if problems:
                    error = "The edit didn't validate and was undone: " + "; ".join(problems[:3])
        except OSError as exc:
            error = f"Couldn't start Claude Code: {exc}"
        finally:
            latest = history(job_dir, clip)
            latest["session_id"] = session_id
            if replies:
                latest["messages"].append({"role": "assistant", "text": "\n\n".join(replies), "ts": time.time()})
            if error:
                latest["messages"].append({"role": "error", "text": error, "ts": time.time()})
            _save(job_dir, clip, latest)
            with _lock:
                _busy.discard(key)
            emit("done", error=error)

    threading.Thread(target=work, daemon=True).start()
