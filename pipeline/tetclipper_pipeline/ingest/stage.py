"""Ingest stage: URL or file → job-dir media + analysis audio + heatmap.

Artifacts produced in the job dir:
    media.mp4      (URL jobs; file jobs keep the source path unless normalized)
    audio16k.wav   16 kHz mono analysis audio (shared by all M1 models)
    heatmap in the checkpoint data (YouTube most-replayed, when available)
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from ..jobs.queue import Stage, StageContext, StageError
from ..render import ffmpeg_bin
from . import normalize, ytdlp


def _sample_hash(path: Path) -> str:
    """Cheap staleness fingerprint for external source files: size + first MiB."""
    h = hashlib.sha256()
    h.update(str(path.stat().st_size).encode())
    with open(path, "rb") as fh:
        h.update(fh.read(1024 * 1024))
    return h.hexdigest()[:16]


# Seconds of context fetched either side of a requested range, so the cut
# can snap to whole sentences and the speech model hears complete words.
SECTION_PAD = 5.0


def _padded_section(section: list[float] | None) -> tuple[float, float] | None:
    if not section:
        return None
    a, b = float(section[0]), float(section[1])
    return max(0.0, a - SECTION_PAD), b + SECTION_PAD


class IngestStage(Stage):
    name = "ingest"
    schema_version = 1

    def artifacts_ok(self, ctx: StageContext, data: dict) -> bool:
        media = Path(data.get("media_path", ""))
        audio = ctx.job_dir / "audio16k.wav"
        if not (media.exists() and audio.exists()):
            return False
        if data.get("source_hash"):
            try:
                return _sample_hash(media) == data["source_hash"] or media.parent == ctx.job_dir
            except OSError:
                return False
        return True

    def run(self, ctx: StageContext) -> dict:
        job = ctx.job

        def prog(fraction: float, message: str) -> None:
            ctx.emit(fraction, message)

        # Probing the file needs ffmpeg/ffprobe, and a machine that has never
        # had ffmpeg (most Macs) only got one at render time — after ingest,
        # transcription and scoring had already failed on it. Fetch the
        # static build now; a no-op when a caption-capable one already exists.
        ffmpeg_bin.ensure_capable(progress=prog)
        if not ffmpeg_bin.available():
            raise StageError(
                "tetclipper needs ffmpeg and could not find or download one. "
                "Check your internet connection and try again."
            )

        heatmap = None
        title = None
        section = _padded_section(getattr(ctx.settings, "section", None))
        if job.source_type == "url":
            meta = ytdlp.fetch_meta(job.source, prog)
            heatmap = None if section else meta.heatmap  # whole-video data
            title = meta.title
            media_path = ctx.job_dir / "media.mp4"
            if not media_path.exists():
                ytdlp.download(job.source, media_path, prog, section=section, fmt=ytdlp.pick_format(meta, prog))
        elif section:
            src = Path(job.source).expanduser().resolve()
            if not src.exists():
                raise StageError(f"File not found: {src}")
            title = src.stem
            media_path = ctx.job_dir / "media.mp4"
            if not media_path.exists():
                prog(0.5, "Trimming the section…")
                try:
                    normalize.trim(src, media_path, section[0], section[1])
                except normalize.FfmpegError as err:
                    raise StageError(str(err)) from err
        else:
            media_path = Path(job.source).expanduser().resolve()
            if not media_path.exists():
                raise StageError(f"File not found: {media_path}")
            title = media_path.stem
            # A pushed YouTube video (downloaded on the user's machine because
            # the cloud's IP is blocked) carries its title + heatmap alongside.
            sidecar = media_path.with_name(media_path.name + ".meta.json")
            if sidecar.exists():
                import json as _json

                meta_side = _json.loads(sidecar.read_text(encoding="utf-8"))
                title = meta_side.get("title") or title
                heatmap = meta_side.get("heatmap")

        prog(0.96, "Probing media…")
        try:
            info = normalize.probe(media_path)
        except normalize.FfmpegError as err:
            raise StageError(str(err)) from err
        if not info.has_audio:
            raise StageError(
                "This video has no audio track. tetclipper needs speech to find moments."
            )

        if info.vfr:
            cfr_path = ctx.job_dir / "media_cfr.mp4"
            try:
                if not cfr_path.exists():
                    normalize.normalize_to_cfr(media_path, cfr_path, info.fps, prog)
                media_path = cfr_path
                info = normalize.probe(media_path)
            except normalize.FfmpegError as err:
                raise StageError(str(err)) from err

        prog(0.98, "Extracting analysis audio…")
        audio_path = ctx.job_dir / "audio16k.wav"
        try:
            if not audio_path.exists():
                normalize.extract_analysis_audio(media_path, audio_path)
        except normalize.FfmpegError as err:
            raise StageError(str(err)) from err

        from ..jobs import queue as jobs_queue

        jobs_queue.set_job_status(job.id, "running", title=title)

        source_hash = None
        if job.source_type == "file":
            source_hash = _sample_hash(media_path)

        return {
            "media_path": str(media_path),
            "audio_path": str(audio_path),
            "title": title,
            # Where media.mp4 starts in the original video (range jobs).
            "section_offset": section[0] if section else 0.0,
            "probe": info.to_json(),
            "heatmap": heatmap,
            "source_hash": source_hash,
        }
