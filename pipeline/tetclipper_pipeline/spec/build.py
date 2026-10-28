"""Build a clip spec (studio/composition/src/spec.ts) from a job's analysis.

The spec is the one document the Studio editor previews, Claude Code edits
and the Remotion renderer renders. Everything here is derived from stage
checkpoints the pipeline already writes:

  words      ← diarize.json (+ emphasis from spec/emphasis.py, + word_edits)
  crop       ← the camera director's per-frame trajectory, with punch-in zoom
               divided back out and the path simplified to keyframes
  effects    ← the director's punch-ins, as editable `punch-in` effects

Times stay in media-file seconds (the downloaded slice), and `source.src` /
`intro.src` are paths relative to the job dir, so a spec is portable between
this PC and the Modal volume; the editor and renderer turn them into URLs.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .. import config
from . import emphasis
from . import store
from .schema import validate

CAPTION_STYLES = (
    "classic", "beast", "hormozi", "minimal", "karaoke-pop",
    "sermon", "one-word", "boxed", "neon",
)
DEFAULT_STYLE = "hormozi"
# Keyframe simplification tolerance, as a fraction of the source frame
# (0.006 ≈ 12 px on 1920 wide) and zoom units.
PATH_TOLERANCE = 0.006


def _stage(job_dir: Path, name: str) -> dict:
    return json.loads((job_dir / f"{name}.json").read_text(encoding="utf-8"))["data"]


# --- camera path → keyframes ---------------------------------------------------

def _simplify(points: list[tuple[float, float, float, float]], tol: float) -> list[int]:
    """Ramer–Douglas–Peucker over (t, x, y, zoom): indices of the points to keep
    so linear interpolation between them stays within `tol` of every frame."""
    if len(points) <= 2:
        return list(range(len(points)))
    keep = {0, len(points) - 1}
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        ta, tb = points[a][0], points[b][0]
        worst, worst_i = 0.0, -1
        for i in range(a + 1, b):
            p = (points[i][0] - ta) / (tb - ta) if tb > ta else 0.0
            err = max(
                abs(points[a][k] + (points[b][k] - points[a][k]) * p - points[i][k]) for k in (1, 2, 3)
            )
            if err > worst:
                worst, worst_i = err, i
        if worst > tol and worst_i > 0:
            keep.add(worst_i)
            stack += [(a, worst_i), (worst_i, b)]
    return sorted(keep)


def keyframes_from_trajectory(traj: dict, src_w: int, src_h: int, clip_start: float) -> tuple[list[dict], list[dict]]:
    """(crop keyframes, punch-in effects) from a director trajectory.

    Trajectory frames are per-frame crop rects [x, y, w, h] in source px with
    punch-in zoom baked in; the spec keeps the camera path and the punch-ins
    apart so either can be edited on its own."""
    from ..camera import director

    fps = float(traj.get("fps", 25))
    frames = traj.get("frames") or []
    if not frames:
        return [], []
    punches = [director.Punch(start=p["start"], trigger=p.get("trigger", "energy")) for p in traj.get("punches", [])]
    env = director.punch_envelope(len(frames), int(fps), punches)

    base_h = float(src_h)
    base_w = base_h * 9.0 / 16.0
    if base_w > src_w:
        base_w = float(src_w)
    points = []
    for f, (x, y, w, h) in enumerate(frames):
        zoom = max(1.0, (base_w / w) / float(env[f])) if w > 0 else 1.0
        points.append((clip_start + f / fps, (x + w / 2) / src_w, (y + h / 2) / src_h, zoom))

    # Simplify each shot separately so a hard cut stays a jump.
    cuts = sorted({int(c) for c in traj.get("cuts", []) if 0 < int(c) < len(points)})
    bounds = [0, *cuts, len(points)]
    keyframes: list[dict] = []
    for si in range(len(bounds) - 1):
        seg = points[bounds[si] : bounds[si + 1]]
        for j, idx in enumerate(_simplify(seg, PATH_TOLERANCE)):
            t, x, y, z = seg[idx]
            kf = {"t": round(t, 3), "x": round(min(1, max(0, x)), 4), "y": round(min(1, max(0, y)), 4), "zoom": round(z, 3)}
            if si > 0 and j == 0:
                kf["cut"] = True
            keyframes.append(kf)

    effects = [
        {
            "type": "punch-in",
            "at": round(clip_start + p.start, 3),
            "duration": round(p.end - p.start, 3),
            "amount": director.PUNCH_ZOOM,
        }
        for p in punches
    ]
    return keyframes, effects


# --- words -----------------------------------------------------------------------

def words_for(job_dir: Path, start: float, end: float, word_edits: dict[str, str]) -> list[dict]:
    """Caption words in [start, end) with emphasis flags and any text fixes
    (an empty fix hides the word)."""
    return words_and_scores(job_dir, start, end, word_edits)[0]


def words_and_scores(job_dir: Path, start: float, end: float,
                     word_edits: dict[str, str]) -> tuple[list[dict], dict[int, float]]:
    """words_for() plus each word's alignment score, by index (for doubts)."""
    from ..edits.store import word_key

    diarize = _stage(job_dir, "diarize")
    events = _stage(job_dir, "events")
    raw = [
        w for seg in diarize["segments"] for w in seg.get("words", [])
        if w.get("start") is not None and start <= w["start"] < end
    ]
    flags = [emphasis.Word(text=w["word"], start=w["start"] - start, end=w["end"] - start) for w in raw]
    if flags:
        curves = json.loads(Path(events["curves_path"]).read_text(encoding="utf-8"))
        emphasis.mark_emphasis(flags, curves["rms"], float(curves["grid_sec"]), clip_start=start)
    words = []
    scores: dict[int, float] = {}
    for w, flagged in zip(raw, flags):
        if w.get("score") is not None:
            scores[len(words)] = float(w["score"])
        fix = word_edits.get(word_key(w["start"]))
        text = (fix if fix is not None else w["word"]).strip()
        item = {"text": text or w["word"].strip(), "start": round(w["start"], 3), "end": round(w["end"], 3)}
        if flagged.emphasized:
            item["emphasis"] = True
        if fix is not None and not fix.strip():
            item["hidden"] = True
        if w.get("speaker") is not None:
            item["speaker"] = f"S{w['speaker']}"
        words.append(item)
    return words, scores


