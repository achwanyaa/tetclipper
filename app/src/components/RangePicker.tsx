import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import { listen } from '../backend'
import type { JobTranscript, PipelineEvent } from '../types'

const PRESETS = ['classic', 'beast', 'hormozi', 'minimal', 'karaoke-pop']
const CAMERAS: [string, string][] = [
  ['cut', 'cut'],
  ['pan', 'pan'],
  ['locked', 'locked']
]
const MIN_SEC = 3
const MAX_SEC = 600

interface Props {
  jobId: string
  onBack: () => void
  /** The cut started; App takes over and opens the review when it lands. */
  onCut: () => void
}

/** "12:30.5" / "1:02:03" ↔ seconds. */
export function fmt(t: number): string {
  const h = Math.floor(t / 3600)
  const m = Math.floor((t % 3600) / 60)
  const s = t % 60
  const ss = s.toFixed(1).padStart(4, '0')
  return h ? `${h}:${String(m).padStart(2, '0')}:${ss}` : `${m}:${ss}`
}

export function parseTime(text: string): number | null {
  const parts = text.trim().split(':').map(Number)
  if (parts.length === 0 || parts.length > 3 || parts.some((p) => Number.isNaN(p) || p < 0)) return null
  return parts.reduce((acc, p) => acc * 60 + p, 0)
}

type Word = [string, number, number]

/** The whole-video transcript. Memoized: it re-renders only when the
 *  selection changes, never on playback ticks (thousands of words). The
 *  playing word is highlighted straight on the DOM by the parent. */
const Transcript = memo(function Transcript({
  segments, start, end, onWord, onSeek
}: {
  segments: JobTranscript['segments']
  start: number | null
  end: number | null
  onWord: (w: Word) => void
  onSeek: (t: number) => void
}) {
  let i = 0
  return (
    <div className="range-transcript">
      {segments.map((seg, s) => (
        <p key={s} className="range-seg">
          <span className="range-stamp mono" onClick={() => onSeek(seg.words[0]?.[1] ?? 0)}>
            {fmt(seg.words[0]?.[1] ?? 0)}
          </span>
          {seg.words.map((w) => {
            const id = i++
            const inSel = start != null && w[1] >= start && w[1] < (end ?? start + 0.01)
            return (
              <span
                key={id}
                id={`w-${id}`}
                className={`range-word ${inSel ? 'in' : ''}`}
                onClick={() => onWord(w)}
              >
                {w[0]}{' '}
              </span>
            )
          })}
        </p>
      ))}
    </div>
  )
})

