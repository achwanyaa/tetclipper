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


def analyze(row: dict, start: float | None, end: float | None, captions: str | None,
            stages: list[str] | None = None) -> Iterator[dict]:
    """Run analysis stages for a job whose ingest (media.mp4, audio16k.wav,
    ingest.json) the PC uploaded. Range mode (start/end given): ASR → diarize →
    events → camera → clip spec. Find mode (stages given, no range): just those
    stages (…, candidates); scoring happens on the PC where Claude Code is."""

    def work(emit) -> dict:
        from .. import cli
        from ..edits import manual
        from ..jobs import queue
        from ..spec import build as spec_build
        from ..spec import store as spec_store

        _use_glossary(row.get("glossary"))
        queue.import_job(row["id"], row["source_type"], row["source"], row["settings_json"], row.get("title"))
        job = queue.get_job(row["id"])
        wanted = stages or ["ingest", "asr", "diarize", "events"]
        results = queue.run_stages(job, [s for s in cli._stages() if s.name in wanted], emit)  # noqa: SLF001
        job = queue.get_job(row["id"]) or job
        if start is None or end is None:
            return {"job_id": job.id}
        offset = float(results["ingest"].get("section_offset", 0.0))
        clips = spec_store.list_clips(job.dir)
        if clips:
            idx = clips[0]
        else:
            idx = manual.add_range(job, start - offset, end - offset, lambda f, m: emit("spec", f, m),
                                   caption_preset=captions)["clip_index"]
        spec_build.build(job.dir, idx, style=captions, emit=lambda f, m: emit("spec", f, m))
        queue.set_job_status(job.id, "done", None)
        return {"job_id": job.id, "clip": idx}

    return _threaded(work)


def _use_glossary(data: dict | None) -> None:
    """The PC's word list is the source of truth; mirror it before ASR/specs."""
    if data:
        from ..spec import glossary

        glossary.save(data)


def matte(job_id: str, clip: int, spec: dict) -> Iterator[dict]:
    """Cut the speaker out of a clip on the GPU (spec sent from the PC)."""

    def work(emit) -> dict:
        from ..config import jobs_dir
        from ..spec import matte as matte_mod
        from ..spec import store

        job_dir = jobs_dir() / job_id
        d = store.clip_dir(job_dir, clip)
        d.mkdir(parents=True, exist_ok=True)
        (d / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
        return matte_mod.make(job_dir, clip, lambda f, m: emit("matte", f, m))

    return _threaded(work)


def second_listen(job_id: str, request: dict) -> list[dict]:
    """The Swahili second listen on the GPU, for spans the PC already found.
    request: {words, spans, hotwords?, model?}"""
    from ..config import jobs_dir
    from ..spec import doubts

    return doubts.second_opinion(jobs_dir() / job_id / "audio16k.wav", request["words"], request["spans"],
                                 request.get("hotwords", ""), request.get("model"))


def build_spec(job_id: str, clip: int, captions: str | None, glossary_data: dict | None = None) -> dict:
    """Camera + spec for one scored clip (fanned out across containers)."""
    from ..config import jobs_dir
    from ..spec import build as spec_build

    _use_glossary(glossary_data)
    spec_build.build(jobs_dir() / job_id, clip, style=captions)
    return {"clip": clip}


from ..spec.timeline import FPS, segments, total_frames  # noqa: E402 — shared with spec/music.py


RATE = 48000


def _mix_music(spec: dict, job_dir: Path, speech: Path, out: Path, total: int) -> None:
    """speech.wav + the music bed with the preview's per-frame gains → out."""
    import numpy as np

    from ..spec.music import frame_gains, music_settings

    m = music_settings(spec)
    duration = total / FPS
    decode = subprocess.run(
        ["ffmpeg", "-loglevel", "error", *(["-stream_loop", "-1"] if m["loop"] else []),
         "-ss", f"{float(m['offset']):.3f}", "-i", str(job_dir / m["src"]), "-t", f"{duration:.6f}",
         "-f", "f32le", "-ac", "2", "-ar", str(RATE), "-"],
        capture_output=True,
    )
    if decode.returncode != 0:
        raise RuntimeError(decode.stderr.decode(errors="replace")[-400:])
    pcm = np.frombuffer(decode.stdout, dtype=np.float32).reshape(-1, 2).copy()
    want = int(round(duration * RATE))
    if len(pcm) < want:  # a short, non-looping track: silence after it ends
        pcm = np.vstack([pcm, np.zeros((want - len(pcm), 2), dtype=np.float32)])
    gains = np.repeat(np.asarray(frame_gains(spec), dtype=np.float32), RATE // FPS)
    k = min(len(pcm), len(gains))
    pcm = pcm[:k] * gains[:k, None]
    raw = out.with_suffix(".music.f32")
    raw.write_bytes(pcm.astype(np.float32).tobytes())
    mix = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(speech), "-f", "f32le", "-ar", str(RATE), "-ac", "2",
         "-i", str(raw), "-filter_complex", "amix=inputs=2:normalize=0:duration=first", "-c:a", "pcm_s16le", str(out)],
        capture_output=True, text=True,
    )
    if mix.returncode != 0:
        raise RuntimeError(mix.stderr[-400:])


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
                 "-t", f"{total / FPS:.6f}", str(tmp / "speech.wav")],
                capture_output=True, text=True,
            )
            if run.returncode != 0:
                audio_err.append(run.stderr[-600:])
            elif spec.get("music"):
                try:
                    _mix_music(spec, Path(job_dir), tmp / "speech.wav", tmp / "audio.wav", total)
                except Exception as err:  # noqa: BLE001
                    audio_err.append(f"music: {err}")
            else:
                (tmp / "speech.wav").replace(tmp / "audio.wav")
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
