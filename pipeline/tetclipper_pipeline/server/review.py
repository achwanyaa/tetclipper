"""Review: editors send a rendered clip, the communication team marks it Good or
Needs work (with notes), and good videos are downloaded and posted by hand.

Everything is files on the shared home, next to the music library:

  home/review/items/<id>.json        one per clip sent for review
  home/review/files/<id>/v<N>.mp4    the render as it was sent (only the newest kept)
  home/review/files/<id>/thumb.jpg   its card picture

A copy of the render is kept because the editor can re-render while someone is
watching. The item id is the owner's user id, the job and the clip, so one
clip has one review item across its versions.

Roles come from server/app.py: admin, reviewer (communication team), editor.
Editors see their own items; reviewers and admins see everyone's. Every
command checks this itself.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from fastapi.responses import FileResponse

from ..spec import store
from .app import CommandError, actor, app, command, home_dir

STATUSES = ("to_review", "needs_work", "good")
NOTE_MAX = 2000
NOTES_MAX = 40
_lock = threading.Lock()  # one web container in normal use (modal_app.py); this guards read-modify-write in it
_ID = re.compile(r"^[A-Za-z0-9_-]{1,200}$")


def review_dir() -> Path:
    return home_dir() / "review"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _safe(part: str) -> str:
    return re.sub(r"[^A-Za-z0-9-]", "", part)[:80]


def item_id(owner_id: str, job_id: str, clip: int) -> str:
    return f"{_safe(owner_id)}__{_safe(job_id)}__{int(clip)}"


def _item_path(item_id: str) -> Path:
    if not _ID.match(item_id):
        raise CommandError("no such video")
    return review_dir() / "items" / f"{item_id}.json"


def _files(item_id: str) -> Path:
    return review_dir() / "files" / item_id


def load(item_id: str) -> dict | None:
    path = _item_path(item_id)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save(item: dict) -> dict:
    """Write atomically: a reader never sees half a file."""
    item["updated"] = _now()
    path = _item_path(item["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(item, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
    return item


def all_items() -> list[dict]:
    root = review_dir() / "items"
    out = []
    for path in root.glob("*.json") if root.is_dir() else []:
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return sorted(out, key=lambda i: i.get("updated", ""), reverse=True)


def _who(user: dict) -> dict:
    return {"id": user["id"], "name": user.get("name") or "Someone", "email": user.get("email") or ""}


def _is_reviewer(user: dict) -> bool:
    return user["role"] in ("admin", "reviewer")


def _may_see(user: dict, item: dict) -> bool:
    return _is_reviewer(user) or item["owner"]["id"] == user["id"]


def _get_for(user: dict, item_id: str) -> dict:
    item = load(item_id)
    if item is None or not _may_see(user, item):
        raise CommandError("no such video")
    return item


def current_file(item: dict) -> Path | None:
    path = _files(item["id"]) / f"v{item['version']}.mp4"
    return path if path.is_file() else None


def summary(item: dict) -> dict:
    """What the list and the record need, without the full event log."""
    versions = item.get("versions") or [{}]
    events = item.get("events") or []
    downloads = [e for e in events if e["kind"] == "downloaded"]
    return {
        **{k: item.get(k) for k in ("id", "owner", "jobId", "clip", "title", "format", "seconds", "status", "version", "reviewer", "updated")},
        "sentAt": versions[-1].get("sentAt"),
        "message": versions[-1].get("message"),
        "sentBack": sum(1 for e in events if e["kind"] == "needs_work"),
        "goodFirstTime": item.get("status") == "good" and not any(e["kind"] == "needs_work" for e in events),
        "openNotes": sum(1 for n in item.get("notes", []) if not n.get("fixed")),
        "lastDownload": downloads[-1] if downloads else None,
        "firstSent": versions[0].get("sentAt") if versions else None,
    }


# ---------- commands ----------

@command
def review_submit(jobId: str, clip: int, message: str | None = None) -> dict:
    """Send this clip's latest render for review (a new version if it was sent before)."""
    from .studio import _job_dir, _title, thumbnail
    from ..spec.timeline import FPS, total_frames

    user = actor()
    job_dir = _job_dir(jobId)  # your own workspace only
    spec = store.load(job_dir, clip)
    render_info = json.loads((store.clip_dir(job_dir, clip) / "render.json").read_text(encoding="utf-8")) if (store.clip_dir(job_dir, clip) / "render.json").exists() else None
    render = store.clip_dir(job_dir, clip) / "render.mp4"
    history = store.history(job_dir, clip)
    latest = history[-1]["version"] if history else None
    if spec is None or render_info is None or not render.is_file():
        raise CommandError("Render the clip first.")
    if render_info.get("spec_version") != latest:
        raise CommandError("You've edited since the last render. Render again, then send it.")
    message = (message or "").strip()[:NOTE_MAX] or None

    with _lock:
        iid = item_id(user["id"], job_dir.name, clip)
        item = load(iid) or {
            "id": iid, "owner": _who(user), "jobId": job_dir.name, "clip": int(clip),
            "status": "to_review", "version": 0, "versions": [], "notes": [], "reviewer": None, "events": [],
        }
        last = item["versions"][-1] if item["versions"] else None
        if last and last.get("specVersion") == latest and item["status"] in ("to_review", "good"):
            raise CommandError("This version is already with the team." if item["status"] == "to_review" else "This version was already marked good.")
        n = item["version"] + 1
        files = _files(iid)
        files.mkdir(parents=True, exist_ok=True)
        part = files / f"v{n}.part.mp4"
        shutil.copyfile(render, part)
        os.replace(part, files / f"v{n}.mp4")
        for old in files.glob("v*.mp4"):  # keep the records, not the old videos
            if old.name != f"v{n}.mp4":
                old.unlink(missing_ok=True)
        thumb = thumbnail(job_dir.name, clip)
        if thumb is not None:
            shutil.copyfile(thumb, files / "thumb.jpg")
        item.update(
            title=spec.get("title") or _title(job_dir),
            format=spec.get("format", "vertical"),
            seconds=round(total_frames(spec) / FPS, 1),
            status="to_review",
            version=n,
            owner={**item["owner"], "name": user.get("name") or item["owner"]["name"]},
        )
        item["versions"].append({"n": n, "specVersion": latest, "sentAt": _now(), "message": message})
        item["events"].append({"kind": "sent", "by": _who(user), "at": _now(), "version": n})
        save(item)
    return summary(item)