export default function RangePicker({ jobId, onBack, onCut }: Props) {
  const [data, setData] = useState<JobTranscript | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [start, setStart] = useState<number | null>(null)
  const [end, setEnd] = useState<number | null>(null)
  const [startText, setStartText] = useState('')
  const [endText, setEndText] = useState('')
  const [now, setNow] = useState(0)
  const [captions, setCaptions] = useState('hormozi')
  const [camera, setCamera] = useState('cut')
  const [busy, setBusy] = useState<string | null>(null)
  const [find, setFind] = useState('')
  const videoRef = useRef<HTMLVideoElement>(null)
  const stopAt = useRef<number | null>(null)
  const findFrom = useRef(0)

  useEffect(() => {
    api.jobTranscript(jobId).then(setData).catch((e) => setError(String(e)))
  }, [jobId])

  // Progress while the cut renders (App handles the final result).
  useEffect(() => {
    let un: (() => void) | undefined
    listen<PipelineEvent>('pipeline-event', ({ payload }) => {
      if (payload.event === 'progress' && payload.message) setBusy(payload.message)
      if (payload.event === 'result' && !payload.ok) {
        setBusy(null)
        setError(String(payload.error ?? 'Cut failed'))
      }
    }).then((stop) => (un = stop))
    return () => un?.()
  }, [])

  useEffect(() => setStartText(start == null ? '' : fmt(start)), [start])
  useEffect(() => setEndText(end == null ? '' : fmt(end)), [end])

  const words: Word[] = useMemo(() => data?.segments.flatMap((s) => s.words) ?? [], [data])
  const duration = data?.duration ?? 0
  const length = start != null && end != null ? end - start : null
  const valid = length != null && length >= MIN_SEC && length <= MAX_SEC

  const seek = useCallback((t: number) => {
    const v = videoRef.current
    if (v) v.currentTime = t
  }, [])

  // Click the first word, then the last; a third click starts over.
  const clickWord = useCallback((w: Word) => {
    seek(w[1])
    if (start == null || end != null) {
      setStart(w[1])
      setEnd(null)
    } else if (w[2] > start) {
      setEnd(w[2])
    } else {
      setStart(w[1])
    }
  }, [seek, start, end])

  // Highlight the playing word without re-rendering the transcript.
  const nowWord = useRef<HTMLElement | null>(null)
  useEffect(() => {
    let lo = 0
    let hi = words.length - 1
    let idx = -1
    while (lo <= hi) {
      const mid = (lo + hi) >> 1
      if (words[mid][1] <= now) {
        idx = mid
        lo = mid + 1
      } else hi = mid - 1
    }
    const el = idx >= 0 && now < words[idx][2] ? document.getElementById(`w-${idx}`) : null
    if (el === nowWord.current) return
    nowWord.current?.classList.remove('now')
    el?.classList.add('now')
    nowWord.current = el
  }, [now, words])

  const playRange = () => {
    const v = videoRef.current
    if (!v || start == null) return
    v.currentTime = start
    stopAt.current = end
    v.play()
  }

  const commitText = (text: string, set: (t: number | null) => void, reset: () => void) => {
    const t = parseTime(text)
    if (t == null || t > duration) reset()
    else set(t)
  }

  const runFind = () => {
    const q = find.trim().toLowerCase()
    if (!q) return
    const n = words.length
    for (let k = 0; k < n; k++) {
      const i = (findFrom.current + k) % n
      if (words[i][0].toLowerCase().includes(q)) {
        findFrom.current = i + 1
        document.getElementById(`w-${i}`)?.scrollIntoView({ block: 'center', behavior: 'smooth' })
        seek(words[i][1])
        return
      }
    }
  }

  const cut = async () => {
    if (!valid || start == null || end == null) return
    setError(null)
    setBusy('Starting…')
    try {
      onCut()
      await api.addClipRange(jobId, start, end, captions, camera)
    } catch (e) {
      setBusy(null)
      setError(String(e))
    }
  }

  const pct = (t: number) => `${(t / Math.max(1, duration)) * 100}%`

  return (
    <div className="range">
      <div className="grain" />
      <header className="review-head">
        <button className="btn-ghost" onClick={onBack} disabled={!!busy}>
          ← back
        </button>
        <div className="review-title-block">
          <h1 className="review-title">{data?.title ?? jobId}</h1>
          <p className="review-sub mono">pick a range · click the first word, then the last</p>
        </div>
      </header>

      {error && (
        <section className="error-block">
          <span className="led led-err" />
          {error}
        </section>
      )}

      {data && (
        <div className="range-body">
          <section className="range-left">
            <video
              ref={videoRef}
              className="range-video"
              src={api.fileUrl(data.media_path)}
              controls
              preload="metadata"
              onTimeUpdate={(e) => {
                const t = e.currentTarget.currentTime
                setNow(t)
                if (stopAt.current != null && t >= stopAt.current) {
                  e.currentTarget.pause()
                  stopAt.current = null
                }
              }}
            />

            <div
              className="range-track"
              onClick={(e) => {
                const r = e.currentTarget.getBoundingClientRect()
                seek(((e.clientX - r.left) / r.width) * duration)
              }}
            >
              {start != null && (
                <div
                  className="range-sel"
                  style={{ left: pct(start), width: end != null ? pct(end - start) : '2px' }}
                />
              )}
              <div className="range-head" style={{ left: pct(now) }} />
            </div>
            <div className="range-times mono">
              <span>{fmt(now)}</span>
              <span>{fmt(duration)}</span>
            </div>

            <div className="range-io">
              <label className="range-field">
                <span className="opt-label">in</span>
                <input
                  className="mono"
                  value={startText}
                  placeholder="12:30"
                  onChange={(e) => setStartText(e.target.value)}
                  onBlur={() => commitText(startText, setStart, () => setStartText(start == null ? '' : fmt(start)))}
                  onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
                />
                <button className="btn-secondary" onClick={() => setStart(now)}>
                  SET IN
                </button>
              </label>
              <label className="range-field">
                <span className="opt-label">out</span>
                <input
                  className="mono"
                  value={endText}
                  placeholder="13:15"
                  onChange={(e) => setEndText(e.target.value)}
                  onBlur={() => commitText(endText, setEnd, () => setEndText(end == null ? '' : fmt(end)))}
                  onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
                />
                <button className="btn-secondary" onClick={() => setEnd(now)}>
                  SET OUT
                </button>
              </label>
              <span className={`range-len mono ${length != null && !valid ? 'bad' : ''}`}>
                {length == null
                  ? '—'
                  : length < MIN_SEC || length > MAX_SEC
                    ? `${length.toFixed(1)} s (needs ${MIN_SEC}–${MAX_SEC} s)`
                    : length > 180
                      ? `${length.toFixed(1)} s · too long for Shorts/Reels, fine for TikTok`
                      : `${length.toFixed(1)} s`}
              </span>
              <button className="btn-ghost" onClick={playRange} disabled={start == null}>
                ▶ play range
              </button>
            </div>

            <div className="run-options">
              <div className="opt-group">
                <span className="opt-label">captions</span>
                {PRESETS.map((p) => (
                  <button key={p} className={`opt ${captions === p ? 'opt-on' : ''}`} onClick={() => setCaptions(p)}>
                    {p}
                  </button>
                ))}
              </div>
              <div className="opt-group">
                <span className="opt-label">camera</span>
                {CAMERAS.map(([mode, label]) => (
                  <button key={mode} className={`opt ${camera === mode ? 'opt-on' : ''}`} onClick={() => setCamera(mode)}>
                    {label}
                  </button>
                ))}
              </div>
            </div>

            <button className="btn-primary range-cut" onClick={cut} disabled={!valid || !!busy}>
              {busy ? 'CUTTING' : 'CUT THIS RANGE'}
            </button>
            {busy && <p className="input-notice mono">{busy}</p>}
          </section>

          <section className="range-right">
            <input
              className="range-find mono"
              placeholder="find a word… (enter for next)"
              value={find}
              onChange={(e) => {
                setFind(e.target.value)
                findFrom.current = 0
              }}
              onKeyDown={(e) => e.key === 'Enter' && runFind()}
            />
            <Transcript segments={data.segments} start={start} end={end} onWord={clickWord} onSeek={seek} />
          </section>
        </div>
      )}
    </div>
  )
}
