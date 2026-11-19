"""Team admin: invite by email with a role, list people, change roles; and what
each role may do. Supabase (sign-in and its admin API) is replaced by stand-ins."""
import pytest
from fastapi.testclient import TestClient

import tetclipper_pipeline.server.app as server
from tetclipper_pipeline.server import users

OWNER = {"id": "oooooooo-1111", "email": "owner@example.com", "admin": True, "role": "admin", "name": "Owner"}
HEAD = {"id": "hhhhhhhh-2222", "email": "head@example.com", "admin": False, "role": "head_reviewer", "name": "Head"}
JOY = {"id": "jjjjjjjj-3333", "email": "joy@example.com", "admin": False, "role": "reviewer", "name": "Joy"}
MERCY = {"id": "mmmmmmmm-4444", "email": "mercy@example.com", "admin": False, "role": "editor", "name": "Mercy"}
TOKENS = {"t-owner": OWNER, "t-head": HEAD, "t-joy": JOY, "t-mercy": MERCY}


class FakeSupabase:
    """The bits of the Supabase admin API the app uses."""

    def __init__(self):
        self.people = {u["id"]: {"id": u["id"], "email": u["email"], "app_metadata": {"role": u["role"]},
                                 "user_metadata": {"name": u["name"]}, "last_sign_in_at": "2026-11-19T10:00:00Z"}
                       for u in (OWNER, HEAD, JOY, MERCY)}

    def __call__(self, method, path, **kw):
        if method == "GET" and path == "/admin/users":
            return {"users": list(self.people.values())}
        if method == "GET" and path.startswith("/admin/users/"):
            return self.people[path.rsplit("/", 1)[1]]
        if method == "PUT" and path.startswith("/admin/users/"):
            u = self.people[path.rsplit("/", 1)[1]]
            u["app_metadata"] = {**u["app_metadata"], **kw["json"]["app_metadata"]}
            return u
        if method == "POST" and path == "/invite":
            email = kw["json"]["email"]
            if any(p["email"] == email for p in self.people.values()):
                raise server.CommandError("A user with this email address has already been registered")
            new = {"id": f"new-{len(self.people)}", "email": email, "app_metadata": {}, "user_metadata": kw["json"].get("data", {})}
            self.people[new["id"]] = new
            return new
        raise AssertionError((method, path))


@pytest.fixture
def c(tmp_path, monkeypatch):
    monkeypatch.setenv("TETCLIPPER_HOME", str(tmp_path))
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_test")
    monkeypatch.setattr(server, "AUTH", "supabase")

    async def check(token):
        return TOKENS.get(token)

    monkeypatch.setattr(server, "_supabase_user", check)
    fake = FakeSupabase()
    monkeypatch.setattr(users, "_call", fake)
    return TestClient(server.app), fake


def cmd(client, token, command_name, **args):
    return client.post(f"/api/cmd/{command_name}", json=args, headers={"Authorization": f"Bearer {token}"})


def test_only_the_admin_manages_people(c):
    client, _ = c
    for token in ("t-head", "t-joy", "t-mercy"):
        assert cmd(client, token, "users_list").status_code == 400
        assert cmd(client, token, "users_invite", email="x@example.com").status_code == 400
    people = cmd(client, "t-owner", "users_list").json()
    assert [p["role"] for p in people] == ["admin", "head_reviewer", "reviewer", "editor"]
    assert people[0]["you"] and people[0]["locked"] and not people[1]["locked"]


def test_invite_with_a_role_and_change_roles(c):
    client, fake = c
    people = cmd(client, "t-owner", "users_invite", email=" New.Person@Example.com ", role="reviewer", name="Ann").json()
    ann = next(p for p in people if p["email"] == "new.person@example.com")
    assert ann["role"] == "reviewer" and ann["status"] == "invited" and ann["name"] == "Ann"
    assert "already has an account" in cmd(client, "t-owner", "users_invite", email="joy@example.com").text
    assert cmd(client, "t-owner", "users_invite", email="not-an-email").status_code == 400
    assert cmd(client, "t-owner", "users_invite", email="b@example.com", role="boss").status_code == 400
    # Roles change, but never your own.
    people = cmd(client, "t-owner", "users_set_role", id=MERCY["id"], role="head_reviewer").json()
    assert next(p for p in people if p["id"] == MERCY["id"])["role"] == "head_reviewer"
    assert cmd(client, "t-owner", "users_set_role", id=OWNER["id"], role="editor").status_code == 400


def test_each_role_does_only_its_side(c):
    client, _ = c
    # Reviewers and the head reviewer can't make or change videos...
    for token in ("t-joy", "t-head"):
        for name, args in [("studio_cut", {"source": "x", "start": 0, "end": 1}), ("studio_render", {"jobId": "j", "clip": 0}),
                           ("studio_chat_send", {"jobId": "j", "clip": 0, "message": "hi"}), ("review_submit", {"jobId": "j", "clip": 0})]:
            assert cmd(client, token, name, **args).status_code == 403, (token, name)
    # ...and editors can't review.
    assert cmd(client, "t-mercy", "review_decide", id="x__y__0", decision="good", version=1).status_code == 400
    assert cmd(client, "t-head", "me").json()["role"] == "head_reviewer"


def test_the_app_says_whether_it_can_invite(c, monkeypatch):
    client, _ = c
    assert client.get("/api/auth-config").json()["team"] is True
    monkeypatch.delenv("SUPABASE_SECRET_KEY")
    assert client.get("/api/auth-config").json()["team"] is False
