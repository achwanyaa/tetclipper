"""Job progress that survives missed live events, and the Drive format choice."""
import json
import sys
import time

import pytest

import tetclipper_pipeline.server.app as server
from tetclipper_pipeline.ingest import ytdlp
from tetclipper_pipeline.server import studio


def _meta(heights, extractor="GoogleDrive"):
    formats = [{"format_id": str(i), "height": h, "url": f"https://x/{i}"} for i, h in enumerate(heights)]
    formats.append({"format_id": "source", "url": "https://x/source", "http_headers": {"User-Agent": "t"}})
    return ytdlp.UrlMeta(id="v", title="v", duration_sec=60.0, webpage_url="u", raw={"extractor_key": extractor, "formats": formats})


def test_drive_original_is_used_only_when_it_is_sharper(monkeypatch):
    probed = []
    monkeypatch.setattr(ytdlp, "_probe_height", lambda url, headers: probed.append(url) or 480)
    assert ytdlp.pick_format(_meta([360]), lambda f, m: None) == "source"
    assert probed == ["https://x/source"]
    # Drive already serves HD: no probe, the usual rule.
    assert ytdlp.pick_format(_meta([360, 1080]), lambda f, m: None) == ytdlp.DOWNLOAD_FORMAT
    assert len(probed) == 1
    # The original is no better, or the probe fails: the usual rule.
    monkeypatch.setattr(ytdlp, "_probe_height", lambda url, headers: 360)
    assert ytdlp.pick_format(_meta([360]), lambda f, m: None) == ytdlp.DOWNLOAD_FORMAT
    monkeypatch.setattr(ytdlp, "_probe_height", lambda url, headers: None)
    assert ytdlp.pick_format(_meta([360]), lambda f, m: None) == ytdlp.DOWNLOAD_FORMAT
    # Not Drive (YouTube etc.): never probed.
    assert ytdlp.pick_format(_meta([360], extractor="Youtube"), lambda f, m: None) == ytdlp.DOWNLOAD_FORMAT


def test_a_failed_original_download_falls_back_to_drives_copy(tmp_path, monkeypatch):
    tried = []

    def fake(url, out, progress, section, fmt):
        tried.append(fmt)
        if fmt == "source":
            raise ytdlp.YtDlpError("ffmpeg exited")

    monkeypatch.setattr(ytdlp, "_download", fake)
    ytdlp.download("u", tmp_path / "media.mp4", lambda f, m: None, fmt="source")
    assert tried == ["source", ytdlp.DOWNLOAD_FORMAT]


@pytest.mark.parametrize("ok", [True, False])
def test_progress_file_follows_the_job_to_the_end(tmp_path, monkeypatch, ok):
    job_dir = tmp_path / "jobs" / "job1"
    job_dir.mkdir(parents=True)
    script = tmp_path / "fake_cli.py"
    lines = [
        {"event": "job", "job_id": "job1", "dir": str(job_dir)},
        {"event": "progress", "stage": "ingest", "fraction": 0.4, "message": "Downloading video…"},
        {"event": "result", "ok": ok, "job_id": "job1", **({} if ok else {"error": "asr: no speech"})},
    ]
    script.write_text("import json\n" + "".join(f"print(json.dumps({line!r}), flush=True)\n" for line in lines), encoding="utf-8")
    monkeypatch.setenv("TETCLIPPER_CLI", f'"{sys.executable}" "{script}"')
    monkeypatch.delenv("TETCLIPPER_PUBLIC_URL", raising=False)
    server.stream_pipeline(["cut", "x"])
    path = job_dir / "progress.json"
    for _ in range(100):
        state = json.loads(path.read_text()) if path.exists() else {}
        if state.get("state") in ("done", "failed"):
            break
        time.sleep(0.1)
    assert state["state"] == ("done" if ok else "failed")
    assert state["label"] == "Cutting a clip"
    assert state["error"] == (None if ok else "asr: no speech")
    assert server._running == 0


def test_clip_list_shows_running_jobs_hides_dismissed_and_flags_stale(tmp_path, monkeypatch):
    monkeypatch.setenv("TETCLIPPER_HOME", str(tmp_path))
    jobs = tmp_path / "jobs"
    now = time.time()
    for name, state, updated in [("a-running", "running", now), ("b-stale", "running", now - 3 * 3600), ("c-dismissed", "dismissed", now)]:
        (jobs / name).mkdir(parents=True)
        (jobs / name / "settings.json").write_text("{}")
        (jobs / name / "progress.json").write_text(json.dumps({"state": state, "fraction": 0.3, "message": "m", "label": None, "updated": updated}))
    listed = {j["id"]: j for j in studio.studio_jobs()}
    assert listed["a-running"]["progress"]["state"] == "running"
    assert listed["b-stale"]["progress"]["state"] == "failed" and "restarted" in listed["b-stale"]["progress"]["error"]
    assert "c-dismissed" not in listed
    studio.studio_job_dismiss("b-stale")
    assert "b-stale" not in {j["id"] for j in studio.studio_jobs()}
