"""`tetclipper find`: auto-find the best moments and turn them into Studio clips.

  download (this PC) → ASR, diarize, events, candidates (Modal GPU or here)
  → scoring with Claude Code as the judge (headless, this PC)
  → smart camera + spec for the top N (one Modal container per clip, or here)

Finding moments inside an existing job starts a new job that reuses that
job's download and analysis (copied, paths rewritten), so its clips stay put.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Callable

from .. import config
from ..jobs import queue

ANALYSIS = ["ingest", "asr", "diarize", "events", "candidates"]
REUSE = ["media.mp4", "audio16k.wav", "ingest.json", "asr.json", "diarize.json", "events.json",
         "curves.json", "diar_embeddings.npy"]
MAX_ROUNDS = 3

Emit = Callable[[str, float, str], None]


def job_from_existing(src_job: queue.Job) -> queue.Job:
    """A fresh find job over the same slice, seeded with src_job's analysis."""
    settings = json.loads(src_job.settings_json)
    settings["llm_mode"] = "claude"
    job = queue.create_job(src_job.source_type, src_job.source, json.dumps(settings))
    src_dir, dst_dir = Path(src_job.dir), Path(job.dir)
    dst_dir.mkdir(parents=True, exist_ok=True)
    for name in REUSE:
        src = src_dir / name
        if not src.exists():
            continue
        if src.suffix == ".json":
            text = src.read_text(encoding="utf-8")
            # absolute paths inside checkpoints point at the old job's folder
            for old, new in ((str(src_dir), str(dst_dir)), (str(src_dir).replace("\\", "\\\\"), str(dst_dir).replace("\\", "\\\\"))):
                text = text.replace(old, new)
            (dst_dir / name).write_text(text, encoding="utf-8")
        else:
            shutil.copyfile(src, dst_dir / name)
    return queue.get_job(job.id) or job


def run(job: queue.Job, top: int, captions: str | None, cloud: bool, emit: Emit) -> list[int]:
    """Analyse, score and build specs for the top clips. Returns their indices."""
    from .. import cli
    from ..scoring import auto_brain
    from ..scoring.brain import AwaitingBrain
    from . import build as spec_build

    os.environ["TETCLIPPER_MUSIC_BRIEFS"] = "0"  # Studio picks music itself; skip that Claude round
    job_dir = Path(job.dir)
    stages = {s.name: s for s in cli._stages()}  # noqa: SLF001
    analysis = [stages[n] for n in ANALYSIS]

    if cloud and not (job_dir / "candidates.json").exists():
        from ..cloud import client

        queue.run_stages(job, analysis[:1], emit)  # the download stays on this PC
        client.analyze(queue.get_job(job.id) or job, None, None, captions, emit, stages=ANALYSIS)
        job = queue.get_job(job.id) or job

    for _ in range(MAX_ROUNDS):
        try:
            queue.run_stages(job, [*analysis, stages["score"]], emit)
            break
        except AwaitingBrain:
            auto_brain.answer(job_dir, lambda f, m: emit("judge", f, m))
            job = queue.get_job(job.id) or job
    else:
        raise RuntimeError("Claude Code didn't finish judging the moments.")

    clips = json.loads((job_dir / "score.json").read_text(encoding="utf-8"))["data"]["clips"]
    chosen = list(range(min(top, len(clips))))  # finalists are sorted best-first
    if cloud:
        from ..cloud import client

        client.build_specs(job_dir, chosen, captions, emit)
    else:
        for i in chosen:
            spec_build.build(job_dir, i, style=captions, emit=lambda f, m: emit("spec", f, m))
    queue.set_job_status(job.id, "done", None)
    return chosen


def create(source: str, section: list[float] | None, captions: str | None, language: str | None) -> queue.Job:
    """A new find job for a URL/file (optionally only a section of it), or a job
    seeded from an existing job when `source` is a job id."""
    existing = queue.get_job(source)
    if existing is not None:
        return job_from_existing(existing)
    settings = config.Settings()
    settings.llm_mode = "claude"
    if captions:
        settings.caption_preset = captions
    if section:
        settings.section = section
    if language and language != "auto":
        settings.language = language
    source_type = "url" if source.startswith(("http://", "https://")) else "file"
    return queue.create_job(source_type, source, json.dumps(settings.to_json()))
