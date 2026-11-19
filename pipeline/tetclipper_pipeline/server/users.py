"""Team (admin): invite people by email with a role, list everyone, change roles.

Roles live in Supabase as app_metadata.role, which only the server (with the
project's secret key) can set; people can't change their own. Signing in is
still Supabase's: an invite emails a link to set a password.

  admin          everything, plus this
  head_reviewer  Review and Record
  reviewer       Review
  editor         Edit (the default for anyone without a role)
"""
from __future__ import annotations

import os
import re
from typing import Any

from . import app as _app
from .app import ADMINS, CommandError, actor, command

ASSIGNABLE = ("editor", "reviewer", "head_reviewer", "admin")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _admin_api() -> tuple[str, dict]:
    url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_SECRET_KEY") or ""
    if _app.AUTH != "supabase" or not url:
        raise CommandError("People are managed in the online app.")
    if not key:
        raise CommandError("The server can't manage people yet: it needs the Supabase secret key (SUPABASE_SECRET_KEY).")
    return f"{url}/auth/v1", {"apikey": key, "Authorization": f"Bearer {key}"}


def _admin_only() -> dict:
    me = actor()
    if me["role"] != "admin":
        raise CommandError("Only the admin can manage people.")
    return me


def _call(method: str, path: str, **kwargs: Any) -> Any:
    import httpx

    base, headers = _admin_api()
    try:
        res = httpx.request(method, f"{base}{path}", headers=headers, timeout=20, **kwargs)
    except httpx.HTTPError as err:
        raise CommandError(f"Couldn't reach Supabase: {err}") from err
    if res.status_code >= 400:
        try:
            msg = res.json().get("msg") or res.json().get("message") or res.text
        except ValueError:
            msg = res.text
        raise CommandError(str(msg)[:300] or f"Supabase said {res.status_code}")
    return res.json() if res.content else None


def _person(u: dict, me: dict) -> dict:
    email = (u.get("email") or "").lower()
    meta = u.get("app_metadata") or {}
    fixed_admin = email in ADMINS  # admin by the server's settings: can't be changed here
    role = _app._role(fixed_admin or meta.get("role") == "admin", meta.get("role"))
    return {
        "id": u["id"],
        "email": email,
        "name": str((u.get("user_metadata") or {}).get("name") or "").strip() or email.split("@")[0],
        "role": role,
        "status": "active" if u.get("last_sign_in_at") else "invited",
        "lastSignIn": u.get("last_sign_in_at"),
        "invitedAt": u.get("invited_at") or u.get("created_at"),
        "locked": fixed_admin or u["id"] == me["id"],  # you can't change your own role
        "you": u["id"] == me["id"],
    }


@command
def users_list() -> list[dict]:
    me = _admin_only()
    out, page = [], 1
    while True:
        data = _call("GET", "/admin/users", params={"page": page, "per_page": 200})
        batch = data.get("users", []) if isinstance(data, dict) else data or []
        out += [_person(u, me) for u in batch]
        if len(batch) < 200 or page >= 20:
            break
        page += 1
    order = {r: i for i, r in enumerate(("admin", "head_reviewer", "reviewer", "editor"))}
    return sorted(out, key=lambda p: (order.get(p["role"], 9), p["email"]))


def _set_role(user_id: str, role: str) -> dict:
    data = _call("PUT", f"/admin/users/{user_id}", json={"app_metadata": {"role": role}})
    _app._verified.clear()  # signed-in sessions pick up the new role at once
    return data


@command
def users_invite(email: str, role: str = "editor", name: str | None = None) -> list[dict]:
    """Email someone a link to join, with the role they'll have."""
    me = _admin_only()
    email = (email or "").strip().lower()
    if not _EMAIL.match(email):
        raise CommandError("Type a full email address.")
    if role not in ASSIGNABLE:
        raise CommandError(f"role must be one of {', '.join(ASSIGNABLE)}")
    payload: dict[str, Any] = {"email": email}
    if name and name.strip():
        payload["data"] = {"name": name.strip()[:60]}
    try:
        user = _call("POST", "/invite", json=payload)
    except CommandError as err:
        if "already" in str(err).lower():
            raise CommandError("That email already has an account: change its role in the list instead.") from err
        raise
    if user and user.get("id"):
        _set_role(user["id"], role)
    return users_list()


@command
def users_set_role(id: str, role: str) -> list[dict]:
    me = _admin_only()
    if role not in ASSIGNABLE:
        raise CommandError(f"role must be one of {', '.join(ASSIGNABLE)}")
    if id == me["id"]:
        raise CommandError("You can't change your own role.")
    current = _call("GET", f"/admin/users/{id}")
    if (current.get("email") or "").lower() in ADMINS:
        raise CommandError("This person is an admin by the server's settings (TETCLIPPER_ADMINS).")
    _set_role(id, role)
    return users_list()
