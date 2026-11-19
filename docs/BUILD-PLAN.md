# Build plan: editor changes, then review

Written 2026-11-19 for the model that will build this. Read all of it before changing code. It was written from a read of the code at commit `3de5bb2`; if a file has moved since, trust the code and keep the intent.

## What the owner wants

tetclipper is a clip editor for a small church media team (sermon videos: 7–10 short vertical clips a week, some 1-hour horizontal videos). It is growing from one person's editor into a small team system. The work is in three phases, in this order:

1. **Editor changes.** A new layout with the tools and an AI chat on the left and a bigger preview, a timeline you can drag and zoom, effects that open when clicked on the timeline, and overlays (photo, GIF or video placed on top of the video by dragging).
2. **Review.** Editors send a rendered video for review. The communication team marks it Good or Needs work with notes, and downloads good videos to post by hand. A record shows who edited what.
3. **Full system review.** After both are built, review the whole system end to end and fix what you find, including problems the owner has not noticed.

Not in scope: posting to social platforms, platform statistics, scheduling. The owner dropped these for now. Do not add them.

## Rules that always apply

- **Cheapest way that works.** This is the owner's standing rule. Add no paid service, no new database and no always-on server. Say what a choice costs when it costs anything.
- **The app says "AI".** No provider or model-family name may reach the browser bundle. `npm run check:names -w editor` enforces this; it must pass.
- **Plain words in the UI.** Users are not technical. Short labels, no jargon.
- **Keep the existing style.** Colour tokens and fonts are in `studio/editor/src/styles.css` (`--bg`, `--sf`, `--ac` and the rest; light and dark themes both exist and both must keep working). Use the existing classes and patterns before adding new ones.
- **Git.** Work on a new branch off `main`, not on `main`. Commit only when the owner asks. The git author is `achwanyaa`. Never commit `env.local`, `.env.local` or anything with keys.
- **Do not deploy** (Modal or Vercel) without the owner saying so. Deploy steps are at the end.
- **Do not break the desktop mode.** The same server runs with no sign-in on a PC (`TETCLIPPER_AUTH` unset) and with Supabase sign-in online. Both must keep working.

## How the system is built today

| Part | Where | Notes |
|---|---|---|
| Clip spec | `studio/composition/src/spec.ts` | zod schema, the single source of truth. One `spec.json` per clip. All times are source seconds. |
| Composition | `studio/composition/src/` | Remotion. `VerticalClip.tsx` stacks the layers. `effects/Overlays.tsx` draws timed effects. |
| Schema for Python | `pipeline/tetclipper_pipeline/spec/spec.schema.json` | Generated: run `npm run schema -w composition` after any change to `spec.ts`. Python validates with it (`spec/schema.py`). |
| Editor | `studio/editor/src/` | Vite + React. `App.tsx` holds state, `components/Canvas.tsx` is the edit screen. |
| Server | `pipeline/tetclipper_pipeline/server/` | FastAPI. Every action is a `@command` function called as `POST /api/cmd/<name>` (`invoke()` in `api.ts`). `studio.py` has the editor commands. |
| Storage | Files on disk | Online this is one Modal volume. Shared things live in `home_dir()`; each signed-in user's work lives in `home_dir()/users/<user id>/` (`workspace_dir()`). |
| Sign-in | `server/app.py` | Supabase token checked in the `_require_token` middleware. Admin comes from `TETCLIPPER_ADMINS` or `app_metadata.role == "admin"`. |
| Render | `spec/render.py`, `cloud/remote.py`, `studio/composition/scripts/render.mjs` | Remotion in Modal containers. The soundtrack is built by ffmpeg in `cloud/remote.py`, not by Remotion. |
| Long videos | `spec/long_video.py` | Landscape videos send only the frames that show something extra through Remotion; the rest is one ffmpeg encode. This is what keeps a 1-hour render cheap. |
| AI chat | `server/studio_chat.py`, `server/agent.py` | Both carry a written description of the spec for the AI. |

