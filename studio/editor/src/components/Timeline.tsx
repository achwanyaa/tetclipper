import { useMemo, type MouseEvent } from 'react'
import { FPS, frameAtSource, type ClipSpec, type Timeline as TL } from '@tetclipper/composition'

interface Props {
  timeline: TL
  spec: ClipSpec
  frame: number
  playhead: number | null // source seconds
  seekFrame: (frame: number) => void
  seekSource: (t: number) => void
}

const NICE_STEPS = [5, 10, 15, 20, 30, 60, 120, 300, 600]
const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`
const FX_LABELS: Record<string, string> = { hook: 'Title card', 'punch-in': 'Punch-in', 'wall-text': 'Couch wall', cover: 'Cover story' }
const fxLabel = (type: string) => FX_LABELS[type] ?? type.replace(/-/g, ' ').replace(/^./, (c) => c.toUpperCase())
const WINDOW = 40

/** Lane timeline under the preview, in output time: the caption words around
 *  the playhead, every effect, and where the cuts are. Click to seek. */
export function Timeline({ timeline, spec, frame, playhead, seekFrame, seekSource }: Props) {
  const total = Math.max(1, timeline.totalFrames)
  const seconds = total / FPS
  const pct = (f: number) => `${Math.min(100, Math.max(0, (f / total) * 100))}%`

  const ticks = useMemo(() => {
    const step = NICE_STEPS.find((s) => seconds / s <= 6) ?? 1200
    const out: number[] = []
    for (let t = 0; t <= seconds; t += step) out.push(t)
    return out
  }, [seconds])

  const doubtful = useMemo(() => {
    const set = new Set<number>()
    for (const d of spec.doubts ?? []) for (let i = d.from; i <= d.to; i++) set.add(i)
    return set
  }, [spec.doubts])

  // Words still in the clip (not cut out), with their index in spec.words.
  const kept = useMemo(
    () => spec.words.map((w, i) => ({ w, i })).filter(({ w }) => frameAtSource(timeline, (w.start + w.end) / 2, FPS) !== null),
    [spec.words, timeline]
  )
  const at = playhead === null ? 0 : Math.max(0, kept.findIndex(({ w }) => w.end + 0.05 > playhead))
  const visible = kept.slice(Math.max(0, at - 2), Math.max(0, at - 2) + WINDOW)

  const effects = useMemo(
    () =>
      (spec.effects ?? []).flatMap((e) => {
        const f = frameAtSource(timeline, e.at, FPS)
        if (f === null) return []
        const width = (e.duration * FPS) / total
        return [{ type: e.type, at: e.at, left: f, width, long: width > 0.06 }]
      }),
    [spec.effects, timeline, total]
  )

  const cuts = useMemo(
    () =>
      (spec.cuts ?? []).flatMap((c) => {
        const f = frameAtSource(timeline, c.start - 0.02, FPS) ?? frameAtSource(timeline, c.end + 0.02, FPS)
        if (f === null) return []
        return [{ left: f, width: Math.min(0.02, (c.end - c.start) / seconds), len: c.end - c.start, start: c.start }]
      }),
    [spec.cuts, timeline, seconds]
  )

  const onTrackClick = (e: MouseEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect()
    seekFrame(Math.round(((e.clientX - r.left) / r.width) * total))
  }

  return (
    <div className="card timeline">
      <div className="labels">
        <span className="lane-row ruler-row" />
        <span className="lane-row lane-label">Captions</span>
        <span className="lane-row fx-row lane-label">Effects</span>
        <span className="lane-row cut-row lane-label">Cuts</span>
      </div>
      <div className="tracks" onClick={onTrackClick}>
        <div className="ruler">
          {ticks.map((t) => (
            <span key={t} style={{ left: pct(t * FPS) }}>
              {clock(t)}
            </span>
          ))}
        </div>
        <div className="words" onClick={(e) => e.stopPropagation()}>
          {visible.map(({ w, i }) => {
            // Seeking lands on a frame boundary, a hair before the word starts.
            const active = playhead !== null && i === kept[at]?.i && playhead >= w.start - 0.1
            return (
              <button
                key={i}
                className={[active && 'active', doubtful.has(i) && 'doubt'].filter(Boolean).join(' ')}
                title={doubtful.has(i) ? 'The speech model wasn’t sure about this word' : undefined}
                onClick={() => seekSource(w.start)}
              >
                {w.text}
              </button>
            )
          })}
        </div>
        <div className="fx">
          {effects.map((e, k) =>
            e.long ? (
              <span key={k} className="long" style={{ left: pct(e.left), width: `${e.width * 100}%` }} title={`${fxLabel(e.type)} at ${clock(e.left / FPS)}`}>
                {fxLabel(e.type)}
              </span>
            ) : (
              <span key={k} style={{ left: pct(e.left), width: `max(6px, ${e.width * 100}%)` }} title={`${fxLabel(e.type)} at ${clock(e.left / FPS)}`} />
            )
          )}
        </div>
        <div className="cuts">
          {cuts.map((c, k) => (
            <span key={k} style={{ left: pct(c.left), width: `${c.width * 100}%` }} title={`Cut ${c.len.toFixed(1)} s`} />
          ))}
        </div>
        <div className="playhead" style={{ left: pct(frame) }} />
      </div>
    </div>
  )
}
