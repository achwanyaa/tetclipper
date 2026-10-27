"""tetclipper CLI.

With --jsonl every progress event and the final result are emitted as one
JSON object per stdout line; the Studio server (server/app.py) spawns
`tetclipper --jsonl …` and streams them to the browser.

  cut    one exact range → a Studio clip            find   best moments → clips
  spec   build / edit / check / render clip specs    serve  the Studio editor
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import config
from .jobs import queue


def _stages() -> list[queue.Stage]:
    """ingest → asr → diarize → events → candidates → score. Range cuts use
    the first four; `find` uses all six. Imports are deferred so cheap
    commands don't pay the torch import tax."""
    from .asr.stage import AsrStage
    from .candidates.stage import CandidatesStage
    from .diarize.stage import DiarizeStage
    from .events.stage import EventsStage
    from .ingest.stage import IngestStage
    from .scoring.stage import ScoreStage

    return [IngestStage(), AsrStage(), DiarizeStage(), EventsStage(), CandidatesStage(), ScoreStage()]


def _progress_printer(jsonl: bool):
    def emit(stage: str, fraction: float, message: str) -> None:
        if jsonl:
            print(
                json.dumps(
                    {"event": "progress", "stage": stage, "fraction": fraction, "message": message}
                ),
                flush=True,
            )
        else:
            pct = f"{fraction * 100:5.1f}%" if fraction >= 0 else "  ...."
            print(f"[{stage:<10}] {pct} {message}", file=sys.stderr, flush=True)

    return emit


def _emit_result(jsonl: bool, payload: dict) -> None:
    if jsonl:
        print(json.dumps({"event": "result", **payload}), flush=True)
    else:
        print(json.dumps(payload, indent=2))


def _uv_binary() -> str:
    """The uv that runs the one-time dependency sync.

    A desktop launch (Finder, the Start menu) hands the app a bare PATH —
    /usr/bin:/bin:/usr/sbin:/sbin on macOS — so a uv installed anywhere a
    terminal would find it is invisible here, and looking it up by name is
    exactly how a packaged app died on first run with `No such file or
    directory: 'uv'`. The shell passes the uv it bundles as TETCLIPPER_UV;
    `uv run` also exports its own path as UV; PATH is the last resort (dev
    shells, CI).
    """
    import os
    import shutil

    for var in ("TETCLIPPER_UV", "UV"):
        candidate = os.environ.get(var)
        if candidate and os.path.exists(candidate):
            return candidate
    return shutil.which("uv") or "uv"


def _ensure_group_deps(
    group: str, marker_name: str, exact: bool, emit, message: str
) -> tuple[bool, str | None]:
    """Sync one uv dependency-group into the app's env, once, as a reportable
    step. `exact=False` passes `--inexact`, so syncing a small group never
    uninstalls a bigger one that is already in (uv sync makes the env match
    exactly by default)."""
    import subprocess
    from pathlib import Path

    marker = config.home_dir() / marker_name
    if marker.exists():
        return True, None

    emit("env", -1, message)
    pipeline_dir = Path(__file__).resolve().parent.parent
    uv_bin = _uv_binary()
    label = f"`uv sync --group {group}`"
    # --frozen for the same reason main.rs passes it: in a packaged build
    # pipeline_dir is inside the app bundle, and re-locking would write
    # uv.lock there. UV_PROJECT_ENVIRONMENT (set by the shell that spawned
    # us) keeps the venv itself out too.
    args = [uv_bin, "--directory", str(pipeline_dir), "sync", "--frozen"]
    if not exact:
        args.append("--inexact")
    args += ["--group", group]
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=3600)
    except Exception as err:  # noqa: BLE001 — surface, don't crash silently
        return False, f"could not start {label}: {err}"

    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or proc.stdout or "").strip().splitlines()[-12:])
        return False, tail or f"{label} exited {proc.returncode}"

    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("ok")
    except OSError:
        pass  # best-effort cache; a missing marker just re-syncs (fast, no-op) next run
    return True, None


def _ensure_pipeline_deps(jsonl: bool, emit) -> tuple[bool, str | None]:
    """First-run bootstrap for the `pipeline` dependency-group (whisperx,
    torch-via-whisperx, opencv, speechbrain, ...).

    That group is deliberately NOT one of uv's default-groups (see
    pyproject.toml) — a bare `uv run tetclipper ...` (exactly what
    Studio's server spawns) would otherwise try to sync it, and every
    dependency in the whole graph, before `main()` gets to run at all: if
    that opaque pre-launch sync fails (no network, a blocked host, a first
    run interrupted), the child exits non-zero having written to stdout
    only ever once `job` has already been printed by `_execute()` below.

    Returns (ok, error_message). On failure, error_message is the real
    stderr tail from `uv sync`, suitable for `_emit_result`.
    """
    del jsonl  # progress goes through `emit`, which already knows the mode
    return _ensure_group_deps(
        "pipeline",
        ".pipeline_deps_synced",
        True,
        emit,
        "Installing pipeline dependencies (one-time setup)…",
    )