Three places turn a spec's relative file paths into loadable URLs. A new field that holds a file path must be added to all three, or it will work in one place and fail in another:
- `resolveForPlayer` in `studio/editor/src/api.ts`
- `resolveAssets` in `studio/composition/scripts/render.mjs`
- any Python that reads the file directly (search `cloud/remote.py` for `spec["source"]["src"]` style reads)

Checks to run (also what CI runs, see `.github/workflows/ci.yml`):
- In `pipeline/`: `uv run --no-sync pytest -q`
- In `studio/`: `npm run typecheck -w composition && npm run build -w editor && npm run check:names -w editor`
- To run the app on the PC: `uv run --project pipeline --no-sync tetclipper serve`, then open `http://127.0.0.1:8765/studio/`. The server serves `studio/editor/dist`, so rebuild the editor first. If the owner's own server is already running on port 8765, do not kill it; ask, or use another port.

## Decisions already made

The owner chose these. Do not reopen them.

- Editor layout is "option A": one left panel holding every tool and the AI chat, the preview takes the rest, the timeline runs full width along the bottom.
- Review screen is "option 1": a list with tabs and the selected video beside it.
- No posting. The communication team downloads the video and posts by hand.
- A record of who edited what is required.

## Assumptions to confirm with the owner

These three questions were asked and not answered. Build with the defaults below and list them in your final report so the owner can change them.

| Question | Default used |
|---|---|
| Do overlays go on 1-hour videos too? | They work everywhere, but the first version is tuned for short clips. On a long video an overlay costs render time for as long as it is on screen; the panel says so. |
| Should a video overlay play its own sound? | No. Overlays are silent in this version. (Sound would need mixing in `cloud/remote.py`.) |
| Are uploaded overlays shared with the team? | Yes. One shared library, like the shared music library. |

Two more defaults: an editor is told about a sent-back video inside the app only (a badge), and a sent-back video goes to the editor who made it.

---

# Phase 1: editor changes

Build in the order below. Each step should leave the app working.

## 1.1 New layout

**Now:** `.editor` is a two-column grid: preview, timeline and AI bar on the left, a 400px inspector on the right (`Canvas.tsx`, `styles.css` around `.editor`).

**Target:**

```
┌──────────────────────────────────────────────────────┐
│ top bar (unchanged)                                  │
├──────┬───────────────┬───────────────────────────────┤
│ rail │ panel         │                               │
│ AI   │ (the open     │        preview (stage)        │
│ Capt │  tool, or     │                               │
│ Look │  the chat)    │                               │
│ ...  │               ├───────────────────────────────┤
│      │ render footer │ play button, time             │
├──────┴───────────────┴───────────────────────────────┤
│ timeline, full width                                 │
└──────────────────────────────────────────────────────┘
```

- Left side is about 420px: a narrow vertical rail of tab buttons (icon plus short label, at least 44px tall) and the panel body beside it.
- Tabs in order: AI, Captions, Look, Intro & outro, Music, Effects, Overlays, Trim. A Review tab is added in phase 2. The default tab is AI.
- The existing panels (`Transcript`, `StylePanel`, `IntroPanel`, `MusicPanel`, `EffectsPanel`, `TrimPanel`) move into the left panel unchanged. Keep the doubtful-captions badge and nudge.
- `RenderFooter` stays at the foot of the left panel with all its current states.
- Move the play button and time out from on top of the video to a row under the stage, so they never cover an overlay being dragged.
- Narrow windows: below about 900px wide the left panel stacks above the preview. It must stay usable, not perfect.

## 1.2 AI chat tab

**Now:** `AiBar.tsx` shows only the last reply on one line, cut off with an ellipsis. The full conversation is hidden in a History drawer.

**Target:** the AI tab is a normal chat.

- Every message shows in full, wrapped, user messages on the right and AI replies on the left. The panel scrolls and stays pinned to the newest message.
- The reply streams in as it arrives (the `delta` events), with the tool notes and typing dots shown while the AI works.
- Under each AI reply: its cost when known, and Undo on the most recent AI reply only (it calls the existing `undo`).
- Errors show as a message in the thread, in the danger colour.
- Composer at the bottom: a text area that sends on Enter and adds a line on Shift+Enter, the playhead/selection context toggle, and Send. The quick-ask chips sit above it.
- Keep "New chat" and the "Let the AI run scripts" switch, in a small menu or row at the top of the tab. Remove the History drawer.
- Keep the "AI is not set up" notice.

