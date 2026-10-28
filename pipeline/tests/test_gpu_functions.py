"""The hosted web app holds no GPU: its jobs send GPU work to the Modal
functions (TETCLIPPER_GPU_FUNCTIONS=1), and clips are built on CPU."""
import json
from pathlib import Path

import pytest

from tetclipper_pipeline import cli, config
from tetclipper_pipeline.cloud import client, remote
from tetclipper_pipeline.jobs import queue
from tetclipper_pipeline.spec import build as spec_build
from tetclipper_pipeline.spec import store

SPEC = {
    "version": 1,
    "source": {"src": "media.mp4", "start": 0.0, "end": 10.0, "width": 1920, "height": 1080},
    "intro": None, "cuts": [], "words": [{"text": "Hello", "start": 0.2, "end": 0.6}],
    "captions": {"enabled": True, "style": "hormozi"}, "crop": {"keyframes": []}, "effects": [],
    "progressBar": {"enabled": False, "color": "#FFD700"},
}


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("TETCLIPPER_HOME", str(tmp_path))
    monkeypatch.delenv("TETCLIPPER_WORKSPACE", raising=False)
    monkeypatch.delenv("TETCLIPPER_GPU_FUNCTIONS", raising=False)
    monkeypatch.delenv("TETCLIPPER_CLOUD", raising=False)
    return tmp_path


def test_the_web_app_counts_as_cloud_ready(home, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: home / "no-login")  # no ~/.modal.toml
    monkeypatch.delenv("MODAL_TOKEN_ID", raising=False)
    assert not client.available() and not client.hosted()
    monkeypatch.setenv("TETCLIPPER_GPU_FUNCTIONS", "1")
    assert client.available() and client.hosted()
    monkeypatch.setenv("TETCLIPPER_CLOUD", "0")
    assert not client.available()


def test_a_users_jobs_map_to_the_shared_cloud_jobs(home, monkeypatch):
    # Online: /data/users/<id>/jobs/<job> is worked on as /data/jobs/<job>; the
    # rest of the home (the music library) keeps its place.
    ws = home / "users" / "u1"
    monkeypatch.setenv("TETCLIPPER_WORKSPACE", str(ws))
    data = {"audio": str(ws / "jobs" / "j1" / "audio16k.wav"), "music": str(home / "audio" / "a.mp3"), "n": 3}
    remote_data = client.to_remote(data)
    assert remote_data == {"audio": "/data/jobs/j1/audio16k.wav", "music": "/data/audio/a.mp3", "n": 3}
    assert client.to_local(remote_data) == data


def test_a_pc_maps_as_before(home):
    data = {"audio": str(home / "jobs" / "j1" / "audio16k.wav"), "model": str(home / "models" / "x")}
    assert client.to_remote(data) == {"audio": "/data/jobs/j1/audio16k.wav", "model": "/data/models/x"}
    assert client.to_local(client.to_remote(data)) == data


def test_a_cloud_cut_builds_its_clip_on_the_cpu_function(home, monkeypatch):
    job = queue.create_job("url", "https://drive.google.com/file/d/x/view",
                           json.dumps({**config.Settings().to_json(), "section": [5.0, 20.0]}))
    calls = []
    monkeypatch.setattr(cli, "_ensure_pipeline_deps", lambda jsonl, emit: (True, None))
    monkeypatch.setattr(queue, "run_stages", lambda job, stages, emit: {"ingest": {"section_offset": 0.0}})
    monkeypatch.setattr(client, "analyze", lambda job, start, end, captions, emit: calls.append(("analyze", start, end)))

    def add_range(job, start, end, emit, caption_preset=None, camera_mode=None):
        calls.append(("add_range", start, end))
        return {"clip_index": 0}

    def build_specs(job_dir, clips, captions, emit):
        calls.append(("build_specs", clips))
        store.save(Path(job_dir), 0, dict(SPEC), reason="built in the cloud")

    from tetclipper_pipeline.edits import manual

    monkeypatch.setattr(manual, "add_range", add_range)
    monkeypatch.setattr(client, "build_specs", build_specs)
    built_here = []
    real_build = spec_build.build
    monkeypatch.setattr(spec_build, "build", lambda job_dir, idx, **kw: built_here.append(store.load(job_dir, idx) is None)
                        or real_build(job_dir, idx, **kw))
    assert cli._run_range(job, False, "hormozi", None, cloud=True) == 0
    assert calls == [("analyze", 5.0, 20.0), ("add_range", 5.0, 20.0), ("build_specs", [0])]
    assert built_here == [False]  # the spec was already there: nothing directed here


