---
name: score-clips
description: Act as tetclipper's scoring brain for a job paused on "Waiting for Claude Code" (llm mode "claude"). Use when the user runs /score-clips <job_id>, or asks Claude to judge/score a tetclipper job's moments or music briefs.
argument-hint: "[job_id]"
---

# Score a paused tetclipper job

A job run with the **claude code** brain pauses at the JUDGE stage and writes
`~/.tetclipper/jobs/<job_id>/brain_request.json`. You answer it; the pipeline
does everything else (cross-checking your scores against detected laughter,
vocal energy and replay heatmaps, ranking, camera, render).

Commands run from the repo root. `PC` below means
`uv --directory pipeline run tetclipper`.

## Steps

1. **Find the job.** Use the job id from the arguments. If none was given, run
   `PC jobs` and pick the most recent job whose `brain_request.json` exists
   (look in `~/.tetclipper/jobs/*/brain_request.json`). Ask the user if more
   than one is waiting.
2. **Read the request:** `PC brain show <job_id>`. Each group prints its JSON
   schema and shared instructions once, then one block per item
   (`--- id <id>` followed by that item's transcript or details).
3. **Answer every item**, following the shared instructions and the schema
   exactly (field names, integer types, enum values). Write ONE JSON file to
   your scratchpad: `{"<id>": {...answer...}, ...}`.
4. **Store the answers:** `PC brain answer <job_id> <answers_file>`. It prints
   `{"written", "missing", "errors"}`. Fix and re-run until missing and errors
   are both empty.
5. **Hand back.** Tell the user to press **Resume job** in the app (it streams
   progress there). Only if the app isn't open, run
   `PC resume <job_id> --llm claude` yourself in the background.
   The first round is moment scoring. Once it is resumed, a second, smaller
   round (music briefs for the 12 finalists) may pause the job again; repeat
   these steps for it.

## Hosted jobs (Modal)

When the job runs on the hosted deployment instead of this machine, the job
dir is on Modal, so the local `PC brain …` commands can't see it. Use the
server's HTTP commands instead, with the deployment URL and the access token
from `~/.tetclipper/web-token.txt` (`-H "Authorization: Bearer <token>"`):

- show: `POST <url>/api/cmd/brain_show` with body `{"jobId": "<job_id>"}` →
  `{"waiting": true, "text": "…same text as brain show…"}`
- answer: `POST <url>/api/cmd/brain_answer` with body
  `{"jobId": "<job_id>", "answers": { "<id>": {…}, … }}` → `{written, missing, errors}`

Then the user presses **Resume job** in the hosted app. The deployment URL is
in `.claude/deploy-url.txt` when one exists; otherwise ask.

## Judging moments (the "moment-scoring" round)

You are the judge whose numbers the app shows in its audit panel. Be an honest,
calibrated short-form editor, not a cheerleader:

- **Most moments are mediocre.** Use the whole 0–10 range; 8+ on any dimension
  should be rare (a few per video at most). Compare items against each other
  before finalizing, since ranking is what matters.
- **hook** rates only the first ~3 seconds of that transcript on their own.
- **funniness** is real humor for a general audience. The pipeline discounts
  it when no laughter was detected, so don't inflate it.
- **shock** is surprising or taboo content, independent of the hook.
- **curiosity_gap**: does it open a question the viewer must stay to resolve?
- **value**: practical or emotional payoff and resonance.
- **self_contained**: false if it leans on context from outside the window.
- **punchline_index**: 0-based index of the word (counting every word in the
  transcript, speaker labels excluded) where the biggest laugh lands, else -1.
- **bait_phrases**: only literal engagement bait ("like and subscribe", ...).
- **summary**: one plain sentence saying what happens. It is shown to the user
  on the clip card.

Keep reasoning internal and short. With ~35 items, don't write essays. Just
produce the JSON.

## Music briefs (the "music-brief" round)

Follow the shared instructions in the request: a real, searchable genre;
`bpm_range` fitting the energy; trust the signal-derived mood prior; exactly 2
alternatives with different genres.
