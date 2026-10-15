"""Claude Code as the scoring brain (llm_mode "claude").

No API: when the score stage needs an answer it doesn't have, the job pauses
and writes every pending prompt to ``<job>/brain_request.json``. A Claude Code
session reads them (``tetclipper brain show <job>``), writes one answers file,
and hands it back (``tetclipper brain answer <job> <file>``), which drops each
answer into the normal LLM cache. ``tetclipper resume <job> --llm claude`` then
re-runs the stage and every call is a cache hit.

A job needs two rounds: the T1 rubric for every candidate (~35), then a music
brief for each of the 12 finalists (which depend on round one's ranking).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ..jobs.queue import StageError
from . import llm as llm_mod

REQUEST_FILE = "brain_request.json"


class BrainPending(Exception):
    """A cache miss in handoff mode. Deliberately NOT an LlmError: the score
    stage's per-call skip paths swallow it, so one pass over all candidates
    collects every prompt still needed instead of stopping at the first."""


class AwaitingBrain(StageError):
    """The stage paused for Claude Code. Resumable like any StageError."""

    def __init__(self, job_dir: Path, count: int, purpose: str):
        self.job_id = job_dir.name
        self.count = count
        self.purpose = purpose
        super().__init__(
            f"Waiting for Claude Code: {count} {purpose} prompt(s). "
            f"Run /score-clips {job_dir.name} in Claude Code, then resume."
        )


class ClaudeHandoffClient:
    backend = "claude"
    model = "claude-code"

    def __init__(self) -> None:
        self.pending: list[dict] = []

    def generate_json(self, prompt: str, schema: dict, images: list[bytes] | None = None) -> dict:
        if images:
            raise BrainPending("the handoff brain is text-only")
        key = llm_mod._cache_key(self.backend, self.model, prompt, schema, [])  # noqa: SLF001
        cache_file = llm_mod._cache_dir() / f"{key}.json"  # noqa: SLF001
        if cache_file.exists():
            return json.loads(cache_file.read_text(encoding="utf-8"))
        if not any(p["id"] == key for p in self.pending):
            self.pending.append({"id": key, "prompt": prompt, "schema": schema})
        raise BrainPending(key)

    def checkpoint(self, job_dir: Path, purpose: str) -> None:
        """Pause the stage if anything is pending; otherwise clear the request."""
        path = job_dir / REQUEST_FILE
        if not self.pending:
            path.unlink(missing_ok=True)
            return
        path.write_text(
            json.dumps({"job_id": job_dir.name, "purpose": purpose, "items": self.pending}, indent=1),
            encoding="utf-8",
        )
        raise AwaitingBrain(job_dir, len(self.pending), purpose)


# ---------- the Claude Code side ----------

def load_request(job_dir: Path) -> dict | None:
    path = job_dir / REQUEST_FILE
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _common_affixes(texts: list[str]) -> tuple[str, str]:
    if len(texts) < 2:
        return "", ""
    # Snap to line boundaries so no item loses part of a word.
    prefix = os.path.commonprefix(texts)
    prefix = prefix[: prefix.rfind("\n") + 1]
    suffix = os.path.commonprefix([t[len(prefix):][::-1] for t in texts])[::-1]
    suffix = suffix[suffix.find("\n"):] if "\n" in suffix else ""
    return prefix, suffix


def render_request(request: dict) -> str:
    """Compact text for a Claude Code session to read: each distinct schema
    and the instructions shared by its prompts are printed once."""
    groups: dict[str, list[dict]] = {}
    for item in request["items"]:
        groups.setdefault(json.dumps(item["schema"], sort_keys=True), []).append(item)

    out = [
        f"JOB {request['job_id']} — {len(request['items'])} {request['purpose']} prompt(s).",
        "Answer every item with a JSON object matching its group's schema.",
        'Write ONE file: {"<id>": {...answer...}, ...} and run `tetclipper brain answer <job> <file>`.',
        "",
    ]
    for g, (schema_key, items) in enumerate(groups.items(), 1):
        prefix, suffix = _common_affixes([i["prompt"] for i in items])
        out += [f"=== GROUP {g} ({len(items)} items) — schema:", schema_key, ""]
        if prefix.strip():
            out += ["--- shared instructions (before each item):", prefix.strip(), ""]
        if suffix.strip():
            out += ["--- shared instructions (after each item):", suffix.strip(), ""]
        for item in items:
            body = item["prompt"][len(prefix): len(item["prompt"]) - len(suffix) or None]
            out += [f"--- id {item['id']}", body.strip(), ""]
    return "\n".join(out)


_TYPES = {"integer": int, "number": (int, float), "string": str, "boolean": bool, "array": list, "object": dict}


def validate(answer: Any, schema: dict) -> list[str]:
    """Light schema check: required keys, primitive types, enums."""
    if not isinstance(answer, dict):
        return ["answer is not an object"]
    errors = []
    props = schema.get("properties", {})
    for key in schema.get("required", []):
        if key not in answer:
            errors.append(f"missing {key}")
    for key, spec in props.items():
        if key not in answer:
            continue
        value = answer[key]
        want = _TYPES.get(spec.get("type", ""))
        if want and (not isinstance(value, want) or (spec.get("type") == "integer" and isinstance(value, bool))):
            errors.append(f"{key} should be {spec['type']}")
        if "enum" in spec and value not in spec["enum"]:
            errors.append(f"{key} must be one of {spec['enum']}")
    return errors


def apply_answers(job_dir: Path, answers: dict) -> dict:
    """Validate answers against the open request and write the valid ones to
    the LLM cache. Returns {written, missing, errors}."""
    request = load_request(job_dir)
    if request is None:
        return {"written": 0, "missing": [], "errors": {"_": "no open brain request for this job"}}
    cache = llm_mod._cache_dir()  # noqa: SLF001
    written, missing, errors = 0, [], {}
    for item in request["items"]:
        answer = answers.get(item["id"])
        if answer is None:
            missing.append(item["id"])
            continue
        problems = validate(answer, item["schema"])
        if problems:
            errors[item["id"]] = problems
            continue
        (cache / f"{item['id']}.json").write_text(json.dumps(answer), encoding="utf-8")
        written += 1
    return {"written": written, "missing": missing, "errors": errors}
