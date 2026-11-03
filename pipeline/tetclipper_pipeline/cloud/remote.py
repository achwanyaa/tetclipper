"""The work done inside Modal functions. Each entry point is a generator of
progress events ({"event": "progress", stage, fraction, message}) ending in
one {"event": "result", ...}, which modal_app.py relays to the PC."""

from __future__ import annotations

import json
import os
import queue as queue_mod
import shutil
import subprocess
import threading
import wave
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
    ingest.json) the caller uploaded: ASR → diarize → events by default, or
    `stages` (find adds candidates). Only the GPU work: the caller adds the
    clip and has it built by `build_spec` on a CPU container, and scores on
    its side. start/end/captions are still accepted: an older desktop app
    sends them, gets no spec back, and builds the clip on the PC instead."""

    def work(emit) -> dict:
        from .. import cli
        from ..jobs import queue

        _use_glossary(row.get("glossary"))
        queue.import_job(row["id"], row["source_type"], row["source"], row["settings_json"], row.get("title"))
        job = queue.get_job(row["id"])
        wanted = stages or ["ingest", "asr", "diarize", "events"]
        queue.run_stages(job, [s for s in cli._stages() if s.name in wanted], emit)  # noqa: SLF001
        return {"job_id": job.id}

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


from ..spec.long_video import base_filter, is_long_video, overlay_filter, remotion_ranges  # noqa: E402
from ..spec.timeline import FPS, _bookend_frames, outro_start, segments, total_frames  # noqa: E402 — shared with spec/music.py


RATE = 48000


def _fit_music(pcm, want: int, loop: bool):
    """The decoded range at exactly `want` samples: repeated when it loops, else
    followed by silence."""
    import numpy as np

    if len(pcm) == 0:
        return np.zeros((want, 2), dtype=np.float32)
    if loop:
        return np.tile(pcm, (want // len(pcm) + 1, 1))[:want]
    if len(pcm) < want:
        return np.vstack([pcm, np.zeros((want - len(pcm), 2), dtype=np.float32)])
    return pcm[:want]


def _mix_music(spec: dict, job_dir: Path, speech: Path, out: Path, total: int) -> None:
    """speech.wav + the music bed with the preview's per-frame gains → out."""
    import numpy as np

    from ..spec.music import frame_gains, music_range, music_settings

    m = music_settings(spec)
    duration = total / FPS
    start, end = music_range(m)
    length = None if end is None else end - start
    if not m["loop"]:
        length = duration if length is None else min(length, duration)
    decode = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-ss", f"{start:.3f}", "-i", str(job_dir / m["src"]),
         *([] if length is None else ["-t", f"{length:.6f}"]),
         "-f", "f32le", "-ac", "2", "-ar", str(RATE), "-"],
        capture_output=True,
    )
    if decode.returncode != 0:
        raise RuntimeError(decode.stderr.decode(errors="replace")[-400:])
    pcm = np.frombuffer(decode.stdout, dtype=np.float32).reshape(-1, 2)
    pcm = _fit_music(pcm, int(round(duration * RATE)), m["loop"])
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


def _has_audio(path: Path) -> bool:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    return probe.returncode == 0 and bool(probe.stdout.strip())


def _bookend_sounds(spec: dict) -> list[dict]:
    """The intro/outro videos that play sound: start second, length and the fade
    across the overlap with the speech, matching the composition's volume curve."""
    video = sum(n for _, n in segments(spec)[1])
    sounds = []
    for side, first in (("intro", 0), ("outro", outro_start(spec))):
        item = spec.get(side)
        if not item or item.get("kind") != "video" or float(item.get("volume", 1)) <= 0:
            continue
        frames, overlap = _bookend_frames(item, video, FPS)
        sounds.append({"src": item["src"], "at": first / FPS, "length": frames / FPS, "volume": float(item.get("volume", 1)),
                       "fade": overlap / FPS, "entering": side == "outro"})
    return sounds


def _mix_bookends(spec: dict, job_dir: Path, speech: Path, out: Path) -> bool:
    """speech + the sound of intro/outro videos → out. False if there's none."""
    sounds = [s for s in _bookend_sounds(spec) if _has_audio(job_dir / s["src"])]
    if not sounds:
        return False
    args = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(speech)]
    parts, labels = [], ["[0:a]"]
    for i, s in enumerate(sounds, 1):
        args += ["-i", str(job_dir / s["src"])]
        chain = f"[{i}:a]atrim=duration={s['length']:.6f},asetpts=PTS-STARTPTS,aformat=sample_rates={RATE}:channel_layouts=stereo,volume={s['volume']:.4f}"
        if s["fade"] > 0:
            chain += (f",afade=t=in:d={s['fade']:.6f}" if s["entering"]
                      else f",afade=t=out:st={s['length'] - s['fade']:.6f}:d={s['fade']:.6f}")
        parts.append(f"{chain},adelay=delays={int(round(s['at'] * 1000))}:all=1[b{i}]")
        labels.append(f"[b{i}]")
    graph = ";".join(parts) + ";" + "".join(labels) + f"amix=inputs={len(labels)}:normalize=0:duration=first[out]"
    run = subprocess.run([*args, "-filter_complex", graph, "-map", "[out]", "-c:a", "pcm_s16le", str(out)],
                         capture_output=True, text=True)
    if run.returncode != 0:
        raise RuntimeError(run.stderr[-400:])
    return True


