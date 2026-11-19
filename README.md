# tetclipper

**Long video in. Vertical clips out, edited by chatting with Claude Code.**

tetclipper is an open-source (AGPL-3.0) clip studio for sermons and talks. Paste a
YouTube link, pick a range (or let Claude find the best moments), and edit the
vertical 9:16 clip in a browser while chatting with Claude Code:

- **Smart camera**: the crop follows whoever is speaking, cuts on speaker
  changes, and punches in on laughter and loud moments.
- **Captions for mixed English/Swahili/Sheng**: 9 animated styles; doubtful
  words are flagged and re-heard in Swahili; a word list learns your fixes.
- **Find moments**: candidates scored by Claude Code (your own Claude plan,
  no API key) against laughter, energy and replay signals.
- **Editing**: dead air, stutters, cuts, an intro photo, a music bed that ducks
  under speech, and 17 effects (checklist, phone mockup, wall text behind the
  speaker, magazine cover…).
- **Cloud**: transcription, the camera and the speaker cutout run on a Modal GPU;
  renders run in parallel on Modal CPUs (a 2-minute clip in under a minute).
- **Telegram delivery**: send finished clips to your own bot.

## Studio (chat-driven clip editor)

A browser editor where you talk to Claude Code and watch the clip change.

1. Paste a YouTube link plus a range (12:30 → 13:15). Only that slice is
   downloaded, on this PC (YouTube blocks cloud IPs).
2. Transcription, diarization, audio events and the smart camera run on a
   Modal GPU (or this PC), and produce one `spec.json` for the clip: words,
   caption style, crop keyframes, punch-ins, intro photo, cuts, effects.
3. Most of the editor is a live Remotion preview of that spec. Every tool sits
   in one panel on the left (AI, Captions, Look, Intro & outro, Music, Effects,
   Overlays, Trim) and a timeline runs along the bottom: drag it to scrub, zoom
   with the slider or Ctrl+wheel, click an effect to open it. Changes show
   instantly, with no re-render.
4. **Overlays**: a photo, GIF or video on top of the clip (a logo in a corner,
   a floating GIF). Drag it on the preview, pull a corner to resize, drag its
   bar on the timeline to set when it shows. Uploaded files go into a shared
   team library. Delete removes the selected overlay or open effect.
5. The **AI** tab is a chat. Online it uses the model the admin picks; on the
   desktop it runs your own `claude` CLI in the clip's folder. It may only edit
   `spec.json`, and its edits show up while it is still answering. Every change
   (yours or the AI's) can be undone.
6. **Render** produces the final mp4 on Modal (16 CPUs) or locally, then
   download it, send it for review (online), or send it to Telegram (desktop).

### Review (online, for a team)

Editors press **Send for review** after rendering. The communication team opens
**Review**, watches each video and marks it **Good** or **Needs work**, with notes
at a time in the video. A video sent back opens on its notes in the editor;
the editor ticks them off and sends a new version. Good videos are downloaded
from Review and posted by hand. **Record** shows who edited, reviewed and
downloaded what. Roles come from Supabase: set a user's app metadata to
`{"role": "reviewer"}` for the communication team or `{"role": "admin"}`; anyone
else is an editor. The team guide is `docs/TEAM-GUIDE.md`.

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
(~4–5 GB) download on first use, and a static ffmpeg is fetched
automatically if the machine has none. A GPU-less laptop is slow (minutes per minute of
video), which is what the cloud path is for.

## Development

```sh
# pipeline tests (some need ffmpeg: on a PC without it on PATH, point
# TETCLIPPER_FFMPEG at ~/.tetclipper/bin/ffmpeg.exe)
cd pipeline && uv sync --group dev --group pipeline && uv run pytest

# Studio from a terminal
uv run tetclipper cut  "https://youtu.be/..." 12:30 13:15 --captions sermon   # exact range
uv run tetclipper find "https://youtu.be/..." 30:00 60:00 --top 5             # Claude finds moments
uv run tetclipper spec show|validate|undo|render <job> [--clip N]
uv run tetclipper spec dead-air|stutters|doubts|matte <job> [--clip N]

# editor dev server with hot reload (proxies the API on :8765)
cd studio && npm run dev -w editor          # http://localhost:5174/studio/

# composition: Remotion Studio on the local fixture, schema + gallery
cd studio/composition && npm run studio
npm run schema && npm run gallery
```

## License

AGPL-3.0-or-later. Portions adapted from other open-source projects — see
`VENDORED-LICENSES.md` for the full provenance list.
