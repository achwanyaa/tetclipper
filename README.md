# tetclipper

**Long video in. Scored vertical clips out. Everything runs on your machine.**

tetclipper is an open-source (AGPL-3.0) desktop app that takes a YouTube URL or a
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

Working end to end: hour-long podcast in, rendered/captioned/scored 9:16 clips
out, validated on real footage. The Instagram feedback loop ships in-app
(sync, clip↔Reel matching, snapshot history, automatic score calibration).
Builds are currently unsigned — install from source below.

Runs on macOS (Apple silicon) and Windows 10/11 x64. The Windows path is
validated on every push by the `windows` workflow: env resolve, full test
suite, NSIS build, silent install, and a launch of the installed app on a
clean VM.

## Music & SFX

Every clip gets its own music/sfx track, backed by a local library at
`~/.tetclipper/audio/` (files copied in, plus an index of tags/bpm/licence).
The library starts empty — fill it from your own files, or pull
Creative-Commons tracks from Freesound/Jamendo straight from the app.

- **Local import** — Library tab → **files**/**folder** opens a native
  picker. Kind (music vs. sfx) and tags are derived automatically; bpm is
  detected for music.
- **Online CC sources** — the Online tab searches Freesound (sound effects)
  and Jamendo (music), CC0-only by default. Both need a free API key, saved
  once in the app: [freesound.org/apiv2/apply](https://freesound.org/apiv2/apply/)
  and [devportal.jamendo.com](https://devportal.jamendo.com/) — the panel
  shows the signup link inline when a key is missing.
- **Suggestions** — **suggest audio** scores your library against the
  clip's music brief (genre/mood/bpm/energy) and the event timeline (cut
  boundaries, laughs), and proposes one music bed plus a few sfx stings.
  Suggested items show dashed on the track; accept one with its ✓, or
  delete it — nothing is ever auto-accepted.
- **Manual placement** — drag any library item onto the audio track,
  drag its edges to trim, drag its body to move it. Select an item for
  gain, fade in/out, loop, and duck controls.
- **Ducking** — music tagged to duck sidechains under speech automatically
  at render time (light/medium/heavy, from the clip's brief) so dialogue
  always stays legible; sfx never ducks.
- **Licence policy** — CC0 by default; a CC-BY item requires opting in
  ("allow attribution" in the Online tab) and is never silent about it — a
  `credits.txt` is written next to every rendered clip that uses one,
  listing its attribution. NC and ND licences are never fetched, full stop.

## Layout

```
pipeline/   Python package — the entire processing pipeline + CLI + web server
studio/     Studio: Remotion composition (spec → video) + the browser editor
app/        Tauri v2 desktop shell (React UI, Python sidecar)
```

## Install from source (macOS)

You need four tools: git, [Node](https://nodejs.org), [Rust](https://rustup.rs),
and [uv](https://docs.astral.sh/uv/). Then:

```sh
git clone <your tetclipper repo URL>
cd tetclipper/app
npm install
npx tauri build --bundles app
ditto src-tauri/target/release/bundle/macos/tetclipper.app /Applications/tetclipper.app
open /Applications/tetclipper.app
```

The app downloads its speech/audio models (~4–5 GB) on first run with a
progress UI, and fetches a caption-capable static ffmpeg automatically if the
machine has none. Scoring runs on Claude Code by default; your own Gemini API
key or a local Ollama model (reduced scoring quality) are one tap away in
onboarding.

## Install from source (Windows)

You need [Rust](https://rustup.rs), the Visual Studio **Desktop development
with C++** build tools, [Node](https://nodejs.org), git, and
[uv](https://docs.astral.sh/uv/) (`winget install --id astral-sh.uv -e`).
Then, in PowerShell:

```powershell
git clone <your tetclipper repo URL>
cd tetclipper\app
npm.cmd install
node_modules\.bin\tauri.cmd build --bundles nsis
# run the installer it produces:
Start-Process (Get-ChildItem src-tauri\target\release\bundle\nsis -Filter *-setup.exe).FullName
```

First run behaves the same as on macOS: models download behind a progress
bar, and a caption-capable static ffmpeg is fetched automatically.

## Development

```sh
# pipeline
cd pipeline && uv sync --group dev --group pipeline && uv run pytest
uv run tetclipper run "https://www.youtube.com/watch?v=..."

# pick the brain per run: --llm claude (default) | gemini | ollama
# own Gemini key from a terminal: TETCLIPPER_GEMINI_API_KEY=AIza...

# browser UI + API (instead of the desktop app)
uv run --group server tetclipper serve        # http://localhost:8765

# range mode: only 12:30-13:15 of a video, cut on this machine
uv run tetclipper cut "https://youtu.be/..." 12:30 13:15 --captions hormozi --language en

# hosted GPU (Modal): analyse there, render here
modal deploy modal_app.py
uv run tetclipper push "https://youtu.be/..."     # download here, analyse on Modal
uv run tetclipper pull <job_id> --render          # bring it back, render here

# app
cd app && npm install && npm run tauri dev
```

## License

AGPL-3.0-or-later. Portions adapted from other open-source projects — see
`VENDORED-LICENSES.md` for the full provenance list.
