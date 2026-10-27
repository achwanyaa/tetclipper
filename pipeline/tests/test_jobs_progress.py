"""Job progress that survives missed live events, and the Drive format choice."""
import json
import subprocess
import sys
import time

import pytest

import tetclipper_pipeline.server.app as server
from tetclipper_pipeline.ingest import ytdlp
from tetclipper_pipeline.server import studio


def _meta(sizes, extractor="GoogleDrive"):
    formats = [{"format_id": str(i), "width": w, "height": h, "url": f"https://x/{i}"} for i, (w, h) in enumerate(sizes)]
    formats.append({"format_id": "source", "url": "https://x/source", "http_headers": {"User-Agent": "t"}})
    return ytdlp.UrlMeta(id="v", title="v", duration_sec=60.0, webpage_url="u", raw={"extractor_key": extractor, "formats": formats})


def test_drive_original_is_used_only_when_it_is_sharper(monkeypatch):
    probed = []
    monkeypatch.setattr(ytdlp, "_probe_short_side", lambda url, headers: probed.append(url) or 480)
    assert ytdlp.pick_format(_meta([(640, 360)]), lambda f, m: None) == "source"
    assert probed == ["https://x/source"]
    # Drive already serves HD, landscape or vertical: no probe, the usual rule.
    assert ytdlp.pick_format(_meta([(640, 360), (1920, 1080)]), lambda f, m: None) == ytdlp.DOWNLOAD_FORMAT
    assert ytdlp.pick_format(_meta([(360, 640), (1080, 1920)]), lambda f, m: None) == ytdlp.DOWNLOAD_FORMAT
    assert len(probed) == 1
    # A vertical 360x640 copy is 360p, not 640p: the original is checked.
    assert ytdlp.pick_format(_meta([(360, 640)]), lambda f, m: None) == "source"
    # The original is no better, or the probe fails: the usual rule.
    monkeypatch.setattr(ytdlp, "_probe_short_side", lambda url, headers: 360)
    assert ytdlp.pick_format(_meta([(640, 360)]), lambda f, m: None) == ytdlp.DOWNLOAD_FORMAT
    monkeypatch.setattr(ytdlp, "_probe_short_side", lambda url, headers: None)
    assert ytdlp.pick_format(_meta([(640, 360)]), lambda f, m: None) == ytdlp.DOWNLOAD_FORMAT
    # Not Drive (YouTube etc.): never probed.
    assert ytdlp.pick_format(_meta([(640, 360)], extractor="Youtube"), lambda f, m: None) == ytdlp.DOWNLOAD_FORMAT


@pytest.mark.skipif(not ytdlp.binary_path().exists(), reason="yt-dlp not installed")
def test_download_rule_allows_1080p_in_either_orientation(tmp_path):
    # yt-dlp's own selector over a Drive phone video's real format list (22222.mp4).
    formats = [
        {"format_id": "134", "ext": "mp4", "width": 360, "height": 640, "vcodec": "avc1", "acodec": "none"},
        {"format_id": "136", "ext": "mp4", "width": 720, "height": 1280, "vcodec": "avc1", "acodec": "none"},
        {"format_id": "137", "ext": "mp4", "width": 1080, "height": 1920, "vcodec": "avc1", "acodec": "none"},
        {"format_id": "140", "ext": "m4a", "vcodec": "none", "acodec": "mp4a"},
        {"format_id": "313", "ext": "mp4", "width": 2160, "height": 3840, "vcodec": "avc1", "acodec": "none"},
    ]

    def picked(fmts):
        info = tmp_path / "info.json"
        info.write_text(json.dumps({"id": "v", "title": "v", "extractor": "generic", "webpage_url": "https://x/v",
                                    "formats": [dict(f, url=f"https://x/{f['format_id']}") for f in fmts]}))
        out = subprocess.run([str(ytdlp.binary_path()), "--load-info-json", str(info), "-f", ytdlp.DOWNLOAD_FORMAT,
                              "--simulate", "--print", "%(format_id)s", "--no-warnings"], capture_output=True, text=True, timeout=60)
        return out.stdout.strip()

    assert picked(formats) == "137+140"  # vertical 1080x1920, not 360x640
    landscape = [dict(f, width=f["height"], height=f["width"]) if "width" in f else f for f in formats]
    assert picked(landscape) == "137+140"  # 1920x1080, not 4K


def test_short_side():
    assert ytdlp.short_side(854, 480) == 480
    assert ytdlp.short_side(1080, 1920) == 1080
    assert ytdlp.short_side(None, 720) == 720


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