**Important:** the chat state (messages, busy, the live text) must not live inside a component that unmounts when the user switches tabs, or a reply that arrives while another tab is open is lost. Move it into a hook called from `Canvas` (for example `useChat(data)`), and let the AI tab only draw it. When the AI is working and another tab is open, show a small dot on the AI rail button.

## 1.3 Timeline: drag, zoom, scroll

**Now:** `Timeline.tsx` seeks on click only. The whole clip always fits the width.

**Target:**

- **Drag to scrub.** Pressing anywhere on the ruler or lanes seeks there, and moving while pressed keeps seeking. Use pointer events with pointer capture. Limit seeks to one per animation frame. If the video was playing, pause while dragging and resume on release. A press that starts on a button (a word, an effect, an overlay bar) must not scrub.
- **Playhead handle.** Give the orange line a grab handle at the top and show the current time beside it while dragging.
- **Zoom.** A zoom slider from 1× (fit) up to about 20×, and Ctrl+wheel over the timeline. When zoomed, the lanes scroll sideways and the view follows the playhead during playback.
- **Captions lane.** It is a moving window of words around the playhead, not placed by time. Keep it that way and keep it outside the scrolling area so it stays put.
- Lanes after this step, top to bottom: Captions (fixed), then in the scrolling area: ruler, Overlays (added in 1.5), Effects, Cuts.
- The ruler's tick spacing must adapt to the zoom (reuse `NICE_STEPS`, picking by visible seconds).

Long videos are an hour: check that scrubbing and zoom stay smooth with a 60-minute timeline and a few hundred cuts.

## 1.4 Click an effect to open it

- Effect marks on the timeline become real buttons with a label for screen readers (`<effect name> at <time>`).
- Clicking one switches the left panel to Effects, opens that effect's edit fields, scrolls it into view and seeks to its start.
- `EffectsPanel` keeps its own `open` state today; make the open effect controllable from `Canvas` (a `selectedEffect` index passed down, with a setter).
- Very short effects are only 6px wide today. Give them a larger hit area (at least 20px) without changing how they look.

## 1.5 Overlays

A new kind of layer: a photo, GIF or video placed on top of the video, positioned by dragging on the preview.

### Spec

Add a top-level `overlays` list to `clipSpecSchema` in `spec.ts` (default empty). Each overlay:

| Field | Type | Meaning |
|---|---|---|
| `id` | string | Stable id, made in the editor. |
| `src` | string | File path, relative to the job folder, like other assets. |
| `kind` | `image` \| `gif` \| `video` | What to draw it with. |
| `from` | seconds or null | When it appears, in source seconds. Null means the start of the clip. |
| `to` | seconds or null | When it leaves. Null means the end of the clip. |
| `x`, `y` | 0–1 | Centre of the overlay, as a fraction of the frame. |
| `width` | 0.03–1 | Width as a fraction of the frame width. Height follows the file's shape. |
| `aspect` | number > 0 | The file's width divided by its height, saved when it is attached. |
| `rotation` | degrees, default 0 | |
| `opacity` | 0–1, default 1 | |
| `duration` | seconds, optional | Length of a video or GIF, so it can loop. |

Null for `from`/`to` matters: a logo meant for the whole clip must stay for the whole clip when the editor later widens or trims the range.

After changing `spec.ts`, run `npm run schema -w composition` and commit the regenerated schema files. The Python validator supports only a small part of JSON Schema (see the top of `spec/schema.py`); check that what zod generates for the new fields stays inside it, and add a case to `pipeline/tests/test_spec.py`.

### Drawing

