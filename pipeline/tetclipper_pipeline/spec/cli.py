"""`tetclipper spec …` — build, inspect, validate, undo and render clip specs.

These are the verbs Claude Code (Studio chat) and the editor server call.
Output is JSON on stdout except `show --transcript`, which prints the
transcript.md text.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import build as build_mod
from . import store


def add_parser(sub) -> None:
    p = sub.add_parser("spec", help="Studio clip specs (build / show / validate / undo)")
    spec_sub = p.add_subparsers(dest="spec_cmd", required=True)

    p_build = spec_sub.add_parser("build", help="write studio/clip_NN/spec.json from the job's analysis")
    p_build.add_argument("job_id")
    p_build.add_argument("--clip", type=int, default=None, help="clip index (default: every clip)")
    p_build.add_argument("--style", choices=build_mod.CAPTION_STYLES, default=None)
    p_build.add_argument("--no-camera", action="store_true", help="centre crop, skip camera directing")
    p_build.add_argument("--force", action="store_true", help="rebuild even if a spec exists (drops edits)")

    p_show = spec_sub.add_parser("show", help="print a clip's spec path + summary (JSON)")
    p_show.add_argument("job_id")
    p_show.add_argument("--clip", type=int, default=0)
    p_show.add_argument("--transcript", action="store_true", help="print transcript.md instead")

    p_val = spec_sub.add_parser("validate", help="check spec.json after a direct edit; restores the last good one if invalid")
    p_val.add_argument("job_id")
    p_val.add_argument("--clip", type=int, default=0)
    p_val.add_argument("--reason", default="edited")

    p_undo = spec_sub.add_parser("undo", help="restore the previous version of a clip's spec")
    p_undo.add_argument("job_id")
    p_undo.add_argument("--clip", type=int, default=0)

    p_dead = spec_sub.add_parser("dead-air", help="find (or with --apply, cut) long pauses and um/uh fillers")
    p_dead.add_argument("job_id")
    p_dead.add_argument("--clip", type=int, default=0)
    p_dead.add_argument("--mode", choices=["natural", "tight"], default="natural")
    p_dead.add_argument("--fillers", action="store_true", help="also cut isolated um/uh/erm/ah/hmm")
    p_dead.add_argument("--apply", action="store_true", help="add the cuts to the spec (one Undo reverts)")

    p_doubts = spec_sub.add_parser("doubts", help="re-check captions: flag doubtful spans + Swahili second listen")
    p_doubts.add_argument("job_id")
    p_doubts.add_argument("--clip", type=int, default=0)

    p_render = spec_sub.add_parser("render", help="render a clip's spec to studio/clip_NN/render.mp4 (Remotion)")
    p_render.add_argument("job_id")
    p_render.add_argument("--clip", type=int, default=0)

    p.set_defaults(fn=run)

    p_find = sub.add_parser("find", help="auto-find the best moments (Claude Code judges) and make Studio clips")
    p_find.add_argument("source", help="YouTube URL, video file, or an existing job id")
    p_find.add_argument("start", nargs="?", default=None, help="optional: only search from here (12:30)")
    p_find.add_argument("end", nargs="?", default=None, help="optional: …to here (45:00)")
    p_find.add_argument("--top", type=int, default=5, help="how many clips to make (default 5)")
    p_find.add_argument("--captions", choices=build_mod.CAPTION_STYLES, default=None)
    p_find.add_argument("--language", default="auto", help="speech language: en, sw, … or auto")
    p_find.add_argument("--cloud", dest="cloud", action="store_true", default=None)
    p_find.add_argument("--local", dest="cloud", action="store_false")
    p_find.set_defaults(fn=run_find)


def _summary(job_dir: Path, clip_idx: int, spec: dict) -> dict:
    src = spec["source"]
    return {
        "clip": clip_idx,
        "path": str(store.spec_path(job_dir, clip_idx)),
        "transcript": str(store.clip_dir(job_dir, clip_idx) / "transcript.md"),
        "range": [src["start"], src["end"]],
        "style": spec.get("captions", {}).get("style"),
        "intro": bool(spec.get("intro")),
        "cuts": len(spec.get("cuts", [])),
        "words": len(spec.get("words", [])),
        "keyframes": len(spec.get("crop", {}).get("keyframes", [])),
        "effects": len(spec.get("effects", [])),
        "versions": len(store.history(job_dir, clip_idx)),
    }


def run(args: argparse.Namespace) -> int:
    from ..cli import _emit_result, _progress_printer
    from ..jobs import queue

    job = queue.get_job(args.job_id)
    if job is None:
        print(json.dumps({"ok": False, "error": f"no job {args.job_id}"}))
        return 2
    job_dir = Path(job.dir)

    if args.spec_cmd == "build":
        emit = _progress_printer(args.jsonl)
        score_path = job_dir / "score.json"
        if not score_path.exists():
            _emit_result(args.jsonl, {"ok": False, "error": "This job has no clips yet."})
            return 1
        n = len(json.loads(score_path.read_text(encoding="utf-8"))["data"]["clips"])
        clips = [args.clip] if args.clip is not None else list(range(n))
        built = []
        try:
            for idx in clips:
                spec = build_mod.build(
                    job_dir, idx, style=args.style, camera=not args.no_camera, force=args.force,
                    emit=lambda f, m: emit("spec", f, m),
                )
                built.append(_summary(job_dir, idx, spec))
        except Exception as err:  # noqa: BLE001 — every failure must reach the caller
            _emit_result(args.jsonl, {"ok": False, "job_id": job.id, "error": str(err)})
            return 1
        _emit_result(args.jsonl, {"ok": True, "job_id": job.id, "clips": built})
        return 0

    if args.spec_cmd == "show":
        spec = store.load(job_dir, args.clip)
        if spec is None:
            print(json.dumps({"ok": False, "error": f"no spec for clip {args.clip}; run `tetclipper spec build {job.id}`"}))
            return 1
        if args.transcript:
            print((store.clip_dir(job_dir, args.clip) / "transcript.md").read_text(encoding="utf-8"))
            return 0
        print(json.dumps({"ok": True, **_summary(job_dir, args.clip, spec)}))
        return 0

    if args.spec_cmd == "validate":
        spec, problems = store.sync_from_disk(job_dir, args.clip, args.reason)
        if problems:
            print(json.dumps({
                "ok": False,
                "problems": problems,
                "restored": spec is not None,
                "hint": "spec.json was restored to the last valid version; fix the problems and edit again",
            }))
            return 1
        print(json.dumps({"ok": True, **_summary(job_dir, args.clip, spec)}))
        return 0

    if args.spec_cmd == "dead-air":
        from . import silence

        spec = store.load(job_dir, args.clip)
        if spec is None:
            print(json.dumps({"ok": False, "error": f"no spec for clip {args.clip}"}))
            return 1
        found = silence.find(spec, job_dir, args.mode, args.fillers)
        if args.apply and (found["cuts"] or found["filler_words"]):
            reason = f"remove dead air ({args.mode}): {len(found['cuts'])} cuts, -{found['saved']:.1f}s"
            if found["filler_words"]:
                reason += f", {len(found['filler_words'])} fillers"
            store.save(job_dir, args.clip, silence.apply(spec, found), reason=reason)
        print(json.dumps({"ok": True, "applied": bool(args.apply), "cuts": len(found["cuts"]),
                          "saved_seconds": found["saved"], "fillers": len(found["filler_words"]),
                          "kept_pauses": found["kept"][:20], "new_cuts": found["cuts"][:50]}))
        return 0

    if args.spec_cmd == "doubts":
        emit = _progress_printer(args.jsonl)
        try:
            spec = build_mod.refresh_doubts(job_dir, args.clip, lambda f, m: emit("doubts", f, m))
        except Exception as err:  # noqa: BLE001
            _emit_result(args.jsonl, {"ok": False, "error": str(err)})
            return 1
        _emit_result(args.jsonl, {"ok": True, "doubts": spec["doubts"]})
        return 0

    if args.spec_cmd == "render":
        from . import render as render_mod

        emit = _progress_printer(args.jsonl)
        try:
            out = render_mod.render(job_dir, args.clip, lambda f, m: emit("render", f, m))
        except Exception as err:  # noqa: BLE001
            _emit_result(args.jsonl, {"ok": False, "job_id": job.id, "clip": args.clip, "error": str(err)})
            return 1
        _emit_result(args.jsonl, {"ok": True, "job_id": job.id, "clip": args.clip, "output": str(out)})
        return 0

    if args.spec_cmd == "undo":
        spec = store.undo(job_dir, args.clip)
        if spec is None:
            print(json.dumps({"ok": False, "error": "nothing to undo"}))
            return 1
        print(json.dumps({"ok": True, **_summary(job_dir, args.clip, spec)}))
        return 0
    return 2


def run_find(args: argparse.Namespace) -> int:
    from ..cli import _emit_result, _ensure_pipeline_deps, _parse_clock, _progress_printer
    from ..cloud import client as cloud_client
    from ..jobs import queue
    from . import find

    emit = _progress_printer(args.jsonl)
    section = None
    if args.start is not None and args.end is not None:
        section = [_parse_clock(args.start), _parse_clock(args.end)]
        if section[1] - section[0] < 60:
            _emit_result(args.jsonl, {"ok": False, "error": "Search at least a minute of video."})
            return 2
    job = find.create(args.source, section, args.captions, args.language)
    if args.jsonl:
        print(json.dumps({"event": "job", "job_id": job.id, "dir": str(job.dir)}), flush=True)
    ok, err = _ensure_pipeline_deps(args.jsonl, emit)
    if not ok:
        _emit_result(args.jsonl, {"ok": False, "job_id": job.id, "error": str(err)})
        return 1
    cloud = args.cloud if args.cloud is not None else cloud_client.available()
    try:
        clips = find.run(job, args.top, args.captions, cloud, emit)
    except Exception as err:  # noqa: BLE001 — every failure must reach the app
        queue.set_job_status(job.id, "failed", str(err))
        _emit_result(args.jsonl, {"ok": False, "job_id": job.id, "error": str(err)})
        return 1
    _emit_result(args.jsonl, {"ok": True, "job_id": job.id, "clips": clips})
    return 0