@command
def review_list() -> list[dict]:
    """Editors get their own videos; reviewers and admins get everyone's."""
    user = actor()
    return [summary(i) for i in all_items() if _may_see(user, i)]


@command
def review_get(id: str) -> dict:
    return _get_for(actor(), id)


@command
def review_for_clip(jobId: str, clip: int) -> dict | None:
    """The review item for a clip open in the editor (your own), or None."""
    user = actor()
    return load(item_id(user["id"], jobId, clip))


@command
def review_decide(id: str, decision: str, version: int, notes: list[dict] | None = None) -> dict:
    """Good, or Needs work with at least one note. `version` is the one the
    reviewer watched: a decision on an older version is refused."""
    user = actor()
    if not _is_reviewer(user):
        raise CommandError("Only the communication team can review videos.")
    if decision not in ("good", "needs_work"):
        raise CommandError("decision must be good or needs_work")
    clean = []
    for note in (notes or [])[:NOTES_MAX]:
        text = str(note.get("text") or "").strip()[:NOTE_MAX]
        at = note.get("time")
        if not text:
            continue
        clean.append({"time": round(float(at), 2) if isinstance(at, (int, float)) and at >= 0 else None, "text": text})
    if decision == "needs_work" and not clean:
        raise CommandError("Say what needs fixing: add at least one note.")
    with _lock:
        item = _get_for(user, id)
        if int(version) != item["version"]:
            raise CommandError(f"There's a newer version (v{item['version']}) of this video. Watch that one first.")
        if item["status"] != "to_review":
            raise CommandError("Someone already reviewed this version.")
        for note in clean:
            item["notes"].append({"id": uuid.uuid4().hex[:10], "version": item["version"], **note,
                                  "by": _who(user), "at": _now(), "fixed": False})
        item["status"] = decision
        item["reviewer"] = _who(user)
        item["events"].append({"kind": decision, "by": _who(user), "at": _now(), "version": item["version"], "notes": len(clean)})
        save(item)
    return item


@command
def review_note_fixed(id: str, noteId: str, fixed: bool = True) -> dict:
    """The editor ticks off a note."""
    user = actor()
    with _lock:
        item = _get_for(user, id)
        if item["owner"]["id"] != user["id"] and user["role"] != "admin":
            raise CommandError("Only the video's editor can tick off its notes.")
        note = next((n for n in item["notes"] if n["id"] == noteId), None)
        if note is None:
            raise CommandError("no such note")
        note["fixed"] = bool(fixed)
        save(item)
    return item


# ---------- the video itself (a <video> tag can't send headers: media token) ----------

@app.get("/api/review/file")
async def review_file(id: str, download: int = 0, what: str = "video") -> FileResponse:
    try:
        who = actor()  # the sign-in token, or a media token carrying the role
        item = _get_for(who, id)
    except CommandError:
        raise HTTPException(404) from None
    if what == "thumb":
        thumb = _files(item["id"]) / "thumb.jpg"
        if not thumb.is_file():
            raise HTTPException(404)
        return FileResponse(thumb, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})
    path = current_file(item)
    if path is None:
        raise HTTPException(404)
    if download:
        with _lock:
            fresh = load(item["id"]) or item
            fresh["events"].append({"kind": "downloaded", "by": _who(who), "at": _now(), "version": fresh["version"]})
            save(fresh)
        name = re.sub(r"[^A-Za-z0-9._ -]+", "", f"{item.get('title') or 'video'} v{item['version']}.mp4").strip() or "video.mp4"
        return FileResponse(path, media_type="video/mp4", filename=name)
    return FileResponse(path, media_type="video/mp4")
