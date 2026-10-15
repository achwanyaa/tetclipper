"""Hybrid mode: the hosted deployment (Modal, GPU) runs a job up to the
camera pass, then this machine pulls the job folder down and renders it.

``pull(job_id)`` copies every file of the job over the hosted API, rewrites
the absolute paths inside its checkpoints from the server's home to this
one, and registers the job in the local queue. A plain ``resume`` then finds
every analysis stage cached and only renders.
"""
from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
from typing import Any, Callable

import httpx

from .. import config
from . import queue

TOKEN_FILE = "web-token.txt"
SKIP = ("clips/", "t2frames/")  # outputs and scratch: re-made locally


class RemoteError(Exception):
    pass


def _secrets() -> dict:
    try:
        return json.loads((config.home_dir() / "secrets.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def remote_url() -> str | None:
    url = os.environ.get("TETCLIPPER_REMOTE_URL") or _secrets().get("remote_url")
    return url.rstrip("/") if url else None


def remote_token() -> str | None:
    token = os.environ.get("TETCLIPPER_REMOTE_TOKEN") or _secrets().get("remote_token")
    if token:
        return token
    path = config.home_dir() / TOKEN_FILE
    return path.read_text(encoding="utf-8").strip() if path.exists() else None


def _client() -> tuple[str, httpx.Client]:
    url, token = remote_url(), remote_token()
    if not url or not token:
        raise RemoteError(
            "No hosted deployment configured: set remote_url in secrets.json "
            f"(and remote_token, or put the token in {config.home_dir() / TOKEN_FILE})."
        )
    headers = {"Authorization": f"Bearer {token}"}
    return url, httpx.Client(headers=headers, timeout=httpx.Timeout(60.0, read=600.0), follow_redirects=True)


def _cmd(client: httpx.Client, url: str, name: str, **args: Any) -> Any:
    res = client.post(f"{url}/api/cmd/{name}", json=args)
    if res.status_code == 401:
        raise RemoteError("The hosted deployment rejected the access token.")
    if res.status_code != 200:
        raise RemoteError(f"{name}: {res.text[:300]}")
    return res.json()


def _rewrite(value: Any, remote_home: str, local_home: Path) -> Any:
    """Point every absolute path under the server's home at this machine's."""
    if isinstance(value, str):
        prefix = remote_home.rstrip("/") + "/"
        if value.startswith(prefix):
            return str(local_home.joinpath(*PurePosixPath(value[len(prefix):]).parts))
        return value
    if isinstance(value, list):
        return [_rewrite(v, remote_home, local_home) for v in value]
    if isinstance(value, dict):
        return {k: _rewrite(v, remote_home, local_home) for k, v in value.items()}
    return value


def _upload(client: httpx.Client, url: str, path: Path, name: str,
            emit: Callable[[float, str], None] | None = None) -> str:
    size = path.stat().st_size or 1

    def chunks():
        sent = 0
        with path.open("rb") as fh:
            while block := fh.read(1 << 20):
                sent += len(block)
                if emit:
                    emit(sent / size, f"Uploading to the cloud ({sent // 1_000_000}/{size // 1_000_000} MB)…")
                yield block

    res = client.post(f"{url}/api/upload", params={"name": name}, content=chunks(),
                      timeout=httpx.Timeout(60.0, write=None, read=600.0))
    if res.status_code != 200:
        raise RemoteError(f"upload failed: HTTP {res.status_code} {res.text[:200]}")
    return res.json()["path"]


def push(source: str, emit: Callable[[str, float, str], None], llm: str | None = None,
         captions: str | None = None) -> dict:
    """Run a video on the hosted GPU without the cloud touching YouTube:
    download here (a home connection isn't bot-blocked), upload the file and
    its title/heatmap, then start the hosted job on that file."""
    import json as _json
    import re

    from ..ingest import ytdlp

    staging = config.home_dir() / "uploads"
    staging.mkdir(parents=True, exist_ok=True)
    meta: dict = {}
    if source.startswith(("http://", "https://")):
        info = ytdlp.fetch_meta(source, lambda f, m: emit("download", f * 0.1, m))
        meta = {"title": info.title, "heatmap": info.heatmap, "url": info.webpage_url}
        safe = re.sub(r"[^A-Za-z0-9 _-]+", "", info.title).strip().replace(" ", "-")[:80] or info.id
        local = staging / f"{safe}-{info.id}.mp4"
        if not local.exists():
            part = local.with_name(local.name + ".part.mp4")
            ytdlp.download(source, part, lambda f, m: emit("download", f, m))
            part.replace(local)
        emit("download", 1.0, "done")
    else:
        local = Path(source).expanduser().resolve()
        if not local.is_file():
            raise RemoteError(f"File not found: {local}")

    url, client = _client()
    with client:
        remote_path = _upload(client, url, local, local.name, lambda f, m: emit("upload", f, m))
        if meta:
            side = staging / (local.name + ".meta.json")
            side.write_text(_json.dumps(meta), encoding="utf-8")
            # The server names uploads uniquely; make the sidecar follow it.
            _upload(client, url, side, PurePosixPath(remote_path).name + ".meta.json")
        emit("upload", 1.0, "done")
        args = {"source": remote_path, "llm": llm, "captions": captions}
        _cmd(client, url, "run_job", **{k: v for k, v in args.items() if v})
    return {"remote_source": remote_path, "title": meta.get("title") or local.stem}


def list_remote() -> list[dict]:
    """Hosted jobs, each flagged with whether this machine already has it."""
    url, client = _client()
    with client:
        jobs = _cmd(client, url, "list_job_dirs")
    for job in jobs:
        job["local"] = (config.jobs_dir() / job["id"] / "render.json").exists()
    return jobs


def pull(job_id: str, emit: Callable[[float, str], None]) -> dict:
    url, client = _client()
    with client:
        manifest = _cmd(client, url, "job_manifest", jobId=job_id)
        remote_home = manifest["home"]
        files = [f for f in manifest["files"] if not f["path"].startswith(SKIP)]
        total = sum(f["size"] for f in files) or 1
        job_dir = config.jobs_dir() / job_id
        done = 0
        for f in files:
            dest = job_dir.joinpath(*PurePosixPath(f["path"]).parts)
            if dest.exists() and dest.stat().st_size == f["size"]:
                done += f["size"]
                continue  # already here (an earlier pull)
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".part")
            with client.stream("GET", f"{url}/files", params={"path": f"{remote_home}/jobs/{job_id}/{f['path']}"}) as res:
                if res.status_code != 200:
                    raise RemoteError(f"download {f['path']}: HTTP {res.status_code}")
                with tmp.open("wb") as out:
                    for chunk in res.iter_bytes(1 << 20):
                        out.write(chunk)
                        done += len(chunk)
                        emit(done / total, f"Pulling {f['path']} ({done // 1_000_000}/{total // 1_000_000} MB)…")
            tmp.replace(dest)

    # Checkpoints carry absolute paths from the server; make them local.
    for path in job_dir.rglob("*.json"):
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        fixed = _rewrite(data, remote_home, config.home_dir())
        if fixed != data:
            path.write_text(json.dumps(fixed))

    row = manifest["job"]
    queue.import_job(row["id"], row["source_type"], row["source"], row["settings_json"], row.get("title"))
    return {"job_id": job_id, "files": len(files), "bytes": total}