def test_cloud_analysis_runs_only_the_gpu_stages(home, monkeypatch):
    ran = []
    monkeypatch.setattr(queue, "run_stages", lambda job, stages, emit: ran.append([s.name for s in stages]) or {})
    monkeypatch.setattr(spec_build, "build", lambda *a, **k: pytest.fail("the camera must not run on the GPU"))
    row = {"id": "20261028-000000-abcdef", "source_type": "url", "source": "u",
           "settings_json": json.dumps(config.Settings().to_json()), "title": "t", "glossary": None}
    events = list(remote.analyze(row, 5.0, 20.0, "hormozi"))
    assert events[-1] == {"event": "result", "ok": True, "job_id": row["id"]}
    assert ran == [["ingest", "asr", "diarize", "events"]]


@pytest.mark.parametrize("hosted, expect", [(True, "cloud"), (False, "here")])
def test_second_listen_from_the_web_app_goes_to_the_gpu(home, monkeypatch, hosted, expect):
    """Inside Modal: the web app (hosted) asks the second_listen GPU function;
    a function container (build_spec, on CPU) listens itself."""
    from tetclipper_pipeline.spec import doubts

    job_dir = home / "jobs" / "j1"
    job_dir.mkdir(parents=True)
    (job_dir / "ingest.json").write_text(json.dumps({"data": {"audio_path": str(job_dir / "audio16k.wav")}}))
    monkeypatch.setenv("MODAL_TASK_ID", "ta-test")
    if hosted:
        monkeypatch.setenv("TETCLIPPER_GPU_FUNCTIONS", "1")
    monkeypatch.setattr(client, "available", lambda: hosted)
    span = [{"from": 0, "to": 0, "reason": "unclear audio"}]
    monkeypatch.setattr(doubts, "detect", lambda words, scores: span)
    monkeypatch.setattr(doubts, "enabled", lambda: True)
    where = []
    monkeypatch.setattr(client, "second_opinion", lambda *a: where.append("cloud") or span)
    monkeypatch.setattr(doubts, "second_opinion", lambda *a: where.append("here") or span)
    spec_build.find_doubts(job_dir, [{"text": "x", "start": 0, "end": 1}], {})
    assert where == [expect]


def test_online_jobs_always_go_to_the_cloud(home, monkeypatch):
    """An open tab from before may still send cloud=False ("This PC"); the web app has no GPU."""
    from tetclipper_pipeline.server import studio

    sent = []
    monkeypatch.setattr(studio, "stream_pipeline", lambda args: sent.append(args))
    studio.studio_cut("u", 0, 30, cloud=False)
    assert sent[-1][-1] == "--local"  # the desktop app: the user's choice
    monkeypatch.setenv("TETCLIPPER_GPU_FUNCTIONS", "1")
    studio.studio_cut("u", 0, 30, cloud=False)
    studio.studio_find("u", cloud=None)
    assert sent[-2][-1] == "--cloud" and sent[-1][-1] == "--cloud"
    assert studio.studio_info()["hosted"] is True


def test_job_db_connections_close(home):
    """An open db file blocks volume.reload() in a warm Modal container."""
    import sqlite3

    from tetclipper_pipeline.scoring import constants

    for connect in (queue._connect, constants._connect):
        with connect() as conn:
            conn.execute("SELECT 1")
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")  # closed
    job = queue.create_job("url", "u", "{}")
    assert queue.get_job(job.id).id == job.id  # writes still committed
