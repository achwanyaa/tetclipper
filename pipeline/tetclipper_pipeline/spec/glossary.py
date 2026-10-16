"""The learning word list (~/.tetclipper/glossary.json).

Kenyan sermons mix English, Swahili and Sheng mid-sentence, and the speech
model hears Swahili as English-sounding words ("ebu tusome" → "able to show
me"). Every caption fix — the user's or Claude's — is remembered here as
heard → said, then:

  * applied automatically to every new transcript (spec/build.py), and
  * fed to the speech model as hotwords (asr/stage.py), with `phrases`.

Fixes never change the number of words: `retext` puts the new text over the
same words (hiding extras, spreading the span's timing), so word indices —
and the before/after diff that `learn` reads — stay stable.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .. import config

SEED_PHRASES = [  # suggestions shown in the word list; not hinted until the user adds them
    "Bwana asifiwe", "Amina", "wapendwa", "ebu tusome", "Yesu", "Yesu Kristo", "Mungu", "Roho Mtakatifu",
    "Bwana", "neno la Mungu", "sasa", "kwa hivyo", "lakini", "ama", "ndio", "hapana", "sisi", "nyinyi",
    "mimi", "wewe", "ati", "hii", "hiyo", "kweli", "maombi", "baraka", "utukufu", "imani", "anasema",
]
INITIAL_PROMPT = (
    "Bwana asifiwe, wapendwa. Ebu tusome Revelation chapter 5. Yesu ni Bwana, amen. "
    "Mungu anasema, sasa kwa hivyo, let us pray."
)
MAX_HOTWORDS = 40
MAX_RUN = 8  # longer changed runs are rewrites, not misheard words
# Only phrase-level mishearings are reusable rules ("able to show me" → "ebu
# tusome"). A one-word swap ("a" → "kwa") or a deletion is right in that spot
# only; learned globally it would rewrite every "a" in every future clip.
MIN_HEARD_WORDS = 2
MAX_HEARD_WORDS = 6

_PUNCT = re.compile(r"[^\w']+", re.UNICODE)


def path() -> Path:
    return config.home_dir() / "glossary.json"


def load() -> dict:
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    # Seed phrases only shape the initial prompt; as hotwords they would get
    # forced into unclear audio. The list starts with what the user confirms.
    return {"phrases": list(data.get("phrases", [])), "fixes": list(data.get("fixes", []))}


def save(data: dict) -> dict:
    clean = {
        "phrases": sorted({p.strip() for p in data.get("phrases", []) if p and p.strip()}, key=str.lower),
        "fixes": [f for f in data.get("fixes", []) if reusable(f.get("heard", ""), f.get("said") or "")],
    }
    path().parent.mkdir(parents=True, exist_ok=True)
    path().write_text(json.dumps(clean, indent=1, ensure_ascii=False), encoding="utf-8")
    return clean


def norm(text: str) -> str:
    return _PUNCT.sub(" ", text.lower()).strip()


def hotwords(data: dict | None = None) -> str:
    """Comma-separated hints for the speech model: what was really said, most
    frequent fixes first, then the phrase list."""
    data = data or load()
    said = [f["said"] for f in sorted(data["fixes"], key=lambda f: -f.get("count", 1)) if f["said"].strip()]
    seen: set[str] = set()
    out: list[str] = []
    for item in [*said, *data["phrases"]]:
        key = norm(item)
        if key and key not in seen:
            seen.add(key)
            out.append(item.strip())
        if len(out) >= MAX_HOTWORDS:
            break
    return ", ".join(out)


# ---------- putting new text over a span of words ----------

def retext(span: list[dict], text: str) -> list[dict]:
    """New words for `span` carrying `text`, same count: tokens go on the first
    words (overflow joins the last), the rest are hidden, and the visible words
    share the span's timing evenly. Speaker and emphasis carry over."""
    tokens = text.split()
    span = [dict(w) for w in span]
    if not span:
        return span
    if not tokens:
        for w in span:
            w["hidden"] = True
        return span
    k = len(span)
    if len(tokens) > k:
        tokens = [*tokens[: k - 1], " ".join(tokens[k - 1 :])]
    a, b = span[0]["start"], span[-1]["end"]
    step = (b - a) / len(tokens)
    for i, w in enumerate(span):
        if i < len(tokens):
            w["text"] = tokens[i]
            w.pop("hidden", None)
            w["start"] = round(a + i * step, 3)
            w["end"] = round(a + (i + 1) * step, 3)
        else:
            w["hidden"] = True
    return span


# ---------- learning from an edit ----------

def _changed_runs(old: list[dict], new: list[dict]) -> list[tuple[int, int]]:
    def differs(i: int) -> bool:
        o, n = old[i], new[i]
        hid = bool(n.get("hidden")) and not o.get("hidden")
        return hid or (not n.get("hidden") and norm(o["text"]) != norm(n["text"]))

    runs, i = [], 0
    while i < len(old):
        if differs(i):
            j = i
            while j + 1 < len(old) and differs(j + 1):
                j += 1
            runs.append((i, j))
            i = j + 1
        else:
            i += 1
    return runs


def diff_fixes(old: list[dict], new: list[dict]) -> list[tuple[str, str]]:
    """(heard, said) pairs for every run of words an edit changed."""
    if len(old) != len(new):
        return []
    pairs = []
    for i, j in _changed_runs(old, new):
        if j - i + 1 > MAX_RUN:
            continue
        heard = " ".join(w["text"] for w in old[i : j + 1] if not w.get("hidden")).strip()
        said = " ".join(w["text"] for w in new[i : j + 1] if not w.get("hidden")).strip()
        if reusable(heard, said):
            pairs.append((heard, said))
    return pairs


def reusable(heard: str, said: str) -> bool:
    """Worth applying to every future clip? See MIN_HEARD_WORDS."""
    n = len(norm(heard).split())
    return bool(said.strip()) and norm(heard) != norm(said) and MIN_HEARD_WORDS <= n <= MAX_HEARD_WORDS


def learn(old_words: list[dict], new_words: list[dict]) -> int:
    pairs = diff_fixes(old_words, new_words)
    if not pairs:
        return 0
    data = load()
    for heard, said in pairs:
        hit = next((f for f in data["fixes"] if norm(f["heard"]) == norm(heard)), None)
        if hit:
            hit["said"] = said
            hit["count"] = hit.get("count", 1) + 1
        else:
            data["fixes"].append({"heard": heard, "said": said, "count": 1})
    save(data)
    return len(pairs)


# ---------- applying what was learned ----------

def apply_fixes(words: list[dict], data: dict | None = None) -> tuple[list[dict], int]:
    """Replace every known misheard sequence in `words` (visible words only)."""
    data = data or load()
    fixes = [(norm(f["heard"]).split(), f["said"]) for f in data["fixes"] if reusable(f["heard"], f["said"])]
    fixes = sorted([f for f in fixes if f[0]], key=lambda f: -len(f[0]))  # longest first
    words = [dict(w) for w in words]
    applied = 0
    i = 0
    while i < len(words):
        if words[i].get("hidden"):
            i += 1
            continue
        for heard, said in fixes:
            idx, k = [], i
            while k < len(words) and len(idx) < len(heard):
                if not words[k].get("hidden"):
                    if norm(words[k]["text"]) != heard[len(idx)]:
                        break
                    idx.append(k)
                k += 1
            if len(idx) == len(heard):
                a, b = idx[0], idx[-1]
                words[a : b + 1] = retext(words[a : b + 1], said)
                applied += 1
                i = b
                break
        i += 1
    return words, applied
