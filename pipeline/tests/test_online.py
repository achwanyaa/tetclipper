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
