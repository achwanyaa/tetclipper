"""Where a clip's spec lives, with an undo history.

  jobs/<id>/studio/clip_NN/
    spec.json         the current spec (what the editor shows)
    transcript.md     compact text view for Claude Code (rewritten on save)
    history/NNN.json  every saved version, newest last; undo restores the
                      previous one and drops the newest
"""

from __future__ import annotations

import json
from pathlib import Path

from .schema import validate

HISTORY_KEEP = 200


def clip_dir(job_dir: Path, clip_idx: int) -> Path:
    return Path(job_dir) / "studio" / f"clip_{clip_idx:02d}"


def spec_path(job_dir: Path, clip_idx: int) -> Path:
    return clip_dir(job_dir, clip_idx) / "spec.json"


def load(job_dir: Path, clip_idx: int) -> dict | None:
    path = spec_path(job_dir, clip_idx)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def list_clips(job_dir: Path) -> list[int]:
    root = Path(job_dir) / "studio"
    if not root.is_dir():
        return []
    out = []
    for d in root.iterdir():
        if d.name.startswith("clip_") and (d / "spec.json").exists():
            try:
                out.append(int(d.name[5:]))
            except ValueError:
                continue
    return sorted(out)


def _history(job_dir: Path, clip_idx: int) -> list[Path]:
    hist = clip_dir(job_dir, clip_idx) / "history"
    return sorted(hist.glob("*.json")) if hist.is_dir() else []


def save(job_dir: Path, clip_idx: int, spec: dict, reason: str = "") -> dict:
    """Validate, write spec.json + transcript.md, and append a history entry.
    Raises ValueError (with every problem) when the spec is invalid."""
    from .transcript import write as write_transcript

    problems = validate(spec)
    if problems:
        raise ValueError("invalid spec: " + "; ".join(problems))
    d = clip_dir(job_dir, clip_idx)
    hist_now = _history(job_dir, clip_idx)
    if hist_now and not reason.startswith("built"):
        # Every caption fix (the user's or Claude's) teaches the word list.
        from . import glossary

        try:
            previous = json.loads(hist_now[-1].read_text(encoding="utf-8"))
        except (OSError, ValueError):
            previous = None
        if previous is not None:
            glossary.learn(previous.get("words", []), spec.get("words", []))
            if not reason.startswith("checked captions"):
                spec = {**spec, "doubts": _unresolved(previous, spec)}
    (d / "history").mkdir(parents=True, exist_ok=True)
    text = json.dumps(spec, indent=1, ensure_ascii=False)
    hist = _history(job_dir, clip_idx)
    if not hist or hist[-1].read_text(encoding="utf-8") != text:
        n = int(hist[-1].stem) + 1 if hist else 1
        (d / "history" / f"{n:04d}.json").write_text(text, encoding="utf-8")
        (d / "history" / f"{n:04d}.reason").write_text(reason, encoding="utf-8")
        for old in hist[: max(0, len(hist) + 1 - HISTORY_KEEP)]:
            old.unlink(missing_ok=True)
            old.with_suffix(".reason").unlink(missing_ok=True)
    (d / "spec.json").write_text(text, encoding="utf-8")
    write_transcript(job_dir, clip_idx, spec)
    return spec


def _unresolved(previous: dict, spec: dict) -> list[dict]:
    """Doubts still worth showing: a span whose words were edited is resolved."""
    old_w, new_w = previous.get("words", []), spec.get("words", [])
    keep = []
    for d in spec.get("doubts", []):
        a, b = d["from"], d["to"]
        if b >= len(new_w):
            continue
        same = len(old_w) == len(new_w) and all(
            old_w[i].get("text") == new_w[i].get("text") and bool(old_w[i].get("hidden")) == bool(new_w[i].get("hidden"))
            for i in range(a, b + 1)
        )
        if same:
            keep.append(d)
    return keep


def sync_from_disk(job_dir: Path, clip_idx: int, reason: str = "edited") -> tuple[dict | None, list[str]]:
    """After something edited spec.json directly (Claude Code): validate it.
    Valid → record it in history. Invalid → restore the last good version.
    Returns (current spec, problems found)."""
    path = spec_path(job_dir, clip_idx)
    hist = _history(job_dir, clip_idx)
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
        problems = validate(spec)
    except (OSError, json.JSONDecodeError) as err:
        spec, problems = None, [f"spec.json is not valid JSON: {err}"]
    if not problems:
        save(job_dir, clip_idx, spec, reason)
        return spec, []
    if hist:
        good = hist[-1].read_text(encoding="utf-8")
        path.write_text(good, encoding="utf-8")
        return json.loads(good), problems
    return None, problems


def undo(job_dir: Path, clip_idx: int) -> dict | None:
    """Step back one version. Returns the restored spec (None if nothing to undo)."""
    hist = _history(job_dir, clip_idx)
    if len(hist) < 2:
        return None
    hist[-1].unlink()
    hist[-1].with_suffix(".reason").unlink(missing_ok=True)
    text = hist[-2].read_text(encoding="utf-8")
    spec_path(job_dir, clip_idx).write_text(text, encoding="utf-8")
    spec = json.loads(text)
    from .transcript import write as write_transcript

    write_transcript(job_dir, clip_idx, spec)
    return spec


def history(job_dir: Path, clip_idx: int) -> list[dict]:
    return [
        {"version": int(p.stem), "reason": p.with_suffix(".reason").read_text(encoding="utf-8")
         if p.with_suffix(".reason").exists() else ""}
        for p in _history(job_dir, clip_idx)
    ]
