# tetclipper

**Long video in. Vertical clips out, edited by chatting with Claude Code.**

tetclipper is an open-source (AGPL-3.0) clip studio that takes a YouTube URL or a
horizontal video file and produces vertical 9:16 clips with:

- **Smart camera** — active-speaker-tracked crop paths, smoothed motion, hard cuts
  on speaker change, punch-ins fired by actual laughter and vocal energy
- **Word-accurate captions** — multiple styles, karaoke highlighting, prosodic
  emphasis (loud words get loud styling), `[laughs]` tags from real laughter detection
- **A virality score you can audit** — never a bare number: every clip ships with
  its subscores, which detectors fired, and every adjustment applied. LLM humor
  scores get discounted when no actual laughter corroborates them.
- **Music & SFX** — a local, CC-licensed library (import your own or pull from
  Freesound/Jamendo), auto-suggested from a genre/mood/energy brief derived
  from what's being said and how it sounds, with manual placement always
  available and music ducked under speech automatically
- **Optional real-outcomes loop** — connect your own Instagram (via your own Meta
  app, no middleman) and the scorer calibrates against how your clips actually perform

Every model — speech recognition, forced alignment, diarization, laughter
detection, audio tagging, face detection, active-speaker detection — runs
locally (or on your own Modal GPU, see below). Moments are judged by your own
Claude Code session — no API key: a job pauses at JUDGE and `/score-clips`
answers it. Your own Gemini key or a local Ollama model also work.

Beyond the auto-found moments:

- **Range mode** — give a link and exact minutes (12:30–13:15); only that slice
  is downloaded, transcribed and cut.
- **Chat** — describe the cut in words ("the part about Goliath, under a
  minute, hormozi captions") and Claude Code finds and cuts it.
- **Caption editing** — fix any word, or let Claude proofread the captions.
- **Telegram delivery** — send finished clips to your own bot.

## Studio (chat-driven clip editor)

A browser editor where you talk to Claude Code and watch the clip change.

1. Paste a YouTube link plus a range (12:30 → 13:15). Only that slice is
   downloaded, on this PC (YouTube blocks cloud IPs).
2. Transcription, diarization, audio events and the smart camera run on a
   Modal GPU (or this PC), and produce one `spec.json` for the clip: words,
   caption style, crop keyframes, punch-ins, intro photo, cuts, effects.
3. The centre of the editor is a live Remotion preview of that spec. Caption
   styles (9, with previews), word fixes, cuts, the intro photo and effects
   change instantly, with no re-render.
4. The chat on the right runs your own `claude` CLI in the clip's folder. It
   may only edit `spec.json` and validate it. Its edits show up while it is
   still answering. Every change (yours or Claude's) can be undone.
5. **Render** produces the final mp4 on Modal (16 CPUs) or locally, then
   download it or send it to Telegram.

```sh
cd studio && npm install && npm run build -w editor     # once, and after editor changes
cd ../pipeline && uv sync --group server --group cloud  # cloud = the Modal SDK
modal deploy modal_app.py                               # analyze + render functions
uv run tetclipper serve                                 # http://localhost:8765/studio/
```

From a terminal: `tetclipper cut <url> 12:30 13:15 [--cloud|--local]`, then
`tetclipper spec show|validate|undo|render <job>`. The spec schema lives in
`studio/composition/src/spec.ts`. Run `npm run schema` there after changing
it, and `npm run gallery` to re-render the caption style stills.

## Status

Working end to end on real footage: range cuts, auto-found moments, live
editing with Claude Code, cloud analysis and parallel cloud renders (a
2-minute clip renders in under a minute on Modal). Runs on Windows and macOS
from source; the analysis can also run fully locally.

## Music

Each clip's spec can carry a music bed (`music` in `spec.json`): volume,
automatic ducking under speech, fades, offset and loop. The duck/fade curve
is computed per frame by the same rules in the live preview
(`studio/composition/src/music.ts`) and in the cloud mix
(`pipeline/tetclipper_pipeline/spec/music.py`), so what you hear in the
editor is what renders. Tracks come from your own uploads or the local
library at `~/.tetclipper/audio/` — fill it from your files
(`tetclipper audio import`) or with the free CC0 starter pack (Music tab;
needs a free [Jamendo](https://devportal.jamendo.com/) or
[Freesound](https://freesound.org/apiv2/apply/) key). NC and ND licences are
never fetched; CC-BY needs an explicit opt-in.

## Layout

```
pipeline/   Python package — the processing pipeline, CLI, web server, Modal app
studio/     Studio: Remotion composition (spec → video) + the browser editor
```

The old Tauri desktop app was retired in favour of Studio (it lives in git
history before the `retire desktop app` commit).

## Install from source (Windows or macOS)

You need git, [Node 22+](https://nodejs.org), [uv](https://docs.astral.sh/uv/),
the [Claude Code CLI](https://claude.com/claude-code) (logged in, for chat and
judging), and optionally a [Modal](https://modal.com) account for the cloud GPU.

```sh
git clone <your tetclipper repo URL> && cd tetclipper
cd studio && npm install && npm run build -w editor && cd ..
cd pipeline && uv sync --group pipeline --group server --group cloud
modal deploy modal_app.py          # optional: cloud analysis + rendering
uv run tetclipper serve            # → http://localhost:8765/studio/
```

Without Modal everything runs on your machine: the speech/audio models
(~4–5 GB) download on first use, and a caption-capable static ffmpeg is
fetched automatically. A GPU-less laptop is slow (minutes per minute of
video), which is what the cloud path is for.

## Development

```sh
# pipeline tests
cd pipeline && uv sync --group dev --group pipeline && uv run pytest

# Studio from a terminal
uv run tetclipper cut  "https://youtu.be/..." 12:30 13:15 --captions sermon   # exact range
uv run tetclipper find "https://youtu.be/..." 30:00 60:00 --top 5             # Claude finds moments
uv run tetclipper spec show|validate|undo|render <job> [--clip N]

# the original full auto-clipper (ffmpeg render, scoring audit)
uv run tetclipper run "https://www.youtube.com/watch?v=..." --llm claude

# editor dev server with hot reload (proxies the API on :8765)
cd studio && npm run dev -w editor          # http://localhost:5174/studio/

# composition: Remotion Studio on the local fixture, schema + gallery
cd studio/composition && npm run studio
npm run schema && npm run gallery
```

## License

AGPL-3.0-or-later. Portions adapted from other open-source projects — see
`VENDORED-LICENSES.md` for the full provenance list.
