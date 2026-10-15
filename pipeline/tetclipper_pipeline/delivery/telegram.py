"""Deliver rendered clips to a Telegram chat through a bot you own.

Setup is two secrets in TETCLIPPER_HOME/secrets.json: ``telegram_bot_token``
(from @BotFather) and ``telegram_chat_id``. The chat id is learned by having
the user message the bot once, then reading getUpdates (``link_chat``).
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx

from .. import config

API = "https://api.telegram.org/bot{token}/{method}"
# Bot API sendVideo caps uploads at 50 MB; larger clips are saved to a
# folder instead (see save_clip).
VIDEO_LIMIT = 50 * 1024 * 1024


class TelegramError(Exception):
    pass


def _secrets() -> dict:
    path = config.home_dir() / "secrets.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_secret(key: str, value) -> None:
    path = config.home_dir() / "secrets.json"
    data = _secrets()
    data[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def status() -> dict:
    s = _secrets()
    return {
        "has_token": bool(s.get("telegram_bot_token")),
        "chat_id": s.get("telegram_chat_id"),
        "chat_name": s.get("telegram_chat_name"),
        "bot_username": s.get("telegram_bot_username"),
    }


def _call(token: str, method: str, **kwargs) -> dict:
    try:
        res = httpx.post(API.format(token=token, method=method), timeout=kwargs.pop("timeout", 30), **kwargs)
        data = res.json()
    except (httpx.HTTPError, ValueError) as err:
        raise TelegramError(f"Telegram unreachable: {err}") from err
    if not data.get("ok"):
        raise TelegramError(data.get("description", f"Telegram {method} failed"))
    return data["result"]


def save_token(token: str) -> dict:
    token = token.strip()
    me = _call(token, "getMe")
    _save_secret("telegram_bot_token", token)
    _save_secret("telegram_bot_username", me.get("username"))
    return status()


def link_chat() -> dict:
    """Find the most recent chat that messaged the bot and remember it."""
    token = _secrets().get("telegram_bot_token")
    if not token:
        raise TelegramError("Save a bot token first.")
    updates = _call(token, "getUpdates", json={"limit": 100})
    chat = None
    for upd in updates:
        msg = upd.get("message") or upd.get("channel_post") or {}
        if msg.get("chat"):
            chat = msg["chat"]
    if chat is None:
        name = _secrets().get("telegram_bot_username") or "your bot"
        raise TelegramError(f"No messages yet. Send /start to @{name} in Telegram, then try again.")
    _save_secret("telegram_chat_id", chat["id"])
    _save_secret("telegram_chat_name", chat.get("username") or chat.get("title") or chat.get("first_name"))
    return status()


def save_dir() -> Path:
    """Where clips too big for Telegram are kept instead: secrets.json
    ``clip_save_dir``, else Desktop/clipper/clips."""
    custom = _secrets().get("clip_save_dir")
    return Path(custom) if custom else Path.home() / "Desktop" / "clipper" / "clips"


def save_clip(file: Path, caption: str = "") -> Path:
    """Copy a clip into save_dir() under a readable name (never overwrites)."""
    import re
    import shutil

    folder = save_dir()
    folder.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9 _-]+", "", caption).strip().replace(" ", "-")[:60] or file.stem
    dest = folder / f"{stem}.mp4"
    n = 1
    while dest.exists():
        dest = folder / f"{stem}-{n}.mp4"
        n += 1
    shutil.copy2(file, dest)
    return dest


def send_clip(path: str | Path, caption: str = "") -> dict:
    s = _secrets()
    token, chat_id = s.get("telegram_bot_token"), s.get("telegram_chat_id")
    if not token or chat_id is None:
        raise TelegramError("Telegram isn't linked. Open brain & keys → Telegram.")
    file = Path(path)
    if not file.is_file():
        raise TelegramError(f"Clip file missing: {file}")
    # Over the Bot API's 50 MB video cap: keep it in the clips folder instead
    # (big document uploads kept dropping mid-transfer).
    if file.stat().st_size > VIDEO_LIMIT:
        dest = save_clip(file, caption)
        return {"ok": True, "saved": str(dest), "reason": "over Telegram's 50 MB limit"}
    data = {"chat_id": str(chat_id), "caption": caption[:1024], "supports_streaming": "true"}
    with file.open("rb") as fh:
        result = _call(token, "sendVideo", data=data, files={"video": (file.name, fh, "video/mp4")}, timeout=600)
    return {"ok": True, "message_id": result.get("message_id"), "as_video": True}