- New component in the composition (for example `effects/MediaOverlays.tsx`), drawn in `VerticalClip.tsx` above the front effects and below the captions.
- Nothing is drawn during the intro and outro.
- Image: Remotion `<Img>`. Video: `<OffthreadVideo muted>`, looped when the overlay is on screen longer than the file.
- **GIF: use `<Gif>` from `@remotion/gif`**, not `<Img>`. An `<img>` GIF plays on the browser's own clock and renders with the wrong frames. Add `@remotion/gif` at exactly the same version as the other Remotion packages (4.0.535). Confirm the component's current props in the Remotion docs before using it.
- Position with percentages so it is the same in the vertical and landscape frames.

### File paths

Add `overlays[].src` to `resolveForPlayer` (`api.ts`) and `resolveAssets` (`render.mjs`). Miss either and overlays show in the preview but not the render, or the other way round.

### Long videos

`spec/long_video.py` decides which frames go through Remotion. Add each overlay's time on screen to `remotion_ranges` (the same way `_effect_ranges` maps source time to output frames, respecting cuts). Add tests to `pipeline/tests/test_long_video.py`: an overlay on a short span adds only that span; a whole-video overlay makes every frame count.

A whole-video overlay on a 1-hour video therefore renders the slow way (about $5 an hour of video, per the note already in `agent.py`). In the Overlays panel, when the clip is landscape and an overlay stays on for more than a few minutes, show one plain line saying this makes the render slower and cost more. Do not build an ffmpeg shortcut for still images now; note it as a possible later saving.

### Uploading and the shared library

- A shared folder `home_dir()/overlays/`, next to the shared `audio` folder.
- Commands in `studio.py`:
  - `overlay_library()` lists the shared files (name, kind, a path the browser can load).
  - `overlay_library_add(path)` copies one of the user's uploads into the shared folder. Accept only the image and video types already listed in `studio.py` and cap the size (suggest 50 MB).
  - `overlay_library_remove(name)` for admins only.
- Allow the shared folder as a readable root in `get_file` (`app.py`) and as a source root in `studio_attach`, exactly as `home_dir()/audio` is allowed today. Keep the path checks strict: resolve the path and require it to sit inside an allowed root.
- Putting an overlay on a clip still goes through `studio_attach`, which copies the file into the clip's `assets/`, so a render never depends on the library.
- Extend what `studio_attach` returns with the file's pixel width and height (ffprobe) so the editor can save `aspect`, and with `duration` for GIFs and videos.

### Overlays tab

- "Add a photo, GIF or video" (upload, add to the shared library, attach to this clip, place it top-right at 25% width for the whole clip).
- "Team overlays": a grid of the shared library. Clicking one attaches it to this clip.
- "On this clip": the overlays in the spec. Selecting one shows its settings:
  - A 3×3 snap grid (corners, edges, centre) with a small margin.
  - Size and see-through sliders.
  - "Appears at" and "Leaves at" time boxes, a "Whole clip" switch, and "Set to the playhead" buttons.
  - Remove.
- Every change goes through the existing `update(next, reason)` so undo and autosave work. Give each a clear reason ("move overlay", "add overlay").

### Dragging on the preview

- Add a transparent layer exactly over the `.player` box in `Canvas.tsx`. For each overlay visible at the current time, draw an invisible box at the same place and size as the composition draws it.
- Click selects it (and opens the Overlays tab). Drag moves it. Four corner handles resize it, keeping its shape. Snap lightly to the centre lines and edges. Arrow keys nudge the selected overlay.
- The box must not trigger the player's click-to-play. Clicks on empty video still play and pause.
- While dragging, update the spec locally on every move so the preview follows the pointer, but do not create a saved version per pixel: the existing 350ms save delay already merges them; confirm that a drag produces one history entry, not dozens.
- Keep the overlay inside the frame (its centre cannot leave).

### Timeline lane

An Overlays lane with one bar per overlay from `from` to `to`. Clicking a bar selects that overlay and opens the tab. Dragging bars to change timing is not needed in this version.

### Tell the AI

Add `overlays` to the spec descriptions in `studio_chat.py` (`GUIDE`) and `agent.py` (the spec notes near the `effects` description, and the list-editing tools that today accept only `cuts` and `effects`). Then the request "put the logo in the top right corner" works when the file is already in `assets/`.

## Phase 1 is done when

