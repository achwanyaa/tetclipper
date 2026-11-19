"""Review: an editor sends a rendered clip, the communication team marks it
Good or Needs work with notes, the editor fixes and re-sends, good videos are
downloaded, and the record says who did what. Roles are checked by the server,
not just hidden in the page. Supabase is replaced by a stand-in token check."""
import json

import pytest
from fastapi.testclient import TestClient

import tetclipper_pipeline.server.app as server
from tetclipper_pipeline.server import review, studio
from tetclipper_pipeline.spec import store

MERCY = {"id": "mmmmmmmm-1111", "email": "mercy@example.com", "admin": False, "role": "editor", "name": "Mercy"}
BRIAN = {"id": "bbbbbbbb-2222", "email": "brian@example.com", "admin": False, "role": "editor", "name": "Brian"}
JOY = {"id": "jjjjjjjj-3333", "email": "joy@example.com", "admin": False, "role": "reviewer", "name": "Joy"}
OWNER = {"id": "oooooooo-4444", "email": "owner@example.com", "admin": True, "role": "admin", "name": "Owner"}
TOKENS = {"t-mercy": MERCY, "t-brian": BRIAN, "t-joy": JOY, "t-owner": OWNER}
SPEC = {
    "version": 1, "title": "No need to fear the accuser",
    "source": {"src": "media.mp4", "start": 5.0, "end": 20.0, "width": 1920, "height": 1080},
    "words": [{"text": "Hello", "start": 5.2, "end": 5.6}],
}


@pytest.fixture
def c(tmp_path, monkeypatch):
    monkeypatch.setenv("TETCLIPPER_HOME", str(tmp_path))
    monkeypatch.setattr(server, "AUTH", "supabase")

    async def check(token):
        return TOKENS.get(token)

    monkeypatch.setattr(server, "_supabase_user", check)
    thumb = tmp_path / "t.jpg"
    thumb.write_bytes(b"jpeg")
    monkeypatch.setattr(studio, "thumbnail", lambda job_id, clip: thumb)
    for user in (MERCY, BRIAN):
        job = tmp_path / "users" / user["id"] / "jobs" / "job1"
        store.save(job, 0, dict(SPEC), reason="built")
    return TestClient(server.app)


def render(tmp_path, user, data=b"video-v1"):
    """What a finished render leaves behind: render.mp4 + render.json at the latest version."""
    job = tmp_path / "users" / user["id"] / "jobs" / "job1"
    cdir = store.clip_dir(job, 0)
    (cdir / "render.mp4").write_bytes(data)
    (cdir / "render.json").write_text(json.dumps({"output": str(cdir / "render.mp4"), "spec_version": store.history(job, 0)[-1]["version"]}))
    return job


def edit(job):
    spec = store.load(job, 0)
    spec["words"][0]["text"] = "Hello!"
    store.save(job, 0, spec, reason="edit")


def cmd(c, token, name, **args):
    return c.post(f"/api/cmd/{name}", json=args, headers={"Authorization": f"Bearer {token}"})


def test_roles_come_from_sign_in(c):
    assert cmd(c, "t-joy", "me").json()["role"] == "reviewer"
    assert cmd(c, "t-mercy", "me").json()["name"] == "Mercy"
    assert cmd(c, "t-owner", "me").json()["role"] == "admin"


def test_the_whole_loop(c, tmp_path):
    job = render(tmp_path, MERCY)
    sent = cmd(c, "t-mercy", "review_submit", jobId="job1", clip=0).json()
    assert sent["status"] == "to_review" and sent["version"] == 1 and sent["owner"]["name"] == "Mercy"
    assert sent["title"] == "No need to fear the accuser" and sent["seconds"] == 15.0
    iid = sent["id"]
    # The same version can't be sent twice.
    assert cmd(c, "t-mercy", "review_submit", jobId="job1", clip=0).status_code == 400

    # Joy watches it and sends it back with two notes, one at a time in the video.
    queue = cmd(c, "t-joy", "review_list").json()
    assert [i["id"] for i in queue] == [iid]
    media = cmd(c, "t-joy", "me").json()["media_token"]
    assert c.get("/api/review/file", params={"id": iid, "access_token": media}).content == b"video-v1"
    assert cmd(c, "t-joy", "review_decide", id=iid, decision="needs_work", version=1, notes=[]).status_code == 400
    back = cmd(c, "t-joy", "review_decide", id=iid, decision="needs_work", version=1,
               notes=[{"time": 41.2, "text": "Wrong verse on screen"}, {"time": None, "text": "Captions a bit small"}, {"text": "  "}]).json()
    assert back["status"] == "needs_work" and back["reviewer"]["name"] == "Joy" and len(back["notes"]) == 2
    assert back["notes"][0]["time"] == 41.2 and back["notes"][1]["time"] is None
    assert cmd(c, "t-joy", "review_decide", id=iid, decision="good", version=1).status_code == 400  # already reviewed

    # Mercy sees it on her clip, ticks the notes off, and can't re-send an unchanged render.
    mine = cmd(c, "t-mercy", "review_for_clip", jobId="job1", clip=0).json()
    assert mine["status"] == "needs_work"
    for note in mine["notes"]:
        cmd(c, "t-mercy", "review_note_fixed", id=iid, noteId=note["id"], fixed=True)
    assert cmd(c, "t-mercy", "review_list").json()[0]["openNotes"] == 0
    assert cmd(c, "t-mercy", "review_submit", jobId="job1", clip=0).status_code == 200  # same render, but it was sent back: allowed
    # ...though a render older than her latest edit is refused.
    edit(job)
    assert "edited since" in cmd(c, "t-mercy", "review_submit", jobId="job1", clip=0).text