def _ensure_net_deps(jsonl: bool, emit) -> tuple[bool, str | None]:
    """The `net` group (httpx) for the `audio …` and `brain …` commands,
    whose modules import httpx at load.

    Before the first clip job has run `_ensure_pipeline_deps`, httpx is not
    in the env at all, so those commands died on a fresh install with
    `No module named 'httpx'`. This
    group is a few small pure-Python packages, so syncing it on demand costs
    seconds, not the pipeline group's multi-GB download. `--inexact` (see
    `_ensure_group_deps`) is what keeps this sync from uninstalling the
    pipeline group once that is in; the pipeline group includes `net`, so
    its marker means this one is already satisfied.
    """
    del jsonl
    if (config.home_dir() / ".pipeline_deps_synced").exists():
        return True, None
    return _ensure_group_deps(
        "net",
        ".net_deps_synced",
        False,
        emit,
        "Installing the app's network library (one-time setup)…",
    )


def _net_ready(args: argparse.Namespace) -> bool:
    """Gate for `audio`: run the one-time `net` sync first and, when it
    cannot happen, answer with one JSON error line instead of a traceback."""
    ok, err = _ensure_net_deps(args.jsonl, _progress_printer(args.jsonl))
    if ok:
        return True
    message = f"Couldn't install the app's network library (one-time setup): {err}"
    print(json.dumps({"ok": False, "error": message}), flush=True)
    return False


def cmd_resume(args: argparse.Namespace) -> int:
    """Finish a range job that stopped part-way (every finished stage is cached)."""
    job = queue.get_job(args.job_id)
    if job is None:
        print(f"No job {args.job_id}", file=sys.stderr)
        return 2
    if not config.Settings.from_json(json.loads(job.settings_json)).section:
        print("Only range jobs resume; run `tetclipper find` again for a find job.", file=sys.stderr)
        return 2
    from .cloud import client as cloud_client

    return _run_range(job, args.jsonl, args.captions, None, cloud=cloud_client.available())


def cmd_jobs(args: argparse.Namespace) -> int:
    for job in queue.list_jobs():
        stages = queue.stage_statuses(job.id)
        done = sum(1 for s in stages.values() if s == "done")
        print(f"{job.id}  {job.status:<8} {done} stage(s) done  {job.title or job.source}")
    return 0


def cmd_brain(args: argparse.Namespace) -> int:
    """The Claude Code side of llm_mode "claude" (see scoring/brain.py)."""
    from pathlib import Path

    ok, err = _ensure_net_deps(False, _progress_printer(False))
    if not ok:
        print(f"Couldn't install dependencies: {err}", file=sys.stderr)
        return 1
    from .scoring import brain

    job = queue.get_job(args.job_id)
    if job is None:
        print(f"No job {args.job_id}", file=sys.stderr)
        return 2
    request = brain.load_request(job.dir)
    if args.brain_cmd == "show":
        if request is None:
            print(f"Job {job.id} is not waiting for Claude Code.")
            return 0
        print(brain.render_request(request))
        return 0
    answers = json.loads(Path(args.answers).read_text(encoding="utf-8"))
    report = brain.apply_answers(job.dir, answers)
    print(json.dumps(report))
    if report["missing"] or report["errors"]:
        return 1
    print("All answers stored.", file=sys.stderr)
    return 0


def cmd_telegram(args: argparse.Namespace) -> int:
    """Deliver clips to a Telegram chat (JSON on stdout, like edit/ig/audio)."""
    if not _net_ready(args):
        return 1
    from .delivery import telegram as tg

    try:
        if args.tg_cmd == "status":
            out = tg.status()
        elif args.tg_cmd == "token":
            out = tg.save_token(args.token)
        elif args.tg_cmd == "link":
            out = tg.link_chat()
        else:
            job = queue.get_job(args.job_id)
            if job is None:
                print(json.dumps({"ok": False, "error": f"no job {args.job_id}"}))
                return 2
            from .spec import store as spec_store

            path = spec_store.clip_dir(job.dir, args.clip) / "render.mp4"
            if not path.exists():
                print(json.dumps({"ok": False, "error": f"clip {args.clip} is not rendered"}))
                return 2
            caption = args.caption or f"{job.title or job.id} · clip {args.clip + 1}"
            out = tg.send_clip(path, caption)
    except tg.TelegramError as err:
        print(json.dumps({"ok": False, "error": str(err)}))
        return 1
    print(json.dumps({"ok": True, **out}))
    return 0


