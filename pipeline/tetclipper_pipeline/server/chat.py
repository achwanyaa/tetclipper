"""Chat with Claude Code about one job: "cut 12:30-13:15 with beast captions".

Each message runs the user's own `claude` CLI headless (their Claude plan, no
API key) in the pipeline directory, allowed to run only a few `tetclipper`
commands. The session id is kept per job, so the conversation continues.
Replies stream to the UI as {"event": "chat", ...} on the same event channel
as pipeline progress. Only works where the CLI is installed and logged in, i.e.
the local app, not the hosted deployment.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

PIPELINE_DIR = Path(__file__).resolve().parents[2]
MAX_TURNS = 20

ALLOWED_TOOLS = [
    "Bash(uv run tetclipper edit text:*)",
    "Bash(uv run tetclipper edit add-range:*)",
    "Bash(uv run tetclipper telegram send:*)",
]

PROMPT = """You are the clip editor inside tetclipper, replying in the app's chat panel.
The user is talking about one video: job {job_id}, "{title}", {duration} long.

You work only through these commands (Bash tool, current directory):
- uv run tetclipper edit text {job_id} [--start S] [--end S] [--find WORD]
    Transcript lines "[m:ss.s-m:ss.s] S0: text" (S = speaker). Read windows or
    search; avoid dumping the whole video unless you need it.
- uv run tetclipper edit add-range {job_id} START END [--captions STYLE] [--camera MODE]
    Cuts and renders a vertical 9:16 clip: speaker-tracked camera, word-by-word
    captions with loud-word emphasis. START/END are source seconds, 3-600 s long
    (over 180 s won't upload to Shorts/Reels; mention that if the user goes longer).
    STYLE: classic | beast | hormozi | minimal | karaoke-pop (default: the job's).
    MODE: cut (hard cut on speaker change) | pan (smooth) | locked.
    Slow (minutes): ALWAYS pass timeout 600000 to the Bash tool. The last output
    line is JSON: {{"ok": true, "output": {{"clip": N, "path": ..., "duration": ...}}}}.
- uv run tetclipper telegram send {job_id} CLIP --caption "..."
    Sends clip CLIP to the user's Telegram. Clips over 50 MB are saved to a
    folder instead; tell the user the path it prints.

Rules:
- Times like 12:30 mean minutes:seconds in the source video (1:02:03 = h:m:s).
- Before cutting, read the transcript around the range and snap START/END to
  sentence boundaries so nothing starts or ends mid-word. Say the exact range.
- If the request is vague (which moment? how long?), find candidates in the
  transcript, propose one or two ranges and ask before cutting; cutting is slow.
- Only those caption styles and camera modes exist. If asked for music, b-roll,
  zooms or other effects, say they aren't available from chat yet.
- Send to Telegram only when asked.
- Replies: short plain text, no markdown headings. After a cut, give the clip
  number, its length and range."""


def _claude() -> str | None:
    found = os.environ.get("TETCLIPPER_CLAUDE") or shutil.which("claude")
    if found and found.lower().endswith(".cmd"):
        # npm's Windows shim; call the real binary so cmd.exe never re-parses
        # our arguments (quotes, newlines and & would break).
        exe = Path(found).parent / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
        if exe.exists():
            return str(exe)
    return found


def available() -> bool:
    return _claude() is not None


def _store(job_dir: Path) -> Path:
    return job_dir / "chat.json"


def history(job_dir: Path) -> dict:
    try:
        return json.loads(_store(job_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"session_id": None, "messages": []}


def _save(job_dir: Path, data: dict) -> None:
    _store(job_dir).write_text(json.dumps(data, indent=1), encoding="utf-8")


def reset(job_dir: Path) -> None:
    _store(job_dir).unlink(missing_ok=True)


def _fmt(t: float) -> str:
    return f"{int(t // 60)}:{int(t % 60):02d}"


def _tool_note(block: dict) -> str:
    """One readable line for a tool call, shown greyed in the chat."""
    cmd = (block.get("input") or {}).get("command", "")
    if " edit text " in cmd:
        return "reading the transcript…"
    if " edit add-range " in cmd:
        parts = cmd.split()
        try:
            i = parts.index("add-range")
            a, b = float(parts[i + 2]), float(parts[i + 3])
            return f"cutting {_fmt(a)}–{_fmt(b)} (takes a few minutes)…"
        except (ValueError, IndexError):
            return "cutting the clip…"
    if " telegram send " in cmd:
        return "sending to Telegram…"
    return f"running {block.get('name', 'a tool')}…"


_busy: set[str] = set()
_lock = threading.Lock()


def send(job_dir: Path, meta: dict, message: str, publish: Callable[[dict], None]) -> None:
    """Start one chat turn on a thread; everything comes back via publish()."""
    job_id = job_dir.name
    claude = _claude()
    if claude is None:
        raise RuntimeError(
            "Chat needs the Claude Code CLI logged in on this machine; use the local app (tetclipper serve)."
        )
    with _lock:
        if job_id in _busy:
            raise RuntimeError("Claude is still working on the last message for this video.")
        _busy.add(job_id)

    data = history(job_dir)
    data["messages"].append({"role": "user", "text": message, "ts": time.time()})
    _save(job_dir, data)

    prompt = PROMPT.format(
        job_id=job_id, title=meta.get("title") or job_id, duration=_fmt(float(meta.get("duration") or 0))
    )
    args = [
        claude, "-p",
        "--output-format", "stream-json", "--verbose",
        "--append-system-prompt", prompt,
        "--max-turns", str(MAX_TURNS),
        "--allowedTools", *ALLOWED_TOOLS,
    ]
    if data.get("session_id"):
        args += ["--resume", data["session_id"]]

    def emit(kind: str, **fields) -> None:
        publish({"event": "chat", "job_id": job_id, "kind": kind, **fields})

    def work() -> None:
        session_id = data.get("session_id")
        replies: list[str] = []
        error: str | None = None
        try:
            child = subprocess.Popen(
                args, cwd=PIPELINE_DIR, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace",
                creationflags=0x08000000 if sys.platform == "win32" else 0,
            )
            assert child.stdin is not None and child.stdout is not None
            child.stdin.write(message)  # the user's words go in on stdin, never argv
            child.stdin.close()
            for line in child.stdout:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                session_id = ev.get("session_id") or session_id
                if ev.get("type") == "assistant":
                    for block in (ev.get("message") or {}).get("content", []):
                        if block.get("type") == "text" and block.get("text", "").strip():
                            replies.append(block["text"].strip())
                            emit("text", text=block["text"].strip())
                        elif block.get("type") == "tool_use":
                            emit("tool", text=_tool_note(block))
                elif ev.get("type") == "result" and ev.get("is_error"):
                    error = ev.get("result") or ev.get("subtype") or "Claude stopped with an error."
            code = child.wait()
            if code != 0 and not replies and error is None:
                err = (child.stderr.read() if child.stderr else "")[-400:]
                error = err.strip() or f"claude exited with code {code}"
        except OSError as exc:
            error = f"Couldn't start Claude Code: {exc}"
        finally:
            latest = history(job_dir)
            latest["session_id"] = session_id
            if replies:
                latest["messages"].append({"role": "assistant", "text": "\n\n".join(replies), "ts": time.time()})
            if error:
                latest["messages"].append({"role": "error", "text": error, "ts": time.time()})
            _save(job_dir, latest)
            with _lock:
                _busy.discard(job_id)
            emit("done", error=error)

    threading.Thread(target=work, daemon=True).start()