def _exact_speech(spec: dict, media: Path, out: Path, tmp: Path, total: int) -> None:
    """The kept source audio, sample-exact to the video's frames, from a single
    decode: a long video can have hundreds of cuts, and a filter per cut would
    decode the file again for each one."""
    raw = tmp / "source.raw"
    run = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(media), "-vn", "-af", "aresample=first_pts=0",
         "-f", "s16le", "-ac", "2", "-ar", str(RATE), str(raw)],
        capture_output=True, text=True,
    )
    if run.returncode != 0:
        raise RuntimeError(run.stderr[-600:])
    per_frame = RATE // FPS
    size = 4  # bytes per stereo sample
    silence = bytes(size * 65536)

    def write_silence(wav, samples: int) -> None:
        while samples > 0:
            step = min(samples, 65536)
            wav.writeframesraw(silence[:step * size])
            samples -= step

    intro, segs = segments(spec)
    with wave.open(str(out), "wb") as wav, open(raw, "rb") as src:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        write_silence(wav, intro * per_frame)
        written = intro
        for start, frames in segs:
            src.seek(int(round(start * RATE)) * size)
            left = frames * per_frame
            while left > 0:
                data = src.read(min(left * size, 1 << 20))
                if not data:
                    break
                wav.writeframesraw(data)
                left -= len(data) // size
            write_silence(wav, left)  # the file's audio ended early
            written += frames
        write_silence(wav, max(0, total - written) * per_frame)
    raw.unlink(missing_ok=True)


def _soundtrack(spec: dict, job_dir: Path, tmp: Path, total: int) -> None:
    """tmp/audio.wav: intro silence + the kept source segments, cut to the same
    frame-exact lengths the video uses, padded through the outro, then the sound
    of intro/outro videos and the music bed."""
    media = job_dir / spec["source"]["src"]
    if is_long_video(spec):
        _exact_speech(spec, media, tmp / "speech.wav", tmp, total)
    else:
        intro, segs = segments(spec)
        parts = [
            f"[0:a]atrim=start={st:.6f}:duration={n / FPS:.6f},asetpts=PTS-STARTPTS[s{i}]"
            for i, (st, n) in enumerate(segs)
        ]
        chain = "".join(f"[s{i}]" for i in range(len(segs))) + f"concat=n={len(segs)}:v=0:a=1[cat]"
        delay = f";[cat]adelay=delays={intro * 1000 // FPS}:all=1,apad[out]" if intro else ";[cat]apad[out]"
        run = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(media), "-filter_complex",
             ";".join(parts) + ";" + chain + delay, "-map", "[out]", "-ar", str(RATE), "-ac", "2",
             "-t", f"{total / FPS:.6f}", str(tmp / "speech.wav")],
            capture_output=True, text=True,
        )
        if run.returncode != 0:
            raise RuntimeError(run.stderr[-600:])
    if _mix_bookends(spec, job_dir, tmp / "speech.wav", tmp / "voices.wav"):
        (tmp / "voices.wav").replace(tmp / "speech.wav")
    if spec.get("music"):
        _mix_music(spec, job_dir, tmp / "speech.wav", tmp / "audio.wav", total)
    else:
        (tmp / "speech.wav").replace(tmp / "audio.wav")