def find_doubts(job_dir: Path, words: list[dict], scores: dict[int, float], emit=lambda f, m: None) -> list[dict]:
    """Doubtful spans, each re-heard in Swahili when the second opinion is on."""
    from . import doubts

    spans = doubts.detect(words, scores)
    if spans and doubts.enabled():
        emit(-1, f"Re-listening to {len(spans)} doubtful span(s) in Swahili…")
        audio = Path(_stage(job_dir, "ingest")["audio_path"])
        try:
            from ..cloud import client

            # On a PC or the hosted web app (no GPU): the second_listen GPU
            # function. Inside a Modal function (build_spec): right here.
            if client.available() and (client.hosted() or not os.environ.get("MODAL_TASK_ID")):
                spans = client.second_opinion(job_dir, words, spans, "")
            else:
                spans = doubts.second_opinion(audio, words, spans, "")
        except Exception as err:  # noqa: BLE001 — the spans are still worth showing
            emit(-1, f"Second listen failed: {err}")
    return spans


# --- the spec ------------------------------------------------------------------

def _trajectory(job_dir: Path, clip_idx: int, edit, score_clip: dict, settings, emit) -> dict:
    """The clip's camera path, cached next to its spec (directing is minutes of CPU)."""
    cache = store.clip_dir(job_dir, clip_idx) / "trajectory.json"
    if cache.exists():
        cached = json.loads(cache.read_text(encoding="utf-8"))
        if abs(cached.get("start", -1) - edit.start) < 0.05 and abs(cached.get("end", -1) - edit.end) < 0.05:
            return cached
    from ..camera.clip import direct  # heavy camera imports, only when needed

    traj = direct(job_dir, edit.start, edit.end, edit.camera_mode, settings, emit)
    traj = {**traj, "start": edit.start, "end": edit.end}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(traj), encoding="utf-8")
    return traj


