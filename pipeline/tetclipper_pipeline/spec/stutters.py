"""Edit out stutters and false starts.

Conservative on purpose: it only removes what's clearly a stumble. Sermons
repeat on purpose ("Choose life. Choose life.", "holy, holy, holy"), so a
repeat only counts when the first take runs on into the second (no
punctuation between them), and only a true dash marks a cut-off word ("…"
is a pause, not a fragment).

  repeat      the same word or 2–4 word phrase said twice in a row
              ("I I I went", "we are we are going") → keep the last one
  fragment    a cut-off word ("wh-", "be— because") or a short prefix of the
              next word ("th the") → drop the fragment
  restart     the speaker stops (dash/ellipsis or a pause ≥ RESTART_PAUSE) and
              starts the sentence again with the same first two words
              ("so the church— so the church is") → drop the abandoned start
  filler      um / uh / erm … (only with fillers=True)

Removed words become `hidden` (captions) and their audio is cut (`cuts`),
each cut ending just before the word that is kept.
"""

from __future__ import annotations

from .glossary import norm
from .silence import FILLERS

MAX_REPEAT_GAP = 0.8  # seconds between the two takes of a repeat
RESTART_PAUSE = 0.3
MAX_ABANDONED = 5  # words in an abandoned start
PAD = 0.02
_CUT_OFF = ("-", "—", "–")  # a word broken off mid-way
_DASH = (*_CUT_OFF, "...", "…")  # a sentence abandoned (restarts)


def _visible(words: list[dict], start: float, end: float, cuts: list[dict]) -> list[int]:
    """Words still heard: not hidden, in range, not already inside a cut."""
    def cut(w: dict) -> bool:
        mid = (w["start"] + w["end"]) / 2
        return any(c["start"] <= mid < c["end"] for c in cuts)

    return [i for i, w in enumerate(words) if not w.get("hidden") and w["end"] > start and w["start"] < end and not cut(w)]


def find(spec: dict, fillers: bool = False) -> dict:
    """{removals: [{from, to, keep, kind, text}], cuts: [...], saved: seconds}.
    from..to are word indices removed; keep is the index the cut runs up to."""
    words = spec.get("words", [])
    src = spec["source"]
    vis = _visible(words, src["start"], src["end"], spec.get("cuts", []))
    t = [norm(words[i]["text"]) for i in vis]
    removals: list[dict] = []
    taken: set[int] = set()  # positions in vis already removed

    def remove(a: int, b: int, keep: int, kind: str) -> None:
        if any(p in taken for p in range(a, b + 1)) or keep >= len(vis):
            return
        taken.update(range(a, b + 1))
        removals.append({
            "from": vis[a], "to": vis[b], "keep": vis[keep], "kind": kind,
            "text": " ".join(words[vis[p]]["text"] for p in range(a, b + 1)),
        })

    def gap(p: int, q: int) -> float:  # silence between vis[p] and vis[q]
        return words[vis[q]]["start"] - words[vis[p]]["end"]

    def punct(p: int) -> bool:
        return words[vis[p]]["text"].rstrip()[-1:] in ".,!?;:"

    p = 0
    while p < len(vis):
        # fragments: "wh-", "be— because", "th the"
        raw = words[vis[p]]["text"].rstrip()
        if p + 1 < len(vis) and t[p] and (
            raw.endswith(_CUT_OFF) and len(t[p]) <= 6
            or (2 <= len(t[p]) <= 3 and t[p + 1].startswith(t[p]) and t[p + 1] != t[p] and gap(p, p + 1) < 0.5)
        ):
            remove(p, p, p + 1, "fragment")
            p += 1
            continue
        # phrase / word repeats, longest first: "we are we are", "I I I"
        hit = False
        for n in (4, 3, 2, 1):
            if p + 2 * n > len(vis) or not all(t[p + k] for k in range(n)):
                continue
            if t[p : p + n] != t[p + n : p + 2 * n] or gap(p + n - 1, p + n) > MAX_REPEAT_GAP:
                continue
            if punct(p + n - 1):
                continue  # "Choose life. Choose life." / "holy, holy": deliberate
            end = p + n
            while end + n <= len(vis) and t[end : end + n] == t[p : p + n] and gap(end - 1, end) <= MAX_REPEAT_GAP:
                end += n  # "I I I" → drop all but the last take
            broke_off = words[vis[end - n - 1]]["text"].rstrip().endswith(_DASH)
            remove(p, end - n - 1, end - n, "restart" if broke_off else "repeat")
            p = end - n
            hit = True
            break
        if hit:
            continue
        # restarts: "so the church— so the church is"
        for k in range(1, MAX_ABANDONED + 1):
            q = p + k + 1  # where the restart begins
            if q + 1 >= len(vis) or t[p : p + 2] != t[q : q + 2] or not t[p]:
                continue
            last = q - 1
            stopped = words[vis[last]]["text"].rstrip().endswith(_DASH) or gap(last, q) >= RESTART_PAUSE
            if stopped and not punct(last):
                remove(p, last, q, "restart")
                p = q
                hit = True
                break
        if hit:
            continue
        if fillers and t[p] in FILLERS:
            if p + 1 < len(vis):
                remove(p, p, p + 1, "filler")
        p += 1

    cuts = []
    for r in removals:
        a = max(src["start"], words[r["from"]]["start"] - PAD)
        b = words[r["keep"]]["start"] - PAD
        if b - a > 0.05:
            cuts.append({"start": round(a, 3), "end": round(b, 3)})
    return {"removals": removals, "cuts": cuts, "saved": round(sum(c["end"] - c["start"] for c in cuts), 2)}


def apply(spec: dict, found: dict) -> dict:
    words = [dict(w) for w in spec.get("words", [])]
    for r in found["removals"]:
        for i in range(r["from"], r["to"] + 1):
            words[i]["hidden"] = True
    cuts = sorted([*spec.get("cuts", []), *found["cuts"]], key=lambda c: c["start"])
    return {**spec, "cuts": cuts, "words": words}
