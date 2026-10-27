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
    """Answer the job's pending brain request: with the admin's API model when
    one is chosen (the online app), else a headless Claude Code run."""
    from ..server import agent
    from ..server.studio_chat import find_claude as _claude

    job_dir = Path(job_dir)
    request = brain.load_request(job_dir)
    if not request:
        return
    if agent.uses_api():
        _answer_with_api(job_dir, request, emit, agent)
        return
    claude = _claude()
    if claude is None:
        if os.environ.get("TETCLIPPER_AUTH", "").lower() == "supabase":
            raise RuntimeError("Finding moments needs an AI model. The admin can choose one under ✦ AI model.")
        raise RuntimeError("Finding moments needs the Claude Code CLI logged in on this machine, or an API model under ✦ AI model.")
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


API_SYSTEM = """You are tetclipper's scoring brain. Judge each prompt and answer with JSON only:
one object {"<id>": {...answer matching that item's schema...}, ...} covering every id.
No prose, no code fences."""


def _json_object(text: str) -> dict:
    """The JSON object in a model reply (tolerates code fences or a stray sentence)."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in the reply")
    value = json.loads(text[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError("the reply isn't a JSON object")
    return value


def _answer_with_api(job_dir: Path, request: dict, emit: Callable[[float, str], None], agent) -> None:
    """The same judging through the admin's API model: send every prompt at
    once, store the valid answers, and send back only what's missing or wrong
    (up to three rounds)."""
    items = request.get("items", [])
    emit(-1, f"Judging {len(items)} moments…")
    def render(req: dict) -> str:
        return (brain.render_request(req)
                .replace("Write ONE file:", "Reply with ONE JSON object:")
                .replace(" and run `tetclipper brain answer <job> <file>`", ""))

    prompt = render(request) + "\n\n" + _judging_rules()
    collected: dict = {}
    for _ in range(3):
        reply = agent.complete(API_SYSTEM, prompt)
        try:
            collected.update(_json_object(reply))
        except ValueError as err:
            prompt = f"Your last reply couldn't be read ({err}). Reply with only the JSON object.\n\n" + prompt
            continue
        result = brain.apply_answers(job_dir, collected)
        if not result["missing"] and not result["errors"]:
            emit(-1, f"Judged {result['written']} moments.")
            return
        todo = set(result["missing"]) | set(result["errors"])
        emit(-1, f"Re-asking about {len(todo)} moments…")
        prompt = (
            "Some answers were missing or didn't match their schema:\n"
            + json.dumps({"missing": result["missing"], "errors": result["errors"]}, ensure_ascii=False)
            + "\nAnswer only these ids, as one JSON object.\n\n"
            + render({**request, "items": [i for i in items if i["id"] in todo]})
        )
        for bad in result["errors"]:
            collected.pop(bad, None)
    raise RuntimeError("The AI model's judging didn't come back complete. Try Find moments again, or pick another model.")