- All checks pass (pytest, typecheck, build, check:names).
- On a short vertical clip, in the running app:
  - The layout matches the sketch, in light and dark themes.
  - An AI request shows its full reply in the chat, and a reply that arrives while another tab is open is still there afterwards.
  - Dragging the timeline scrubs the video; zoom and sideways scroll work.
  - Clicking an effect on the timeline opens it in Effects.
  - A GIF can be uploaded, dragged to a corner, resized, and it appears in the same place in the rendered file, animating correctly.
  - Undo steps back through overlay changes.
- On a landscape long video: the editor still opens and plays, and a short overlay does not turn the whole render into the slow path (check with the tests, and with the frame ranges the render reports).

---

# Phase 2: review

## How it works for people

1. An editor renders a clip and presses **Send for review**.
2. Someone on the communication team opens **Review**, watches it, and presses **Good** or **Needs work**. Needs work requires at least one note; a note can carry the time in the video where the problem is.
3. A video marked Needs work shows up for its editor with the notes. The editor fixes it, ticks the notes off, renders and sends it again as the next version.
4. A video marked Good can be downloaded by the communication team, who post it by hand.
5. **Record** lists every video: who edited it, who reviewed it, its status, how many times it was sent back, and who downloaded it.

## Roles

- Read the role from Supabase `app_metadata.role`, where `admin` is already read (`_supabase_user` in `app.py`). Values: `admin`, `reviewer` (communication team), anything else is an editor.
- Admins can do everything, including reviewing. Editors see only their own videos in Review and Record. Reviewers see everyone's.
- Add `role` and a display `name` (Supabase `user_metadata.name` if set, else the part of the email before `@`) to the user dict and to what `me` returns.
- Desktop mode has no sign-in: treat the single user as an admin named "You" so every screen works there and tests can run without Supabase.
- Check the role on the server in every review command. Hiding a button is not a permission check.
- The owner sets roles in the Supabase dashboard (the project is in an account the available connector cannot reach). Give the owner the exact steps in your final report: Authentication → Users → the user → edit app metadata to `{"role": "reviewer"}`.

## Storage

No database. Use files on the shared volume, like the rest of the app.