def test_resend_good_and_download_are_recorded(c, tmp_path):
    job = render(tmp_path, MERCY)
    iid = cmd(c, "t-mercy", "review_submit", jobId="job1", clip=0).json()["id"]
    cmd(c, "t-joy", "review_decide", id=iid, decision="needs_work", version=1, notes=[{"time": 3, "text": "fix"}])
    edit(job)
    render(tmp_path, MERCY, b"video-v2")
    v2 = cmd(c, "t-mercy", "review_submit", jobId="job1", clip=0, message="Fixed the verse").json()
    assert v2["version"] == 2 and v2["message"] == "Fixed the verse" and v2["status"] == "to_review"
    files = sorted(p.name for p in (tmp_path / "review" / "files" / iid).iterdir())
    assert files == ["thumb.jpg", "v2.mp4"]  # older videos go, their records stay

    # A decision on the version Joy watched before is refused.
    assert "newer version" in cmd(c, "t-joy", "review_decide", id=iid, decision="good", version=1).text
    assert cmd(c, "t-joy", "review_decide", id=iid, decision="good", version=2).json()["status"] == "good"
    assert cmd(c, "t-mercy", "review_submit", jobId="job1", clip=0).status_code == 400  # already good

    media = cmd(c, "t-joy", "me").json()["media_token"]
    got = c.get("/api/review/file", params={"id": iid, "download": 1, "access_token": media})
    assert got.content == b"video-v2" and "attachment" in got.headers["content-disposition"]
    row = cmd(c, "t-owner", "review_list").json()[0]
    assert row["sentBack"] == 1 and row["goodFirstTime"] is False
    assert row["lastDownload"]["by"]["name"] == "Joy" and row["reviewer"]["name"] == "Joy"
    events = [e["kind"] for e in cmd(c, "t-owner", "review_get", id=iid).json()["events"]]
    assert events == ["sent", "needs_work", "sent", "good", "downloaded"]


def test_editors_see_only_their_own(c, tmp_path):
    render(tmp_path, MERCY)
    render(tmp_path, BRIAN)
    mercy = cmd(c, "t-mercy", "review_submit", jobId="job1", clip=0).json()["id"]
    brian = cmd(c, "t-brian", "review_submit", jobId="job1", clip=0).json()["id"]
    assert mercy != brian
    assert [i["id"] for i in cmd(c, "t-brian", "review_list").json()] == [brian]
    assert {i["id"] for i in cmd(c, "t-joy", "review_list").json()} == {mercy, brian}
    # Not by the command, not by the file route, not by the media token.
    assert cmd(c, "t-brian", "review_get", id=mercy).status_code == 400
    media = cmd(c, "t-brian", "me").json()["media_token"]
    assert c.get("/api/review/file", params={"id": mercy, "access_token": media}).status_code == 404
    assert c.get("/api/review/file", params={"id": mercy, "what": "thumb", "access_token": media}).status_code == 404
    assert c.get("/api/review/file", params={"id": mercy}).status_code == 401
    # Editors can't review, even their own; they can't tick someone else's notes.
    assert cmd(c, "t-brian", "review_decide", id=brian, decision="good", version=1).status_code == 400
    cmd(c, "t-joy", "review_decide", id=mercy, decision="needs_work", version=1, notes=[{"text": "x"}])
    note = cmd(c, "t-joy", "review_get", id=mercy).json()["notes"][0]["id"]
    assert cmd(c, "t-brian", "review_note_fixed", id=mercy, noteId=note).status_code == 400
    assert cmd(c, "t-joy", "review_note_fixed", id=mercy, noteId=note).status_code == 400


def test_odd_ids_and_paths_are_refused(c):
    for bad in ("../users", "a/b", "x" * 300, ""):
        assert cmd(c, "t-owner", "review_get", id=bad).status_code == 400
    assert cmd(c, "t-mercy", "review_submit", jobId="../../review", clip=0).status_code == 400
    assert cmd(c, "t-mercy", "review_submit", jobId="job1", clip=0).status_code == 400  # not rendered


def test_the_desktop_app_has_one_admin(tmp_path, monkeypatch):
    monkeypatch.setenv("TETCLIPPER_HOME", str(tmp_path))
    monkeypatch.setattr(server, "AUTH", "")
    monkeypatch.setattr(server, "WEB_TOKEN", None)
    monkeypatch.setattr(studio, "thumbnail", lambda job_id, clip: None)
    store.save(tmp_path / "jobs" / "job1", 0, dict(SPEC), reason="built")
    job = tmp_path / "jobs" / "job1"
    cdir = store.clip_dir(job, 0)
    (cdir / "render.mp4").write_bytes(b"v")
    (cdir / "render.json").write_text(json.dumps({"output": "x", "spec_version": store.history(job, 0)[-1]["version"]}))
    tc = TestClient(server.app)
    assert tc.post("/api/cmd/me", json={}).json()["role"] == "admin"
    iid = tc.post("/api/cmd/review_submit", json={"jobId": "job1", "clip": 0}).json()["id"]
    assert tc.post("/api/cmd/review_decide", json={"id": iid, "decision": "good", "version": 1}).json()["status"] == "good"
    assert review.item_id("local", "job1", 0) == iid