def _render_mostly_plain(job_dir: str, clip: int, chunk_map: Callable, spec: dict, total: int,
                         extra: list[tuple[int, int]]) -> Iterator[dict]:
    """A long video with few effects: Remotion only for the frames that need it
    (spec/long_video.py), overlaid during one ffmpeg encode of the source."""
    import tempfile
    import time

    t0 = time.time()
    clip_dir = Path(job_dir) / "studio" / f"clip_{clip:02d}"

    def progress(fraction: float, message: str) -> dict:
        return {"event": "progress", "stage": "render", "fraction": fraction, "message": message}

    chunks = [(a + first, a + last) for a, b in extra for first, last in chunk_ranges(b - a + 1)]
    frames = sum(b - a + 1 for a, b in extra)
    timings: dict[str, float] = {}
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        audio_err: list[str] = []

        def audio() -> None:
            a0 = time.time()
            try:
                _soundtrack(spec, Path(job_dir), tmp, total)
            except Exception as err:  # noqa: BLE001
                audio_err.append(str(err)[-600:])
            timings["audio"] = round(time.time() - a0, 1)

        audio_thread = threading.Thread(target=audio, daemon=True)
        audio_thread.start()

        args = ["ffmpeg", "-y", "-loglevel", "error", "-progress", "pipe:1", "-nostats",
                "-i", str(Path(job_dir) / spec["source"]["src"])]
        if chunks:
            yield progress(0.02, f"Rendering effects: {frames} of {total} frames…")
            try:
                names = []
                for i, data in enumerate(chunk_map([(job_dir, clip, a, b) for a, b in chunks])):
                    name = tmp / f"chunk_{i:03d}.mp4"
                    name.write_bytes(data)
                    names.append(name)
                    yield progress(0.02 + 0.18 * (i + 1) / len(chunks), f"Rendered effects {i + 1}/{len(chunks)}")
            except Exception as err:  # noqa: BLE001
                yield {"event": "result", "ok": False, "error": f"chunk render failed: {err}"}
                return
            listing = tmp / "chunks.txt"
            listing.write_text("".join(f"file '{p.as_posix()}'" + chr(10) for p in names))
            joined = tmp / "effects.mp4"
            join = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                                   "-c", "copy", str(joined)], capture_output=True, text=True)
            if join.returncode != 0:
                yield {"event": "result", "ok": False, "error": f"joining effects failed: {join.stderr[-600:]}"}
                return
            timings["effects"] = round(time.time() - t0, 1)
            args += ["-i", str(joined)]
        audio_thread.join()
        if audio_err:
            yield {"event": "result", "ok": False, "error": f"audio render failed: {audio_err[0]}"}
            return

        width, height = (1920, 1080)
        graph = f"[0:v]{base_filter(spec, width, height)}[base]"
        if chunks:
            timing, enable = overlay_filter(extra)
            graph += f";[1:v]{timing}[fx];[base][fx]overlay=eof_action=pass:repeatlast=0:enable='{enable}',trim=end_frame={total}[v]"
        else:
            graph += f";[base]trim=end_frame={total}[v]"
        out = tmp / "render.mp4"
        args += ["-i", str(tmp / "audio.wav"), "-filter_complex", graph, "-map", "[v]", "-map", f"{2 if chunks else 1}:a",
                 # The filter ends the video: -frames:v or -shortest would stop before
                 # the encoder's buffered audio is written, losing the last second or two.
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
                 "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                 "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)]
        yield progress(0.22, "Encoding the video…")
        e0 = time.time()
        encode = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        assert encode.stdout is not None
        errors: list[str] = []
        drain = threading.Thread(target=lambda: errors.append(encode.stderr.read()), daemon=True)  # type: ignore[union-attr]
        drain.start()
        shown = 0.0
        for line in encode.stdout:
            if line.startswith("frame="):
                try:
                    done = int(line.split("=", 1)[1]) / max(1, total)
                except ValueError:
                    continue
                if done - shown >= 0.02:
                    shown = done
                    yield progress(0.22 + 0.76 * min(1.0, done), f"Encoding the video… {round(done * 100)}%")
        code = encode.wait()
        drain.join()
        if code != 0:
            yield {"event": "result", "ok": False, "error": f"ffmpeg encode failed: {''.join(errors)[-600:]}"}
            return
        timings["encode"] = round(time.time() - e0, 1)
        dest = clip_dir / "render.mp4"
        part = clip_dir / "render.part.mp4"
        shutil.copyfile(out, part)
        part.replace(dest)
    seconds = round(time.time() - t0, 1)
    yield {"event": "result", "ok": True, "output": f"studio/clip_{clip:02d}/render.mp4", "seconds": seconds,
           "fps": round(total / seconds, 1), "chunks": len(chunks), "timings": timings, "remotion_frames": frames}


def chunk_ranges(total: int, max_chunks: int = 40, min_frames: int = 150) -> list[tuple[int, int]]:
    # Every chunk is a container that has to start: for short clips, fewer and
    # longer chunks cost less for the same frames, at a slightly slower render.
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
    long_video = is_long_video(spec)
    if long_video:
        extra = remotion_ranges(spec)
        if extra != [(0, total - 1)]:
            yield from _render_mostly_plain(job_dir, clip, chunk_map, spec, total, extra)
            return
    # An hour of frames would run into a chunk's time limit at the usual 40 chunks.
    ranges = chunk_ranges(total, max_chunks=200) if long_video else chunk_ranges(total)

    def progress(fraction: float, message: str) -> dict:
        return {"event": "progress", "stage": "render", "fraction": fraction, "message": message}

    yield progress(0.02, f"Rendering {total} frames in {len(ranges)} parallel chunks…")
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        audio_err: list[str] = []

        timings: dict[str, float] = {}

        def audio() -> None:
            a0 = time.time()
            try:
                _soundtrack(spec, Path(job_dir), tmp, total)
            except Exception as err:  # noqa: BLE001
                audio_err.append(str(err)[-600:])
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
