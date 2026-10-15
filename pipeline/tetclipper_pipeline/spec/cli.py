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

    p_render = spec_sub.add_parser("render", help="render a clip's spec to studio/clip_NN/render.mp4 (Remotion)")
    p_render.add_argument("job_id")
    p_render.add_argument("--clip", type=int, default=0)

    p.set_defaults(fn=run)


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
