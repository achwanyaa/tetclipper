"""The online server (TETCLIPPER_AUTH=supabase): sign-in required, a private
workspace per user, media tokens only for files/events, AI model admin-only.
Supabase is replaced by a stand-in token check (no network)."""
import pytest
from fastapi.testclient import TestClient

import tetclipper_pipeline.server.app as server
from tetclipper_pipeline.spec import store

A = {"id": "aaaaaaaa-1111", "email": "owner@example.com", "admin": True}
B = {"id": "bbbbbbbb-2222", "email": "editor@example.com", "admin": False}
SPEC = {
    "version": 1,
    "source": {"src": "media.mp4", "start": 5.0, "end": 20.0, "width": 1920, "height": 1080},
    "intro": None,
    "cuts": [],
    "words": [{"text": "Hello", "start": 5.2, "end": 5.6}],
    "captions": {"enabled": True, "style": "hormozi"},
    "crop": {"keyframes": []},
    "effects": [],
    "progressBar": {"enabled": False, "color": "#FFD700"},
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TETCLIPPER_HOME", str(tmp_path))
    monkeypatch.setattr(server, "AUTH", "supabase")
    tokens = {"token-a": A, "token-b": B}

    async def check(token):
        return tokens.get(token)

    monkeypatch.setattr(server, "_supabase_user", check)
    job = tmp_path / "users" / A["id"] / "jobs" / "job1"
    store.save(job, 0, dict(SPEC), reason="test")
    (job / "media.mp4").write_bytes(b"video")
    return TestClient(server.app), job


def cmd(client, name, token=None, **args):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.post(f"/api/cmd/{name}", json=args, headers=headers)


def test_sign_in_is_required_except_auth_config(client):
    c, _ = client
    assert c.get("/api/auth-config").json() == {"mode": "supabase"}
    assert cmd(c, "studio_jobs").status_code == 401
    assert cmd(c, "studio_jobs", "made-up").status_code == 401
    me = cmd(c, "me", "token-a").json()
    assert me["user"]["email"] == A["email"] and me["admin"] is True and me["media_token"].startswith("mt.")


def test_each_user_sees_only_their_own_workspace(client):
    c, job = client
    assert [j["id"] for j in cmd(c, "studio_jobs", "token-a").json()] == ["job1"]
    assert cmd(c, "studio_jobs", "token-b").json() == []
    assert cmd(c, "studio_clip", "token-b", jobId="job1", clip=0).status_code == 400
    assert cmd(c, "studio_clip", "token-a", jobId="job1", clip=0).json()["jobId"] == "job1"


def test_media_tokens_open_only_your_files(client):
    c, job = client
    media_a = cmd(c, "me", "token-a").json()["media_token"]
    media_b = cmd(c, "me", "token-b").json()["media_token"]
    path = str(job / "media.mp4")
    assert c.get("/files", params={"path": path, "access_token": media_a}).content == b"video"
    assert c.get("/files", params={"path": path, "access_token": media_b}).status_code == 404
    assert c.get("/files", params={"path": path}).status_code == 401
    # A media token can't run commands.
    assert c.post("/api/cmd/studio_jobs", params={"access_token": media_a}, json={}).status_code == 401


def test_only_the_admin_manages_the_ai_model(client):
    c, _ = client
    assert cmd(c, "ai_settings_get", "token-b").status_code == 400
    assert cmd(c, "ai_settings_get", "token-a").json()["provider"] == "claude-code"


def test_health_is_public_and_tells_only_the_running_count(client):
    c, _ = client
    assert c.get("/api/health").json() == {"running": 0}


def test_a_reconnecting_event_stream_gets_what_it_missed():
    """Streams end every STREAM_SEC; Last-Event-ID replays the gap, per workspace."""
    import asyncio

    b = server.Broadcaster()
    b.loop = asyncio.new_event_loop()
    try:
        b.publish({"n": 1}, workspace="/ws/a")
        b.publish({"n": 2}, workspace="/ws/b")
        b.publish({"n": 3}, workspace="/ws/a")
        assert [e for _, _, e in b.missed(f"{b.boot}-1", "/ws/a")] == [{"n": 3}]
        assert [e for _, _, e in b.missed(f"{b.boot}-0", "/ws/b")] == [{"n": 2}]
        # No id, or an id from another container (before a deploy): nothing to replay.
        assert b.missed(None, "/ws/a") == [] and b.missed("0123abcd-1", "/ws/a") == []
    finally:
        b.loop.close()


def test_clip_cards_get_a_real_frame_framed_like_the_clip(client, monkeypatch):
    """/api/thumb: a 9:16 frame from the source, cropped where the camera
    points; media tokens open it, other users' jobs stay hidden."""
    import shutil
    import subprocess
    from pathlib import Path

    from tetclipper_pipeline.render import ffmpeg_bin
    from tetclipper_pipeline.server import studio

    c, job = client
    # The camera path, as the composition reads it.
    spec = {"crop": {"keyframes": [{"t": 0, "x": 0.2, "y": 0.5, "zoom": 1}, {"t": 2, "x": 0.6, "y": 0.5, "zoom": 1},
                                   {"t": 3, "x": 0.9, "y": 0.5, "zoom": 1.2, "cut": True}]}}
    assert studio._crop_at(spec, 1)["x"] == 0.4
    assert studio._crop_at(spec, 2.5)["x"] == 0.6  # holds until a cut
    assert studio._crop_at(spec, 9)["x"] == 0.9

    media = cmd(c, "me", "token-b").json()["media_token"]
    assert c.get("/api/thumb", params={"job": "job1", "clip": 0, "access_token": media}).status_code == 404
    listed = cmd(c, "studio_jobs", "token-a").json()[0]["clips"][0]
    assert listed["thumb"] > 0
    real = Path(str(Path.home() / ".tetclipper" / "bin" / "ffmpeg.exe"))
    exe = shutil.which("ffmpeg") or (str(real) if real.exists() else None)
    if not exe:
        pytest.skip("no ffmpeg here")
    monkeypatch.setattr(ffmpeg_bin, "ffmpeg", lambda: exe)
    # Left half red, right half blue; the clip's camera points at the right.
    subprocess.run([exe, "-v", "error", "-y", "-f", "lavfi", "-i", "color=red:s=960x1080:d=30", "-f", "lavfi",
                    "-i", "color=blue:s=960x1080:d=30", "-filter_complex", "hstack", "-t", "30", str(job / "media.mp4")],
                   check=True)
    s = store.load(job, 0)
    s["crop"] = {"keyframes": [{"t": 0, "x": 0.8, "y": 0.5, "zoom": 1}]}
    store.save(job, 0, s, reason="camera right")
    media = cmd(c, "me", "token-a").json()["media_token"]
    r = c.get("/api/thumb", params={"job": "job1", "clip": 0, "access_token": media})
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    pixel = subprocess.run([exe, "-v", "error", "-i", str(job / "studio" / "clip_00" / "thumb.jpg"), "-vf",
                            "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    assert pixel[2] > 150 and pixel[0] < 80  # blue: framed where the camera points
