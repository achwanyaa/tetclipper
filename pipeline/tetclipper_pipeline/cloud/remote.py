"""The work done inside Modal functions. Each entry point is a generator of
progress events ({"event": "progress", stage, fraction, message}) ending in
one {"event": "result", ...}, which modal_app.py relays to the PC."""

from __future__ import annotations

import json
import os
import queue as queue_mod
import subprocess
import threading
from pathlib import Path
from typing import Callable, Iterator

STUDIO_DIR = Path("/root/studio")


def _threaded(work: Callable[[Callable[[str, float, str], None]], dict]) -> Iterator[dict]:
    """Run `work(emit)` on a thread and yield its progress as it happens."""
    events: queue_mod.Queue = queue_mod.Queue()

    def emit(stage: str, fraction: float, message: str) -> None:
        events.put({"event": "progress", "stage": stage, "fraction": fraction, "message": message})

    def run() -> None:
        try:
            events.put({"event": "result", "ok": True, **work(emit)})
        except Exception as err:  # noqa: BLE001 — every failure goes back to the PC
            events.put({"event": "result", "ok": False, "error": str(err)})

    threading.Thread(target=run, daemon=True).start()
    while True:
        ev = events.get()
        yield ev
        if ev["event"] == "result":
            return


def analyze(row: dict, start: float, end: float, captions: str | None) -> Iterator[dict]:
    """ASR → diarize → events → camera → spec for a range job whose ingest
    (media.mp4, audio16k.wav, ingest.json) the PC already uploaded."""

    def work(emit) -> dict:
        from .. import cli
        from ..edits import manual
        from ..jobs import queue
        from ..spec import build as spec_build
        from ..spec import store as spec_store

        queue.import_job(row["id"], row["source_type"], row["source"], row["settings_json"], row.get("title"))
        job = queue.get_job(row["id"])
        stages = [s for s in cli._stages() if s.name in ("ingest", "asr", "diarize", "events")]  # noqa: SLF001
        results = queue.run_stages(job, stages, emit)
        offset = float(results["ingest"].get("section_offset", 0.0))
        job = queue.get_job(row["id"]) or job
        clips = spec_store.list_clips(job.dir)
        if clips:
            idx = clips[0]
        else:
            idx = manual.add_range(job, start - offset, end - offset, lambda f, m: emit("spec", f, m),
                                   caption_preset=captions, render=False)["clip_index"]
        spec_build.build(job.dir, idx, style=captions, emit=lambda f, m: emit("spec", f, m))
        queue.set_job_status(job.id, "done", None)
        return {"job_id": job.id, "clip": idx}

    return _threaded(work)


FPS = 30


def _round(x: float) -> int:
    return int(x + 0.5)  # JS Math.round, as in studio/composition/src/timeline.ts


def segments(spec: dict, fps: int = FPS) -> tuple[int, list[tuple[float, int]]]:
    """(intro frames, [(source start, frames)]) exactly as buildTimeline() in
    studio/composition/src/timeline.ts: the source range minus merged cuts."""
    src = spec["source"]
    a, b = float(src["start"]), float(src["end"])
    intro = spec.get("intro")
    intro_frames = _round(float(intro.get("duration", 2)) * fps) if intro else 0
    cuts = sorted(
        (max(a, min(c["start"], c["end"])), min(b, max(c["start"], c["end"])))
        for c in spec.get("cuts", [])
    )
    merged: list[list[float]] = []
    for c0, c1 in cuts:
        if c1 <= c0:
            continue
        if merged and c0 <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], c1)
        else:
            merged.append([c0, c1])
    out: list[tuple[float, int]] = []
    cursor = a
    for c0, c1 in [*merged, [b, b]]:
        n = _round((c0 - cursor) * fps)
        if n >= 1:
            out.append((cursor, n))
        cursor = c1
    return intro_frames, out


def total_frames(spec: dict, fps: int = FPS) -> int:
    """Output length in frames: intro + every kept segment."""
    intro, segs = segments(spec, fps)
    return max(1, intro + sum(n for _, n in segs))