- `home_dir()/review/items/<item id>.json`, one file per reviewed clip. The item id combines the owner's user id, the job id and the clip number, with unsafe characters removed.
- `home_dir()/review/files/<item id>/v<N>.mp4`, a copy of the render taken when it is sent. A copy is needed because the editor can re-render while a reviewer is watching. When a new version arrives, delete the older versions' video files and keep their records, so storage does not grow.
- Each item holds: the owner (id, name, email), job id, clip, title, format, length, status (`to_review`, `needs_work`, `good`), the current version number, a list of versions (number, spec version, when sent, the editor's message), a list of notes (id, version, time in the video or null, text, who wrote it, when, fixed or not), who reviewed it, and a log of events (sent, needs work, good, downloaded) each with who and when.
- Write safely: write to a temporary file and rename it over the real one, and re-read the item just before changing it. The web app can run in up to 4 containers (`max_containers=4` in `modal_app.py`), so do not rely on an in-memory lock or cache alone.
- The web app saves the volume every 30 seconds (`_commit_forever`). Another container may not see a new file until the volume reloads there. Check how the web function reloads the volume and make sure a reviewer sees a freshly sent video within about a minute; if not, reload the volume when the review list is read.

Put this in a new module, `server/review.py`, with the store logic separate from the commands so it can be tested without a server.

## Commands

All in `server/review.py`, registered like the commands in `studio.py`.

| Command | Who | What it does |
|---|---|---|
| `review_submit(jobId, clip, message?)` | The clip's owner | Requires a render that matches the current spec version. Copies the render, creates the item or adds a version, sets status `to_review`. |
| `review_list()` | Anyone signed in | Editors get their own items, reviewers and admins get all. Returns summaries for the list and the record. |
| `review_get(id)` | Owner, reviewer, admin | The full item. |
| `review_decide(id, decision, notes)` | Reviewer, admin | `good` or `needs_work`. Needs work must come with at least one note. Records who decided. Rejects a decision on a version that is no longer the current one. |
| `review_note_fixed(id, noteId, fixed)` | The owner | Ticks a note off. |
| `review_for_clip(jobId, clip)` | The owner | The item for the clip open in the editor, or null. |

Plus one route for the video itself, because a `<video>` tag cannot send headers: `GET /api/review/file?id=<item id>&download=0|1`. It serves the current version's file to the owner, reviewers and admins, and records a "downloaded" event (who, when) when `download=1`.

- The route must accept the media token, like `/files` does. Media tokens today carry only the user id (`media_token` and `_media_user` in `app.py`); add the role to the token so this route can check it, and add the route to the list of paths a media token may open.
- Serve byte ranges so the video can seek (FastAPI's `FileResponse` does this already for `/files`).
- Build the file path from the item, never from a path in the request.

Tests: a new `pipeline/tests/test_review.py` covering the full loop (send, needs work with notes, fix, send again, good, download logged), the permission rules for each role, and that an editor cannot read another editor's item.

## Screens

Design reference: the owner's canvas at https://claude.ai/artifact/MNkkP5ajRaWphnyzy2nWqD (boards 2, 3 and 5). It is private to the owner, so the descriptions below are the specification.

**Top bar.** Add three links: Edit (the current home and editor), Review, Record. Show a count on Review: for reviewers, videos waiting; for editors, their videos that need work. Hide all three in a way that keeps the current look when the app is in desktop mode with nothing sent yet, if that is simpler.

**Review (list with the video beside it).**
- Left: three tabs with counts, To review, Needs work, Good. Under them a list of rows: thumbnail, title, "Edited by <name> · <length> · <when>", the version, and for a re-sent video the editor's message.
- Right: the selected video in a normal `<video controls>` player, its title, editor, version and when it was rendered.
- For reviewers on a video waiting for review: a notes area and two large buttons, **Needs work** and **Good**. A note is added with "Add note at <current time>" (it reads the player's time) or as a note about the whole video. Notes can be removed before sending. Needs work is disabled until there is a note.
- **Download video** is always available to reviewers and admins. On a Good video it is the main button.
- Editors see the same screen for their own videos, read-only, with the notes they were given.
- Refresh the list when the screen opens, when the tab becomes visible again, and about once a minute while it is open and the user is active (`isAwake()` in `api.ts`). Do not hold an event stream open for it; that keeps the billed server awake.

**Editor: Review tab.** When the open clip has a review item, the left rail shows a Review tab.
- Needs work: it shows who reviewed which version and when, then each note with its time, a "jump there" link, and an "I fixed this" tick. A badge on the rail button counts the notes not yet ticked. At the bottom, an optional message box and **Render and send for review again**.
- Waiting or Good: it shows the status and nothing to do.
- Note times are positions in the rendered file, which is the output timeline. "Jump there" seeks to that output time. If the editor has since cut or widened the clip the spot can be slightly off; that is acceptable.
- Show each unfixed note as a small amber mark on the timeline ruler.

**Render footer.** Online, when the render is up to date and not yet sent, the main button becomes **Send for review** and Download becomes secondary. After sending, show "Sent for review" or the current status. "Render and send for review again" chains the two: start the render, and when its `result` event arrives, call `review_submit`. If the browser closes before the render finishes, the Send for review button is simply there next time.

**Record.**
- A row of small cards, one per editor: videos this week, how many were good first time, how many were sent back.
- A table: Video, Edited by, Reviewed by, Status, Times sent back, Last change, Downloaded (who and when), and Open.
- Filters: editor, status, and This week / This month / All time.
- Status shows as a coloured pill with the word in it, never colour alone.
- Editors see only their own rows. The table must scroll sideways on a narrow screen.

## Phase 2 is done when

- All checks pass, including the new review tests.
- With three test users (editor, reviewer, admin) on the running app:
  - The editor sends a video; the reviewer sees it within about a minute.
  - Needs work with two timed notes reaches the editor, with the badge and timeline marks.
  - The editor ticks the notes, re-sends, and the reviewer sees version 2 with the message.
  - Good, then Download, saves the file, and the Record shows who downloaded it.
  - A second editor cannot see or open the first editor's video, by the screen or by calling the command or file route directly.
- Desktop mode still works with no sign-in.

---

# Phase 3: full system review and fixes

After phases 1 and 2 are built, review the whole system, not only the new code. The owner asked for this explicitly: find and fix problems they have not seen. Use the app as each kind of user would, and read the code with fresh eyes.

## What to go through

1. **Every flow, end to end, in the running app:** sign in, make a clip from a link, find moments, a long video, each editor tab, the AI chat, overlays, render, send for review, review, send back, fix, approve, download, record. Do it in both themes and at a narrow window width.
2. **Preview against render.** For a clip using captions, an effect, an overlay of each kind (image, GIF, video), music, an intro and a cut with a transition, compare the preview with the rendered file frame by frame at several points. They must match in position, size and timing.
3. **Permissions.** For every command and route, ask: can a signed-in user reach another user's files or review items by changing an id or a path? Test it directly against the API, not through the screen.
4. **Failure handling.** A failed upload, a wrong file type, a huge file, a render that fails, the server waking from sleep, a lost connection mid-drag, two people deciding on the same video at once, a video re-sent while a reviewer has the old one open.
5. **Cost.** Nothing new may keep the web server awake when nobody is using it (see the comments on idle and hidden tabs in `api.ts`). Confirm the review screens stop polling when hidden or idle, and that a long video with a short overlay still takes the cheap render path.
6. **Speed.** Scrubbing, dragging an overlay and typing in the chat must stay smooth on a slow laptop (the owner's PC has 4 cores and no GPU) with a long clip open.
7. **Wording.** Read every new label and message. Plain words, no provider names, no leftover placeholder text.
8. **Old paths.** Anything the new layout replaced must be gone: the History drawer, unused CSS, dead props. Nothing that used to work may be missing (Telegram button in desktop mode, the doubtful-captions nudge, keyboard space to play).
9. **The three path-resolving places** named near the top: confirm every file-holding spec field is in all of them.
10. **Docs.** Update `docs/SYSTEM.md` and `README.md` for the new layout, overlays, roles and review, and write a short how-to for the communication team in plain words.

## How to handle what you find

- Fix real bugs directly, each with a test where one is practical. Keep fixes small; do not restructure working code.
- Do not make product decisions for the owner. If something is a choice rather than a bug, list it with your recommendation.
- Anything risky or outside this plan (a schema change that breaks old specs, deleting user files, a change to sign-in) gets listed, not done.
- Old clips made before this work must still open and render: an old `spec.json` has no `overlays` field, and old users have no role.

## Final report to the owner

Write it in plain words. Include:
- What was built, phase by phase, and what was verified by running it versus only by tests.
- Every fix made in phase 3, one line each, and anything found but left alone, with the reason.
- The assumptions from the table near the top, so the owner can change them.
- Anything that failed or could not be tested, said plainly.
- The steps the owner must do themselves: setting roles in Supabase, and approving the deploy.

---

# Deploying (only when the owner says so)

- **Modal** (server and renderer): from the repo root, `modal deploy pipeline/modal_app.py`. On Windows set `PYTHONUTF8=1` first or the command crashes while printing. Any change to `studio/composition` needs this deploy, because the renderer image carries its own copy of the composition.
- After a deploy, warm containers keep serving the old code. List them and stop them with `modal container stop <id> --yes`. The owner has approved this step before; confirm no render is running first (`GET /api/health`).
- **Vercel** (the editor): hosted as `tetclipper.vercel.app` under the `achwanyaa` account. Find out how it deploys (git push or manual) before assuming.
- New shared folders (`overlays`, `review`) are created on first use; no setup step is needed.

# Order of work, in short

1. Branch off `main`.
2. Phase 1 in the order 1.1 → 1.5, running the checks after each step.
3. Show the owner phase 1 running before starting phase 2, unless they said to continue straight through.
4. Phase 2: server module and tests first, then the screens.
5. Phase 3: review, fix, update the docs.
6. Final report. Deploy only on the owner's word.
