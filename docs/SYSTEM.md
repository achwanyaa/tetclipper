# tetclipper: system brief for the online UI

This brief describes tetclipper as it works today and the online version we are about to build. It is written for
Claude Design, which will design the online UI. Every path below is an absolute path on this PC, so the files can be opened
directly.

> **Repo root:** `C:\Users\sajim\Desktop\tetclipper`
> The product's name is **tetclipper**, always lower case and nothing else.

---

## 0. What we want back from Claude Design

1. **The new online screens** in section 5: login, account menu, video source (Google Drive / upload), the AI model switch
   with per-message cost, the usage view, and later a Publish panel.
2. **A refresh of the existing Studio screens** in section 4. Keep the structure, the tools and the live video preview.
   Improve hierarchy, density, states and polish so it feels like a professional editing bay, not a developer tool.
3. **All states:** for every screen, its empty, loading, progress, error and success states (section 4.7 lists what exists
   today).
4. **Output format:** React + CSS that drops into the existing editor (`studio\editor\src`). Reuse or extend the CSS tokens
   in section 8 rather than inventing a parallel system. If that's not practical, mockups are fine, with every screen and
   state shown and the tokens named.

Out of scope: the look of the rendered video itself (caption styles, effects). That is product output made by the Remotion
composition. The UI only chooses and tunes it.

---

## 1. What tetclipper is

tetclipper is a **chat-driven studio that turns long sermon and talk videos into vertical 9:16 clips** for TikTok,
Instagram Reels and YouTube Shorts. Think of it as Claude Design for video:

- You give it a video and either an exact time range ("12:30 to 13:15") or ask it to **find the best moments**.
- A cloud GPU transcribes the speech word by word, tells speakers apart, follows the active speaker with a virtual camera
  (it crops 16:9 to 9:16 and keeps the face framed) and marks emphasised words.
- You see the clip **immediately as a live preview** (a Remotion Player in the browser, not a rendered video), with animated
  captions.
- You edit it in two ways, and both change the same document (the clip spec, section 6):
  - **By hand:** fix caption words, cut words or pauses, pick one of 9 caption styles, add an intro photo, music and
    effects, trim the start and end.
  - **By chatting with Claude** in a sidebar: "use sermon captions and put them a bit higher", "remove the dead air", "add
    a title card for the first 3 seconds". Claude edits the spec and the preview updates live while you watch.
- Every change, yours or Claude's, is one **undo step**.
- When it looks right you press **Render**. The cloud renders the final MP4 (about 1 minute for a 2-minute clip). You
  **download** it or send it to **Telegram**.
- Later: **publish** to the social platforms with one click, with a caption written per platform.

**Who uses it:** at most **5 people**, each with their own login and their own private workspace. The owner adds the
accounts; there is no public sign-up, no teams and no billing. The speakers are Kenyan preachers, so speech mixes
**English, Swahili and Sheng**. The speech model is weakest exactly there, so the UI must make doubtful captions easy to
find and fix (section 4.4).

---

## 2. Today vs. online