def build(job_dir: Path, clip_idx: int, *, style: str | None = None, camera: bool = True,
          force: bool = False, emit=lambda f, m: None) -> dict:
    """Write studio/clip_NN/spec.json (+ transcript.md) for one clip and return
    the spec. An existing spec is kept unless `force` — it holds the user's edits."""
    from ..edits import store as edit_store
    from ..jobs import queue

    job_dir = Path(job_dir)
    existing = store.load(job_dir, clip_idx)
    if existing is not None and not force:
        return existing

    ingest = _stage(job_dir, "ingest")
    score_clip = _stage(job_dir, "score")["clips"][clip_idx]
    edit = edit_store.edit_for_clip(job_dir, clip_idx, score_clip)
    job = queue.get_job(job_dir.name)
    settings = config.Settings.from_json(json.loads(job.settings_json)) if job else config.Settings()

    src_w, src_h = int(ingest["probe"]["width"]), int(ingest["probe"]["height"])
    media = Path(ingest["media_path"])
    keyframes, punches = [], []
    if camera:
        traj = _trajectory(job_dir, clip_idx, edit, score_clip, settings, emit)
        keyframes, punches = keyframes_from_trajectory(traj, src_w, src_h, edit.start)

    from . import glossary

    words, scores = words_and_scores(job_dir, edit.start, edit.end, edit.word_edits)
    words, fixed = glossary.apply_fixes(words)  # what the user taught it on earlier clips
    found = find_doubts(job_dir, words, scores, emit)

    preset = style or edit.caption_preset or settings.caption_preset
    spec = {
        "version": 1,
        "title": ingest.get("title") or None,
        "source": {
            "src": media.name if media.parent == job_dir else str(media),
            "start": round(edit.start, 3),
            "end": round(edit.end, 3),
            "width": src_w,
            "height": src_h,
        },
        "intro": None,
        "cuts": [],
        "words": words,
        "captions": {"enabled": True, "style": preset if preset in CAPTION_STYLES else DEFAULT_STYLE},
        "crop": {"keyframes": keyframes},
        "effects": punches,
        "progressBar": {"enabled": False, "color": "#FFD700"},
        "doubts": found,
    }
    if spec["title"] is None:
        del spec["title"]
    problems = validate(spec)
    if problems:
        raise ValueError("built an invalid spec: " + "; ".join(problems[:5]))
    note = f"built from analysis ({fixed} learned fix{'es' if fixed != 1 else ''} applied)" if fixed else "built from analysis"
    store.save(job_dir, clip_idx, spec, reason=note)
    return spec


def refresh_doubts(job_dir: Path, clip_idx: int, emit=lambda f, m: None) -> dict:
    """Recompute doubts (and the Swahili second listen) on a clip's current
    words, keeping every edit. Alignment scores come from the analysis, matched
    by word start time."""
    job_dir = Path(job_dir)
    spec = store.load(job_dir, clip_idx)
    if spec is None:
        raise ValueError(f"clip {clip_idx} has no spec yet")
    diarize = _stage(job_dir, "diarize")
    by_start = {round(w["start"], 2): w.get("score") for seg in diarize["segments"] for w in seg.get("words", [])
                if w.get("start") is not None}
    raw_text = {round(w["start"], 2): w["word"] for seg in diarize["segments"] for w in seg.get("words", [])
                if w.get("start") is not None}
    scores = {i: float(by_start[round(w["start"], 2)]) for i, w in enumerate(spec["words"])
              if by_start.get(round(w["start"], 2)) is not None}
    # Words someone already fixed (text differs from what the speech model
    # wrote, or retimed so they no longer match) are trusted, not re-flagged.
    from .glossary import norm

    edited = {i for i, w in enumerate(spec["words"])
              if norm(raw_text.get(round(w["start"], 2), "")) != norm(w["text"]) or w.get("hidden")}
    words = [{**w, "hidden": True} if i in edited else w for i, w in enumerate(spec["words"])]
    spec = {**spec, "doubts": find_doubts(job_dir, words, scores, emit)}
    store.save(job_dir, clip_idx, spec, reason=f"checked captions: {len(spec['doubts'])} span(s) to verify")
    return spec