def chunk_ranges(total: int, max_chunks: int = 40, min_frames: int = 60) -> list[tuple[int, int]]:
    size = max(min_frames, -(-total // max_chunks))
    return [(a, min(total, a + size) - 1) for a in range(0, total, size)]


def _node_render(clip_dir: Path, job_dir: str, out: Path, *extra: str) -> dict:
    child = subprocess.run(
        ["node", str(STUDIO_DIR / "composition" / "scripts" / "render.mjs"), str(clip_dir / "spec.json"),
         job_dir, str(out), *extra],
        cwd=str(STUDIO_DIR / "composition"), capture_output=True, text=True,
    )
    result: dict = {}
    for line in child.stdout.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("event") == "result":
            result = ev
    if child.returncode != 0 or not result.get("ok"):
        raise RuntimeError(result.get("error") or child.stderr[-800:] or "render failed")
    return result


def render_chunk(job_dir: str, clip: int, first: int, last: int) -> bytes:
    """One silent h264 chunk of the clip (frames first..last), as mp4 bytes."""
    import tempfile

    clip_dir = Path(job_dir) / "studio" / f"clip_{clip:02d}"
    concurrency = os.environ.get("TETCLIPPER_RENDER_CONCURRENCY", "8")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "chunk.mp4"
        _node_render(clip_dir, job_dir, out, f"--frames={first}-{last}", "--muted", f"--concurrency={concurrency}")
        return out.read_bytes()


def render(job_dir: str, clip: int, chunk_map: Callable) -> Iterator[dict]:
    """Render studio/clip_NN/spec.json to studio/clip_NN/render.mp4: frames in
    parallel chunks (chunk_map = render_chunk.starmap), the soundtrack here,
    then one ffmpeg join (video stream-copied)."""
    import tempfile
    import time

    t0 = time.time()
    clip_dir = Path(job_dir) / "studio" / f"clip_{clip:02d}"
    spec = json.loads((clip_dir / "spec.json").read_text(encoding="utf-8"))
    total = total_frames(spec)
    ranges = chunk_ranges(total)

    def progress(fraction: float, message: str) -> dict:
        return {"event": "progress", "stage": "render", "fraction": fraction, "message": message}

    yield progress(0.02, f"Rendering {total} frames in {len(ranges)} parallel chunks…")
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        audio_err: list[str] = []

        timings: dict[str, float] = {}

        def audio() -> None:
            # The soundtrack is intro silence + the kept source segments, cut to
            # the same frame-exact lengths the video uses.
            a0 = time.time()
            intro, segs = segments(spec)
            media = Path(job_dir) / spec["source"]["src"]
            parts = [
                f"[0:a]atrim=start={st:.6f}:duration={n / FPS:.6f},asetpts=PTS-STARTPTS[s{i}]"
                for i, (st, n) in enumerate(segs)
            ]
            chain = "".join(f"[s{i}]" for i in range(len(segs))) + f"concat=n={len(segs)}:v=0:a=1[cat]"
            delay = f";[cat]adelay=delays={intro * 1000 // FPS}:all=1[out]" if intro else ";[cat]anull[out]"
            run = subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-i", str(media), "-filter_complex",
                 ";".join(parts) + ";" + chain + delay, "-map", "[out]", "-ar", "48000", "-ac", "2",
                 "-t", f"{total / FPS:.6f}", str(tmp / "audio.wav")],
                capture_output=True, text=True,
            )
            if run.returncode != 0:
                audio_err.append(run.stderr[-600:])
            timings["audio"] = round(time.time() - a0, 1)

        audio_thread = threading.Thread(target=audio, daemon=True)
        audio_thread.start()
        try:
            for i, data in enumerate(chunk_map([(job_dir, clip, a, b) for a, b in ranges])):
                (tmp / f"chunk_{i:03d}.mp4").write_bytes(data)
                yield progress(0.05 + 0.85 * (i + 1) / len(ranges), f"Rendered chunk {i + 1}/{len(ranges)}")
        except Exception as err:  # noqa: BLE001
            yield {"event": "result", "ok": False, "error": f"chunk render failed: {err}"}
            return
        timings["chunks"] = round(time.time() - t0, 1)
        audio_thread.join()
        if audio_err:
            yield {"event": "result", "ok": False, "error": f"audio render failed: {audio_err[0]}"}
            return
        yield progress(0.93, "Joining chunks…")
        listing = tmp / "chunks.txt"
        names = [tmp / f"chunk_{i:03d}.mp4" for i in range(len(ranges))]
        listing.write_text("".join(f"file '{p.as_posix()}'" + chr(10) for p in names))
        out = tmp / "render.mp4"
        join = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
             "-i", str(tmp / "audio.wav"), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
             "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out)],
            capture_output=True, text=True,
        )
        if join.returncode != 0:
            yield {"event": "result", "ok": False, "error": f"ffmpeg join failed: {join.stderr[-600:]}"}
            return
        timings["join"] = round(time.time() - t0 - timings["chunks"], 1)
        dest = clip_dir / "render.mp4"
        tmp_dest = clip_dir / "render.part.mp4"
        tmp_dest.write_bytes(out.read_bytes())
        tmp_dest.replace(dest)
    seconds = round(time.time() - t0, 1)
    yield {"event": "result", "ok": True, "output": f"studio/clip_{clip:02d}/render.mp4",
           "seconds": seconds, "fps": round(total / seconds, 1), "chunks": len(ranges), "timings": timings}
