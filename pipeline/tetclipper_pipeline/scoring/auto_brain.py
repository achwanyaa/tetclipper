"""Answer a paused job's brain_request.json with a headless Claude Code run.

Runs `claude -p` in the job folder: read the prompts (`brain show`), write one
answers file, store it (`brain answer`) until nothing is missing. Uses the
user's own Claude plan; no API key.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

from . import brain

PIPELINE_DIR = Path(__file__).resolve().parents[2]
RULES = Path(__file__).with_name("judging.md")
ANSWERS = "brain_answers.json"
ALLOWED_TOOLS = [
    "Read",
    f"Write(./{ANSWERS})",
    f"Edit(./{ANSWERS})",
    "Bash(uv run tetclipper brain show:*)",
    "Bash(uv run tetclipper brain answer:*)",
]


def _judging_rules() -> str:
    """The calibration the scores rely on (scoring/judging.md)."""
    try:
        text = RULES.read_text(encoding="utf-8")
    except OSError:
        return ""
    i = text.find("## Judging moments")
    return text[i:] if i >= 0 else text


def prompt(job_id: str) -> str:
    return f"""You are tetclipper's scoring brain for job {job_id}. The job is paused
waiting for your answers; nobody is watching this run, so don't ask questions.

1. Run `uv run tetclipper brain show {job_id}` to read every pending prompt.
2. Answer every item following its schema exactly. Write ONE JSON file,
   `{ANSWERS}` in the current folder: {{"<id>": {{...answer...}}, ...}}.
3. Run `uv run tetclipper brain answer {job_id} {ANSWERS}`. It prints
   {{"written", "missing", "errors"}}. Fix the file and re-run until missing and
   errors are both empty.
4. Reply with one line: how many items you scored.

{_judging_rules()}"""


def answer(job_dir: Path, emit: Callable[[float, str], None]) -> None:
    """Run Claude Code until the job's pending brain request is answered."""
    from ..server.studio_chat import find_claude as _claude

    job_dir = Path(job_dir)
    request = brain.load_request(job_dir)
    if not request:
        return
    claude = _claude()
    if claude is None:
        raise RuntimeError("Finding moments needs the Claude Code CLI logged in on this machine.")
    count = len(request.get("items", request.get("prompts", [])) or [])
    emit(-1, f"Claude is judging {count or 'the'} moments…")
    child = subprocess.run(
        [claude, "-p", "--output-format", "json", "--max-turns", "40", "--allowedTools", *ALLOWED_TOOLS],
        input=prompt(job_dir.name), cwd=job_dir, env={**os.environ, "UV_PROJECT": str(PIPELINE_DIR)},
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3600,
        creationflags=0x08000000 if sys.platform == "win32" else 0,
    )
    try:
        result = json.loads(child.stdout or "{}")
    except ValueError:
        result = {}
    if child.returncode != 0 or result.get("is_error"):
        raise RuntimeError(result.get("result") or child.stderr[-400:] or "Claude Code stopped with an error")
    emit(-1, (result.get("result") or "Judged.").strip()[:120])