| | Today (local) | Online (what we're building) |
|---|---|---|
| Where the server runs | the owner's PC (`tetclipper serve`) | Modal (serverless cloud), a small CPU web container |
| Video source | a YouTube link plus a range, downloaded on the PC | **Google Drive** (Google Picker) or **upload** from the computer |
| Heavy work (transcribe, camera, cutout, render) | already on Modal GPUs and CPUs | the same, called directly from the cloud |
| Chat with Claude | the Claude Code CLI on the owner's PC | a **lean editor agent** on the Claude API: **Haiku 5.5** by default, **Sonnet 5.5** one click away |
| Users | 1, no login | up to 5, **each logs in**, each has a separate workspace |
| Delivery | Download, Telegram | Download, Telegram; later one-click **Publish** |

YouTube links are not available online (cloud IPs get bot-blocked); they keep working in the local Studio only.

---

## 3. End-to-end flow

```
Log in
  └─ New clip (left sidebar)
       ├─ Source: pick a file from Google Drive, or upload one
       ├─ Mode: "Exact range" (from / to)  or  "Find moments" (optional range, best 3/5/8/12)
       ├─ Caption style, speech language (English / Swahili / auto)
       └─ Start ──► progress in the sidebar (trim → transcribe → speakers → camera → spec)
                     Find moments adds a judging step; each moment becomes a clip with a 0–100 score
  └─ Open a clip ──► Canvas: live 9:16 preview + tabs (Captions, Style, Intro, Music, Effects, Trim)
       ├─ edit by hand (each change saves automatically, one undo step)
       ├─ chat with Claude on the right (it edits the same clip; the preview updates live)
       ├─ check doubtful captions (Swahili/Sheng), teach the word list
       └─ Render ──► progress % in the toolbar ──► Download · Telegram · (later) Publish
```

Timings to design around:
- **Analysis:** about 1–3 minutes for a 1-minute range. Find moments on a long video takes longer.
- **Chat reply:** a few seconds to about 30 seconds. Claude streams short notes ("Cutting 6 pauses…") while it works.
- **Render:** about 45–60 seconds for a 2-minute clip.
- **Cutout:** the speaker matte some "behind the speaker" effects need takes about 1–2 minutes and is generated once per
  clip.

Long tasks are background jobs: the page gets progress events and must survive the user switching clips, refreshing, or
leaving and coming back.

---

## 4. The screens as they exist today

Run it live (section 10), then open the clip **"The Worthy Lamb With Pst Catherine"** in the sidebar. It is a real
6.5-minute clip with 922 caption words, 39 cuts, 49 punch-in zooms (placed by the camera director), Beast captions and an
intro photo. It has no music yet.

### 4.1 Layout
A three-column app shell, full height, no page scroll. CSS: `.studio { grid-template-columns: 260px 1fr 360px }`, with a
`max-width: 1100px` breakpoint that tightens it to `220px 1fr 300px`.

| Left: Sidebar (260 px) | Center: Canvas (flexible) | Right: Chat (360 px) |
|---|---|---|
| new clip form, progress, jobs and clips | toolbar, 9:16 preview, tabs, tool panel | chat with Claude about this clip |

Code: `C:\Users\sajim\Desktop\tetclipper\studio\editor\src\App.tsx`

### 4.2 Sidebar
Code: `C:\Users\sajim\Desktop\tetclipper\studio\editor\src\components\Sidebar.tsx`

- **New clip form**
  - A mode toggle: **Exact range** | **Find moments** ("Claude finds the best moments for you").
  - Source input: "YouTube link". Online this becomes the Drive / upload picker (section 5.3).
  - `from` / `to` time inputs (mm:ss or h:mm:ss). They are optional in Find moments mode.
  - Find moments only: **Best 3 / 5 / 8 / 12 moments**.
  - Caption style (9 styles) and language (English / Swahili / auto).
  - "Analyse on cloud GPU" / "Analyse on this PC". Online it is always the cloud, so this control goes away.
  - Primary button: "Cut 0:45" (shows the length), "Find moments" or "Working…".
  - Hints: "Range must be 3 s – 10 min.", "Search at least a minute.", "No range = the whole video (long download)."
- **Progress block** (while a cut or find runs): a thin bar, the current step message, and on failure the error with
  "dismiss".
- **Jobs list**, newest first. Each job shows:
  - its title (the video name) and its range, e.g. "12:30 – 13:15", or "no clip yet"
  - "✦ find moments here": re-search the same slice, reusing the analysis
  - its clips: "clip 1", a **score** chip (0–100, the judge's score, only for found moments), the caption style label,
    and a dot when it has been rendered; hovering shows the moment's summary
  - the open clip is highlighted

### 4.3 Canvas: toolbar and preview
Code: `C:\Users\sajim\Desktop\tetclipper\studio\editor\src\components\Canvas.tsx`

- **Toolbar:**
  - left: title "The Worthy Lamb With Pst Catherine · clip 1", **↶ Undo** (yours or Claude's) and the version "v12"
  - right: **⬇ Download** (or "Download (older)" when there are edits after the last render), **✈ Telegram** /
    "Sending…", and the primary **Render** / "Rendering 42%"
  - Banner: "Render failed: …"
- **Stage:** the live Remotion `<Player>` at 1080×1920, scaled to fit, with play/pause, scrubber, space to play and click
  to play, on a near-black stage (`#08090a`). It takes about 52% of the height. If the spec is invalid: "This spec can't be
  previewed (invalid). Undo the last change."
- **Tabs:** Captions · Style · Intro · Music · Effects · Trim, over a scrollable panel that takes about 38% of the height.
- The playhead is shared: clicking a word jumps the player, and new effects are added at the playhead.

### 4.4 Tab panels
All in `C:\Users\sajim\Desktop\tetclipper\studio\editor\src\components\`.

**Captions**: `Transcript.tsx`, `CheckBar.tsx`, `WordList.tsx`
- **Check bar** (top), for doubtful captions:
  - A button that checks the captions: it finds words the speech model may have misheard and re-listens to them in Swahili.
  - Then it steps through flagged spans one at a time: play from here, the suggested alternative (e.g. "ebu tusome"),
    **"It's right"**, an input "or type what was said…", and **next ▸**.
  - When nothing is flagged: "No captions flagged."
  - A **Word list** button opens the learning list.
- **Word list:**
  - **Learned fixes**: "Every caption fix is remembered and applied to new clips automatically." Shows old → new, or
    "(removed)".
  - **Phrases**: "Swahili/Sheng words, names and phrases the speech model should expect." Includes chips of common sermon
    words to click-add, and an input "add a word or phrase (e.g. Pst Catherine)" with **Add**.
- **Transcript**: every word as a token in reading order.
  - The word under the playhead is highlighted, emphasised words are marked, and cut words appear struck through as a
    restorable block ("restore this cut").
  - Hint line: "Click a word to jump · double-click to fix it · shift-click to select a span (then cut, hide, or ask
    Claude)".
  - Selection actions: **✂ Cut out**, **Hide/show** (keep the audio, hide the caption), **Emphasis**.

**Style**: `StylePanel.tsx`
- A **gallery of the 9 caption styles**, each card showing a still rendered on real footage:
  - Classic: white with a gold spoken word
  - Beast: MrBeast caps, yellow and red
  - Hormozi: bold caps, green spoken word
  - Minimal: clean white, no highlight
  - Karaoke pop: blue pill on the spoken word
  - Sermon: elegant serif, words fade in
  - One word: one big word at a time
  - Boxed: white text on a black bar
  - Neon: glowing caps with emoji
- The stills are in `C:\Users\sajim\Desktop\tetclipper\studio\editor\public\styles\` (`classic.png`, `beast.png`,
  `hormozi.png`, `minimal.png`, `karaoke-pop.png`, `sermon.png`, `one-word.png`, `boxed.png`, `neon.png`).
- **Controls:**
  - Captions on/off
  - sliders for Position %, Size px and Words per line
  - colour pickers for Text, Spoken (the active word) and Emphasis
  - toggles for UPPERCASE, Auto emoji and Progress bar

**Intro**: `IntroPanel.tsx`
- Add a photo (an image file) shown full screen at the start.
- Duration slider, 0.5–5 s.
- Fill: **cover** (crop to fill) or **contain** (letterbox).

**Music**: `MusicPanel.tsx`
- Empty state: "No music. Pick a track below, upload one, or ask Claude."
- When set: "♪ track name", volume, **duck** (how much the music dips while someone speaks), start offset, fade in and out,
  and loop.
- Sources:
  - the local music library, with "use" on each track
  - upload a track
  - fetch free tracks from Jamendo / Freesound when a free key is set ("free Jamendo client id")
- Remove music.

**Effects**: `EffectsPanel.tsx`
- A catalogue of 22 effects in 4 groups. Each has a label and a one-line hint, and is added at the playhead with defaults:

  | Group | Effects |
  |---|---|
  | Graphics | Checklist, Headline wall, Chart, Glass type, Title card, Emoji |
  | Camera | Punch-in, Digital zoom, Vertigo, Pull-back reveal, Zoom-through cut, Shake, Flash |
  | Styles | Phone mockup, UI world, Paper cut, Doodle, Orbit |
  | Behind the speaker | Couch wall, Frame break, Green screen, Cover story |

- The "Behind the speaker" effects need the **cutout** (a speaker matte made on the GPU). Until it exists:
  - Those items read "· needs cutout".
  - A banner explains: "Behind-the-speaker effects need the speaker cut out (about 1–2 min on the cloud GPU). Until then
    they draw in front."
  - The banner has a button that starts the cutout.
- Below the catalogue is the list of placed effects in time order. Each row shows its time and editable fields (text,
  items, colours, amount, duration) and a delete button.
- Empty state: "No effects yet. Pick one above (added at the playhead), or ask Claude."
- A real clip can hold about 50 effects, so the list must stay scannable.

**Trim**: `TrimPanel.tsx`
- **Dead air**: removes long pauses.
  - Two modes: **Natural** keeps short sentence pauses; **Tight** is snappier.
  - A toggle also removes um/uh fillers.
  - A live preview of the result ("6 cuts · −4.2 s · 2 fillers", or "nothing to cut") appears before you press **Remove
    dead air**.
- **Stutters**: removes repeated words, cut-off words and false starts. Deliberate repetition is kept.
  - Preview: "3 found · −1.8 s (hover to list)".
  - Then **Remove stutters**.
- **Start / End**, each with:
  - jump-to
  - nudges: −1s, −0.2, +0.2, +1s
  - "at playhead"
- **Cuts list**: every cut with a jump link and "restore".

### 4.5 Chat (right column)
Code: `C:\Users\sajim\Desktop\tetclipper\studio\editor\src\components\Chat.tsx`

- Header: the title, a **"run scripts"** toggle (lets Claude run helper scripts), and **"new chat"**.
- Empty state: "Tell Claude how you want this clip. It edits the spec and the preview updates live." It is followed by
  example chips:
  - "Use sermon captions and put them a bit higher"
  - "Cut the first sentence and any long pauses"
  - "Add a title card for the first 3 seconds with the main point"
  - "Check the doubtful captions (Swahili/Sheng) and fix what you can"
  - "Remove the dead air"
  - "Edit out stutters and false starts"
- The message log shows user bubbles (`--user`) and assistant text. While Claude works:
  - its streamed text
  - a running list of short notes about what it is doing
  - a typing indicator
- Composer:
  - a textarea ("Describe the edit…" / "Claude is editing…"); Enter sends, Shift+Enter adds a new line
  - a toggle "include playhead" / "include 3 selected words", which tells Claude the playhead time and the selection
  - **Send**
- Error banner today: "Claude Code CLI not found on this machine…". Online this becomes API errors (section 5.4).

### 4.6 Shared plumbing the UI relies on
- **Autosave:** every edit is saved about 0.35 s after the last change, with a short reason ("caption colour", "captions:
  beast"). The reasons become the undo history.
- **Live updates:** the server pushes progress and chat events over SSE (`onEvent` in `api.ts`).
- **Files:** media is served from `/files?path=…`; uploads go to `/api/upload`.

### 4.7 States that exist today
| State | Where | Current treatment |
|---|---|---|
| Nothing open | center | "tetclipper Studio — Paste a YouTube link and a range on the left, or open a clip." |
| Job running | sidebar | progress bar + step message |
| Job failed | sidebar | error text + "dismiss" |
| Generic error | center top | red banner, click to dismiss |
| Invalid spec | stage | banner telling you to undo |
| Rendering | toolbar | "Rendering 42%" on the Render button |
| Render failed | under the toolbar | banner |
| Render outdated | toolbar | "Download (older)" |
| Claude working | chat | notes + typing dots, composer disabled |
| No doubts | check bar | "No captions flagged." |
| No effects / music | panel | an empty-state line pointing to the catalogue or Claude |
| Cutout needed | effects | banner + progress |

---

## 5. New screens and changes for the online version

### 5.1 Login
- A username and password form, centered, branded "tetclipper". No sign-up and no "forgot password"; the owner resets
  passwords.
- Error: "Wrong username or password." Option: "Keep me signed in".
- Everything else (Studio, files, API) is behind the login.

### 5.2 Account menu (top of the sidebar or the toolbar)
- The user's name and initial avatar.
- This month's AI spend for this user (e.g. "$0.42 this month") and a link to **Usage**.
- Connected accounts: Google Drive (connected / connect), Telegram chat, and later the social accounts.
- **Log out**.

### 5.3 Video source (replaces the "YouTube link" input)
- Two choices: **Choose from Google Drive** (opens Google's own Picker in a popup) and **Upload a video** (drag and drop
  or browse).
- **Drive:**
  - The first time, the user signs in with Google and grants access only to files they pick (scope `drive.file`).
  - After picking, show a **file card**: name, size, duration if known, a "change" link, and the Drive thumbnail if
    available.
  - Only the chosen range is fetched from Drive, not the whole 1–2 GB file. The UI can say so ("only 12:30–13:15 is
    downloaded").
- **Upload:**
  - Large files (1–2 GB sermons) upload straight to cloud storage with a progress bar, speed and time left, and a cancel
    button. A failed upload must be retryable.
  - Upload first, then choose the range, or choose the range while it uploads.
- **Range:** the same from/to inputs and the Exact range | Find moments toggle as today.
  - Optional, nice to have: a small preview player to scrub to the moment and set from/to with "set start" / "set end".
  - A Drive-hosted file can be previewed with Google's embed; an upload can be previewed locally before it finishes.
- A YouTube link pasted anywhere gets a clear message: "YouTube links work in the desktop version only. Download the video
  to Drive or upload it."

### 5.4 Chat: model switch and cost
- A compact switch in the chat header:
  - **Haiku 5.5**: fast and cheap. The default, for everyday edits.
  - **Sonnet 5.5**: smarter, about 20× the cost. For tricky multi-step edits.
- Each assistant message shows its cost in small muted text, e.g. "Haiku · $0.003" (input/output tokens on hover). The
  header shows the session total.
- The "run scripts" toggle is gone; the online agent has built-in tools instead.
- Errors to design for:
  - "Claude is busy, try again in a moment" (rate limit / overloaded)
  - "Monthly AI budget reached" (an optional per-user cap)
  - "That edit didn't validate, nothing changed"
- When Claude changes the clip, the message shows a short summary of what changed ("6 cuts added · captions → Sermon")
  with an inline **Undo**.
- Expected cost: Haiku is about **$0.0025 per message** (about $0.03 per finished clip). Sonnet is about **$0.05 per
  message**.

### 5.5 Usage (a page or a modal from the account menu)
- Per user, this month: AI spend split by model (chat, find moments); clips analysed; renders.
- Cloud compute against the **Modal free credit of $30/month**, shared by everyone. This is the owner's concern; show it to
  everyone, or only to the owner.
- A simple table or bars is enough. It's 5 people.

### 5.6 Admin (owner only, minimal)
- Users are created from the command line today (`tetclipper user add <name>`). An optional small "Users" page would list
  up to 5 users with last active, AI spend, reset password and remove.

### 5.7 Publish panel (later phase; design it now so it has a home)
- Opens from the toolbar after a render: **Publish**.
- Connected platforms: **TikTok**, **Instagram Reels**, **YouTube Shorts**, **Facebook Reels**. Each has
  connect/disconnect and the account name.
- Per platform, a caption that Claude drafts from the transcript, editable. TikTok gets a caption with hashtags; Instagram
  gets a caption with hashtags; YouTube gets a title and description; Facebook gets a caption.
- **Publish to selected** in one click, then per-platform status: queued → uploading → live (with a link) or failed (with
  a reason).
- Note for the UI: until each platform approves the app, TikTok posts are private-only and YouTube uploads are private.
  Show that honestly ("will post as private until approved").

### 5.8 Things that change in existing screens
- The sidebar loses "Analyse on this PC". Jobs and clips belong to the logged-in user only.
- The empty state becomes: "Choose a video from Drive or upload one, then pick a range."
- Telegram settings move into the account menu.
- Tablet support (≥ 1024 px wide, landscape) matters more online. A phone needs only to view clips, download them and
  later publish; editing on a phone is not required.

---

## 6. The data the UI edits: the clip spec

Every clip is **one JSON document**, `spec.json`. The editor previews it, Claude edits it, and the renderer renders it, so
the UI is a view over this one object. **Times are in seconds of the source video.** The output timeline is the intro,
followed by the source range minus the cuts.

- **Source of truth (zod):**
  - `C:\Users\sajim\Desktop\tetclipper\studio\composition\src\spec.ts`
- **JSON Schema** (generated):
  - `C:\Users\sajim\Desktop\tetclipper\studio\composition\spec.schema.json`
  - a copy for the Python side: `C:\Users\sajim\Desktop\tetclipper\pipeline\tetclipper_pipeline\spec\spec.schema.json`
- **Output timeline maths** (cuts, intro, frames):
  - `C:\Users\sajim\Desktop\tetclipper\studio\composition\src\timeline.ts`

| Field | What it is | Edited in |
|---|---|---|
| `title` | the video title | (shown in the toolbar) |
| `source {src, start, end, width, height}` | the media file and the clip's range | Trim (start/end) |
| `intro {src, duration 0.5–5, fit cover/contain}` or null | the opening photo | Intro |
| `cuts [{start, end}]` | removed spans (pauses, stutters, words) | Captions (✂), Trim, chat |
| `music {src, volume, duck, offset, fadeIn, fadeOut, loop}` or null | the music bed | Music |
| `words [{text, start, end, emphasis?, hidden?, speaker?}]` | every caption word | Captions |
| `doubts [{from, to, reason, alt?}]` | flagged word spans (word indexes) with a suggested alternative | Check bar |
| `captions {enabled, style, position?, size?, maxWords?, color?, activeColor?, emphasisColor?, uppercase?, emoji?}` | caption look | Style |
| `crop {keyframes [{t, x, y, zoom, cut?}]}` | the virtual camera path (set automatically) | (not exposed yet) |
| `effects [{type, at, duration, …}]` | overlays and camera moves (22 kinds) | Effects |
| `matte {src, start}` | the speaker cutout video, when made | Effects (cutout banner) |
| `progressBar {enabled, color}` | a thin progress bar | Style |

A short example. The `source`, `intro`, first cut, captions, keyframe and punch-in come from the sample clip; the music,
the doubt, the Swahili words and the title card are added to show every field:

```json
{
  "version": 1,
  "title": "The Worthy Lamb With Pst Catherine",
  "source": { "src": "media.mp4", "start": 6.6, "end": 396.6, "width": 1920, "height": 1080 },
  "intro": { "src": "studio/clip_00/assets/photo.jpg", "duration": 2, "fit": "cover" },
  "cuts": [{ "start": 9.176, "end": 11.778 }],
  "music": { "src": "studio/clip_00/assets/worship-pad.mp3", "volume": 0.2, "duck": 0.35, "offset": 0, "fadeIn": 1, "fadeOut": 1.5, "loop": true },
  "words": [
    { "text": "it", "start": 5.044, "end": 5.124, "emphasis": true, "speaker": "S0" },
    { "text": "ebu", "start": 9.1, "end": 9.32, "speaker": "S0" },
    { "text": "tusome", "start": 9.32, "end": 9.8, "speaker": "S0" }
  ],
  "doubts": [{ "from": 1, "to": 2, "reason": "low confidence", "alt": "ebu tusome" }],
  "captions": { "enabled": true, "style": "beast", "emphasisColor": "#ffffff" },
  "crop": { "keyframes": [{ "t": 5, "x": 0.5, "y": 0.5, "zoom": 1 }] },
  "effects": [
    { "type": "punch-in", "at": 8.1, "duration": 2.1, "amount": 1.12 },
    { "type": "hook", "at": 6.6, "duration": 3, "text": "Worthy is the Lamb", "background": "#FFD700", "color": "#000000" }
  ],
  "progressBar": { "enabled": false, "color": "#FFD700" }
}
```

The real file for the sample clip (922 words, 144 KB) is at
`C:\Users\sajim\.tetclipper\jobs\20261016-105403-8f61c5\studio\clip_00\spec.json`.

Each clip folder `C:\Users\sajim\.tetclipper\jobs\<job id>\studio\clip_NN\` holds:
- `spec.json`
- `history\` (one snapshot per undo step)
- `chat.json`
- `transcript.md`
- `assets\` (intro photo, music)
- `render.mp4` (after a render)
- `fg.webm` (the cutout)

---

## 7. Constraints

- **The preview must stay a live Remotion Player.** That is the core of the product: edits show instantly with no
  re-render. The preview is 1080×1920 at 30 fps and must keep 9:16 at any panel size.
- **Rendering is remote and takes about a minute.** Show progress, never block the editor while it runs, and mark a render
  outdated once the clip is edited after it.
- **Long jobs are asynchronous.** Analysis and find moments take minutes. A cloud web request times out at 150 s, so
  everything long is a job with progress events. Design for "come back later" (the job list shows status).
- **Mixed English / Swahili / Sheng captions.** Doubtful words need high visibility and a fast fix loop (listen → accept,
  or type → next). Fixes are learned and applied to future clips.
- **Big inputs:** 1–2 hour sermons, 1–2 GB files, and clips with 900+ words and about 50 effects. Lists need to scroll and
  scan well, and the transcript must stay fast.
- **Cost-aware AI:** show what each chat message costs, default to the cheap model, and keep the expensive one one click
  away.
- **Five users and private workspaces.** No sharing between users in this version.
- **Desktop first** (1280–1920 wide), tablet second (landscape ≥ 1024). Phone: view, download and publish only.
- **Dark only** is fine. It's an editing bay: the video must be the brightest thing on screen.

---

## 8. Current visual language

The "editing bay" theme: near-black panels, warm off-white text and a single **amber accent**. Inter at 14 px, 8 px radius.
Tokens from `C:\Users\sajim\Desktop\tetclipper\studio\editor\src\styles.css`:

```css
--bg:        #0e0f11;   /* app background */
--panel:     #16181b;   /* sidebars, panels */
--panel-2:   #1d2024;   /* raised controls, inputs */
--line:      #2a2e33;   /* borders, dividers */
--text:      #e8e6e1;   /* primary text */
--muted:     #8b8f96;   /* secondary text */
--accent:    #f5b83d;   /* amber: primary buttons, active tab, selection */
--accent-ink:#1a1405;   /* text on amber */
--danger:    #ff6b5b;   /* errors, delete */
--user:      #2b3340;   /* user chat bubble */
--radius:    8px;
/* stage behind the player: #08090a */
```

Feel free to extend the palette (success and info colours, an elevation scale, a type scale), but keep the amber identity
and the dark stage. Class names in use: `.studio`, `.center`, `.canvas`, `.toolbar`, `.stage`, `.tabs`, `.panel`,
`.banner.error`, `.empty`, `.run`, `.bar`, `.jobs`, `.job`, `.clip`, `.score`, `.gallery`, `.style-card`, `.controls`,
`.fx-group`, `.msg.user`, `.msg.assistant`, `.examples`, `.notes`, `.typing`, `.primary`, `.link`, `.toggle`.

---

## 9. Where everything lives

```
C:\Users\sajim\Desktop\tetclipper\
├─ README.md
├─ docs\SYSTEM.md                       ← this brief
├─ studio\
│  ├─ editor\                           ← the Studio web app (React + Vite, served at /studio/)
│  │  ├─ public\styles\*.png            ← caption style stills (9)
│  │  ├─ vite.config.ts                 ← base /studio/, proxies /api and /files to :8765
│  │  └─ src\
│  │     ├─ App.tsx                     ← app shell, state, autosave, undo, render/cut/find actions
│  │     ├─ api.ts                      ← invoke(command), onEvent (SSE), upload, mediaUrl
│  │     ├─ retext.ts                   ← retiming when a caption is retyped
│  │     ├─ styles.css                  ← all styles and tokens
│  │     └─ components\
│  │        ├─ Sidebar.tsx              ← new clip form, progress, jobs/clips
│  │        ├─ Canvas.tsx               ← toolbar, Player, tabs
│  │        ├─ Transcript.tsx           ← Captions tab (word tokens, selection actions)
│  │        ├─ CheckBar.tsx             ← doubtful captions stepper
│  │        ├─ WordList.tsx             ← learned fixes + phrases
│  │        ├─ StylePanel.tsx           ← style gallery + controls
│  │        ├─ IntroPanel.tsx
│  │        ├─ MusicPanel.tsx
│  │        ├─ EffectsPanel.tsx         ← effect catalogue + placed effects
│  │        ├─ TrimPanel.tsx            ← dead air, stutters, start/end nudges
│  │        └─ Chat.tsx                 ← Claude chat sidebar
│  └─ composition\                      ← the Remotion video (shared by preview and render)
│     ├─ spec.schema.json
│     ├─ scripts\                       ← render.mjs, bundle.mjs, gallery.mjs (style stills), export-schema.ts
│     └─ src\
│        ├─ spec.ts                     ← THE clip schema (zod), FPS/WIDTH/HEIGHT
│        ├─ timeline.ts                 ← source time ↔ output frame maths
│        ├─ VerticalClip.tsx            ← layers: video → behind-speaker → speaker → overlays → captions → intro → music
│        ├─ VideoLayer.tsx, Intro.tsx, music.ts, Root.tsx
│        ├─ captions\                   ← Captions.tsx, presets.ts (the 9 styles), chunk.ts, emoji.ts
│        ├─ effects\                    ← Overlays.tsx, graphics.tsx, styles.tsx, behind.tsx
│        └─ dev\DevRoot.tsx             ← dev compositions per effect and style (Remotion Studio)
└─ pipeline\                            ← Python backend (uv project)
   ├─ modal_app.py                      ← Modal cloud app: web, analyze, build_spec, matte, second_listen, render, render_chunk
   ├─ tests\
   └─ tetclipper_pipeline\
      ├─ cli.py                         ← `tetclipper` command (serve, cut, find, spec, …)
      ├─ server\
      │  ├─ app.py                      ← HTTP server: /api commands, SSE events, /files, /api/upload
      │  ├─ studio.py                   ← every Studio command (list below)
      │  └─ studio_chat.py              ← chat with Claude (to be replaced by the lean API agent)
      ├─ spec\                          ← build, store (history/undo), schema, timeline, silence (dead air), stutters,
      │                                   doubts, glossary (word list), matte, find, render, music, emphasis
      ├─ ingest\                        ← download/trim the source (normalize.trim does the range cut)
      ├─ asr\, diarize\, events\        ← transcription (whisperX), speakers, laughter/applause events
      ├─ camera\                        ← the virtual camera director (active-speaker framing)
      ├─ scoring\                       ← find-moments judging (judging.md holds the rubric)
      ├─ cloud\                         ← client for the Modal functions
      └─ delivery\                      ← Telegram
```

**Server commands the UI calls** (`invoke(name, args)` → `POST /api/cmd/<name>`, in `server\studio.py`):

| Group | Commands |
|---|---|
| Jobs and clips | `studio_jobs`, `studio_clip`, `studio_info` |
| Editing | `studio_save`, `studio_undo` |
| New work | `studio_cut`, `studio_find` |
| Assets | `studio_attach` (intro photo / music) |
| Output | `studio_render`, `studio_telegram` |
| Trim | `studio_dead_air`, `studio_stutters` |
| Effects | `studio_matte` (cutout) |
| Captions | `studio_doubts`, `glossary_get`, `glossary_save` |
| Settings | `studio_settings` |
| Chat | `studio_chat_send`, `studio_chat_reset` |

The online version adds login/logout, me (the user plus usage), Drive file registration, upload URLs, and the model choice
on `studio_chat_send`.

**Data on disk:** `C:\Users\sajim\.tetclipper\`:
- `jobs\<job id>\` for analysis checkpoints and the `studio\clip_NN\` folders
- the job database
- the word list

Online, the same layout lives per user at `/data/users/<name>/` on the Modal volume.

---

## 10. Running it locally to see the real thing

The server is usually already running at **http://localhost:8765/studio/**. To start it:

```powershell
cd C:\Users\sajim\Desktop\tetclipper\pipeline
uv run tetclipper serve          # → http://localhost:8765/studio/
```

For live-reloading UI work, run Vite next to it. It proxies `/api` and `/files` to the server on port 8765:

```powershell
cd C:\Users\sajim\Desktop\tetclipper\studio\editor
npm run dev                      # → http://localhost:5173/studio/
```

Open **"The Worthy Lamb With Pst Catherine" → clip 1** in the sidebar to see an edited clip. It has an intro, 39 cuts,
49 punch-ins and Beast captions. Each tab, the chat empty state with its example chips, and Render all work. Add a few
effects and music from their tabs to see those panels with content.