def _parse_clock(text: str) -> float:
    """'12:30', '1:02:03', '750' or '750.5' → seconds."""
    parts = [float(p) for p in str(text).strip().split(":")]
    if not 1 <= len(parts) <= 3 or any(p < 0 for p in parts):
        raise argparse.ArgumentTypeError(f"bad time {text!r}: use 12:30, 1:02:03 or seconds")
    total = 0.0
    for p in parts:
        total = total * 60 + p
    return total


def cmd_cut(args: argparse.Namespace) -> int:
    """Range mode: fetch only [start, end] of a video (+ a little padding),
    analyse just that slice, and cut it into one clip. No scoring, no full
    download; fast enough on a laptop CPU."""
    start, end = args.start, args.end
    if end <= start:
        _emit_result(args.jsonl, {"ok": False, "error": "The end time must be after the start."})
        return 2
    source = args.source
    source_type = "url" if source.startswith(("http://", "https://")) else "file"
    settings = config.Settings()
    settings.llm_mode = "claude"  # never called: range jobs skip scoring
    if args.captions:
        settings.caption_preset = args.captions
    if args.camera:
        settings.camera.speaker_change = args.camera
    settings.section = [start, end]
    if args.language and args.language != "auto":
        settings.language = args.language
    job = queue.create_job(source_type, source, json.dumps(settings.to_json()))
    from .cloud import client as cloud_client

    cloud = args.cloud if args.cloud is not None else cloud_client.available()
    return _run_range(job, args.jsonl, args.captions, args.camera, cloud=cloud)


def _run_range(job: queue.Job, jsonl: bool, captions: str | None = None, camera: str | None = None,
               cloud: bool = False) -> int:
    """Analyse a range job's slice (no scoring) and build its clip spec, unless
    that exists. Shared by `cut` and `resume` of a range job. With cloud=True
    only the download runs here; analysis + camera run on a Modal GPU."""
    settings = config.Settings.from_json(json.loads(job.settings_json))
    start, end = settings.section or (0.0, 0.0)
    emit = _progress_printer(jsonl)
    if jsonl:
        print(json.dumps({"event": "job", "job_id": job.id, "dir": str(job.dir)}), flush=True)
    ok, err = _ensure_pipeline_deps(jsonl, emit)
    if not ok:
        queue.set_job_status(job.id, "failed", str(err))
        _emit_result(jsonl, {"ok": False, "job_id": job.id, "error": str(err)})
        return 1
    from .edits import manual

    analysis = [s for s in _stages() if s.name in ("ingest", "asr", "diarize", "events")]
    try:
        if cloud and not (job.dir / "studio").exists():
            from .cloud import client as cloud_client

            queue.run_stages(job, analysis[:1], emit)  # the download stays on this PC
            queue.set_job_status(job.id, "running")
            job = queue.get_job(job.id) or job
            cloud_client.analyze(job, start, end, captions, emit)
            job = queue.get_job(job.id) or job
        results = queue.run_stages(job, analysis, emit)
        queue.set_job_status(job.id, "running")  # run_stages says done; the cut is still to come
        offset = float(results["ingest"].get("section_offset", 0.0))
        job = queue.get_job(job.id) or job
        # Studio: a range job ends at a clip spec (previewed live, rendered by
        # Remotion) instead of an ffmpeg render. Re-runs reuse the clip/spec.
        from .spec import build as spec_build
        from .spec import store as spec_store

        clips = spec_store.list_clips(job.dir)
        if clips:
            idx = clips[0]
        else:
            idx = manual.add_range(
                job, start - offset, end - offset, lambda f, m: emit("spec", f, m),
                caption_preset=captions, camera_mode=camera,
            )["clip_index"]
        spec_build.build(job.dir, idx, style=captions, emit=lambda f, m: emit("spec", f, m))
        entry = {"clip_index": idx, "spec": str(spec_store.spec_path(job.dir, idx))}
    except Exception as err:  # noqa: BLE001 — every failure must reach the app
        failed = queue.get_job(job.id)
        error = failed.error if failed and failed.error else str(err)
        _emit_result(jsonl, {"ok": False, "job_id": job.id, "error": error})
        return 1
    queue.set_job_status(job.id, "done", None)
    _emit_result(jsonl, {"ok": True, "job_id": job.id, "output": entry, "manual": True})
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """Browser UI + HTTP API (needs the `server` group: `uv run --group server tetclipper serve`)."""
    from .server.app import serve

    serve(args.host, args.port)
    return 0


def cmd_audio(args: argparse.Namespace) -> int:
    """Local music/SFX library — local import + CC-licensed online sources.
    import/remove/tag/fetch are always JSON (edit_tool's convention);
    list/search default to human-readable lines, --json switches them
    over for the app."""
    if not _net_ready(args):
        return 1
    from dataclasses import asdict

    from .audio_library import library
    from .audio_library.sources import MissingKeyError
    from .audio_library.sources.registry import SOURCES

    if args.audio_cmd == "import":
        items = library.import_paths(args.paths, kind=args.kind)
        print(json.dumps({"ok": True, "items": [i.to_json() for i in items]}))
        return 0

    if args.audio_cmd == "list":
        items = library.list_items(kind=args.kind, query=args.query)
        if args.json:
            print(json.dumps({"ok": True, "items": [i.to_json() for i in items]}))
        else:
            for i in items:
                bpm = f"{i.bpm:.0f}bpm" if i.bpm else "-"
                print(
                    f"{i.id}  {i.kind:<5} {i.duration:6.1f}s {bpm:>7}  "
                    f"{i.licence or 'local':<10} {i.name}  [{', '.join(i.tags)}]"
                )
        return 0

    if args.audio_cmd == "remove":
        removed = library.remove_item(args.item_id)
        print(json.dumps({"ok": removed}))
        return 0 if removed else 2

    if args.audio_cmd == "tag":
        item = library.update_tags(args.item_id, args.tags)
        if item is None:
            print(json.dumps({"ok": False, "error": f"no item {args.item_id}"}))
            return 2
        print(json.dumps({"ok": True, "item": item.to_json()}))
        return 0

    if args.audio_cmd == "search":
        source_names = list(SOURCES) if args.source == "all" else [args.source]
        max_duration = args.max_duration
        # Freesound has no sound-effect facet to filter on server-side — a
        # short default cap keeps --kind sfx results actually sfx-shaped.
        if max_duration is None and args.kind == "sfx":
            max_duration = 20.0
        results = []
        errors = []
        for name in source_names:
            try:
                results.extend(
                    SOURCES[name].search(
                        args.query, kind=args.kind,
                        max_duration=max_duration, allow_attribution=args.allow_attribution,
                    )
                )
            except MissingKeyError as err:
                errors.append(str(err))
        if errors and not results:
            message = "; ".join(errors)
            if args.json:
                print(json.dumps({"ok": False, "error": message}))
            else:
                print(message, file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps({"ok": True, "results": [asdict(r) for r in results]}))
        else:
            for r in results:
                print(
                    f"{r.source:<9} {r.source_id:<10} {r.duration:6.1f}s  "
                    f"{r.licence:<10} {r.name}  ({r.attribution})"
                )
        return 0

    if args.audio_cmd == "fetch":
        mod = SOURCES.get(args.source)
        if mod is None:
            print(json.dumps({"ok": False, "error": f"unknown source {args.source!r}"}))
            return 2
        try:
            result = mod.get(args.source_id)
        except MissingKeyError as err:
            print(json.dumps({"ok": False, "error": str(err)}))
            return 2
        if result is None:
            print(json.dumps({"ok": False, "error": f"{args.source} {args.source_id} not found, or its licence isn't CC0/CC-BY"}))
            return 2
        item = mod.download(result)
        print(json.dumps({"ok": True, "item": item.to_json()}))
        return 0

    if args.audio_cmd == "bootstrap":
        from .audio_library import starter_pack

        emit = _progress_printer(args.jsonl)
        items = starter_pack.bootstrap(lambda f, m: emit("bootstrap", f, m))
        _emit_result(args.jsonl, {"ok": True, "items": [i.to_json() for i in items]})
        return 0
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tetclipper")
    parser.add_argument("--jsonl", action="store_true", help="machine-readable progress on stdout")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_resume = sub.add_parser("resume", help="finish a range job that stopped part-way")
    p_resume.add_argument("job_id")
    p_resume.add_argument("--captions", default=None, help="caption style")
    p_resume.set_defaults(fn=cmd_resume)

    p_jobs = sub.add_parser("jobs", help="list jobs")
    p_jobs.set_defaults(fn=cmd_jobs)

    p_brain = sub.add_parser("brain", help="Claude Code as the judge for `find` (show / answer pending prompts)")
    brain_sub = p_brain.add_subparsers(dest="brain_cmd", required=True)
    p_bshow = brain_sub.add_parser("show", help="print the prompts a paused job is waiting on")
    p_bshow.add_argument("job_id")
    p_bans = brain_sub.add_parser("answer", help="store answers ({id: answer} JSON) for a paused job")
    p_bans.add_argument("job_id")
    p_bans.add_argument("answers")
    p_brain.set_defaults(fn=cmd_brain)

    p_tg = sub.add_parser("telegram", help="send rendered clips to a Telegram chat via your bot")
    tg_sub = p_tg.add_subparsers(dest="tg_cmd", required=True)
    tg_sub.add_parser("status", help="token / linked chat (JSON)")
    p_tg_tok = tg_sub.add_parser("token", help="save the @BotFather token")
    p_tg_tok.add_argument("token")
    tg_sub.add_parser("link", help="remember the chat that last messaged the bot")
    p_tg_send = tg_sub.add_parser("send", help="send one rendered clip")
    p_tg_send.add_argument("job_id")
    p_tg_send.add_argument("clip", type=int)
    p_tg_send.add_argument("--caption", default=None)
    p_tg.set_defaults(fn=cmd_telegram)

    p_cut = sub.add_parser("cut", help="fetch only START-END of a video and make it a Studio clip")
    p_cut.add_argument("source", help="YouTube URL or local video file")
    p_cut.add_argument("start", type=_parse_clock, help="e.g. 12:30")
    p_cut.add_argument("end", type=_parse_clock, help="e.g. 13:15")
    p_cut.add_argument("--captions", choices=["classic", "beast", "hormozi", "minimal", "karaoke-pop", "sermon", "one-word", "boxed", "neon"], default=None)
    p_cut.add_argument("--camera", choices=["cut", "pan", "locked"], default=None)
    p_cut.add_argument("--language", default="auto", help="speech language: en, sw, … or auto")
    p_cut.add_argument("--cloud", dest="cloud", action="store_true", default=None,
                       help="analyse on the Modal GPU (default when Modal is set up)")
    p_cut.add_argument("--local", dest="cloud", action="store_false", help="analyse on this machine")
    p_cut.set_defaults(fn=cmd_cut)

    p_serve = sub.add_parser("serve", help="run Studio (http://localhost:8765/studio/) + the API")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8765)
    p_serve.set_defaults(fn=cmd_serve)

    from .spec import cli as spec_cli

    spec_cli.add_parser(sub)

    p_audio = sub.add_parser("audio", help="local music/SFX library")
    audio_sub = p_audio.add_subparsers(dest="audio_cmd", required=True)

    p_a_import = audio_sub.add_parser("import", help="import local files or folders")
    p_a_import.add_argument("paths", nargs="+")
    p_a_import.add_argument("--kind", choices=["auto", "music", "sfx"], default="auto")

    p_a_list = audio_sub.add_parser("list", help="list library items")
    p_a_list.add_argument("--kind", choices=["music", "sfx"], default=None)
    p_a_list.add_argument("--query", default=None)
    p_a_list.add_argument("--json", action="store_true")

    p_a_remove = audio_sub.add_parser("remove", help="remove a library item")
    p_a_remove.add_argument("item_id")

    p_a_tag = audio_sub.add_parser("tag", help="set an item's tags")
    p_a_tag.add_argument("item_id")
    p_a_tag.add_argument("tags", nargs="+")

    p_a_search = audio_sub.add_parser("search", help="search CC-licensed online sources")
    p_a_search.add_argument("query")
    p_a_search.add_argument("--source", choices=["freesound", "jamendo", "all"], default="all")
    p_a_search.add_argument("--kind", choices=["music", "sfx"], default="music")
    p_a_search.add_argument("--max-duration", type=float, default=None)
    p_a_search.add_argument("--allow-attribution", action="store_true")
    p_a_search.add_argument("--json", action="store_true")

    p_a_fetch = audio_sub.add_parser("fetch", help="download one known online item by id")
    p_a_fetch.add_argument("source", choices=["freesound", "jamendo"])
    p_a_fetch.add_argument("source_id")

    audio_sub.add_parser("bootstrap", help="fetch a curated CC0 starter pack (music + sfx)")

    p_audio.set_defaults(fn=cmd_audio)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
