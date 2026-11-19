import { useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'
import { FPS, frameAtSource, outputSpan, sourceTimeAt, type ClipSpec, type Timeline as TL } from '@tetclipper/composition'

export interface PlayerControls {
  play: () => void
  pause: () => void
  isPlaying: () => boolean
}

export interface TimelineMark {
  frame: number
  label: string
}

interface Props {
  timeline: TL
  spec: ClipSpec
  frame: number
  playing: boolean
  playhead: number | null // source seconds
  seekFrame: (frame: number) => void
  seekSource: (t: number) => void
  player: PlayerControls
  selectedEffect: number | null
  onEffect: (index: number) => void
  selectedOverlay: string | null
  onOverlay: (id: string) => void
  onOverlayTime: (id: string, from: number | null, to: number | null) => void // source seconds, null = the clip's start/end
  marks?: TimelineMark[] // review notes, shown on the ruler
}

const NICE_STEPS = [1, 2, 5, 10, 15, 20, 30, 60, 120, 300, 600, 900, 1800]
const MAX_ZOOM = 20
const OV_BAR = 20 // px: one overlay row
const OV_GAP = 3
const WINDOW = 40
const FX_LABELS: Record<string, string> = { hook: 'Title card', 'punch-in': 'Punch-in', 'wall-text': 'Couch wall', cover: 'Cover story', 'glass-text': 'Glass type' }
export const fxLabel = (type: string) => FX_LABELS[type] ?? type.replace(/-/g, ' ').replace(/^./, (c) => c.toUpperCase())
const baseName = (src: string) => src.split(/[\\/]/).pop() ?? src

function clock(s: number, long: boolean) {
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = String(Math.floor(s % 60)).padStart(2, '0')
  return long ? `${h}:${String(m).padStart(2, '0')}:${sec}` : `${Math.floor(s / 60)}:${sec}`
}
const exact = (frames: number) => {
  const s = frames / FPS
  return `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, '0')}`
}

/** Lane timeline under the preview, in output time. Drag anywhere to scrub,
 *  zoom with the slider or Ctrl+wheel; effects and overlays open on click. */
export function Timeline({ timeline, spec, frame, playing, playhead, seekFrame, seekSource, player, selectedEffect, onEffect, selectedOverlay, onOverlay, onOverlayTime, marks = [] }: Props) {
  const total = Math.max(1, timeline.totalFrames)
  const seconds = total / FPS
  const long = seconds >= 3600
  const pct = (f: number) => `${Math.min(100, Math.max(0, (f / total) * 100))}%`
  const [zoom, setZoom] = useState(1)
  const [dragging, setDragging] = useState(false)
  const scroller = useRef<HTMLDivElement>(null)
  const content = useRef<HTMLDivElement>(null)
  const anchor = useRef<{ frac: number; x: number } | null>(null)
  const drag = useRef<{ wasPlaying: boolean; pending: number | null; raf: number } | null>(null)

  const ticks = useMemo(() => {
    const visible = seconds / zoom
    const step = NICE_STEPS.find((s) => visible / s <= 6) ?? 3600
    const out: number[] = []
    for (let t = 0; t <= seconds; t += step) out.push(t)
    return out
  }, [seconds, zoom])

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
  const visibleWords = kept.slice(Math.max(0, at - 2), Math.max(0, at - 2) + WINDOW)

  const effects = useMemo(
    () =>
      (spec.effects ?? []).flatMap((e, index) => {
        const f = frameAtSource(timeline, e.at, FPS)
        if (f === null) return []
        const width = (e.duration * FPS) / total
        return [{ index, type: e.type, left: f, width, long: width * zoom > 0.06 }]
      }),
    [spec.effects, timeline, total, zoom]
  )

  // Overlays that are on screen at the same time get a row each.
  const { overlays, overlayRows } = useMemo(() => {
    const bars = (spec.overlays ?? []).flatMap((o) => {
      const span = outputSpan(timeline, o.from, o.to, FPS)
      return span ? [{ id: o.id, name: baseName(o.src), left: span[0], end: span[1], width: (span[1] - span[0]) / total, row: 0 }] : []
    })
    const ends: number[] = []
    for (const b of [...bars].sort((a, c) => a.left - c.left)) {
      const row = ends.findIndex((e) => e <= b.left)
      b.row = row < 0 ? ends.length : row
      ends[b.row] = b.end
    }
    return { overlays: bars, overlayRows: Math.max(1, ends.length) }
  }, [spec.overlays, timeline, total])
  const overlayLaneHeight = overlayRows * OV_BAR + (overlayRows - 1) * OV_GAP

  const cuts = useMemo(
    () =>
      (spec.cuts ?? []).flatMap((c) => {
        const f = frameAtSource(timeline, c.start - 0.02, FPS) ?? frameAtSource(timeline, c.end + 0.02, FPS)
        if (f === null) return []
        return [{ left: f, width: Math.min(0.02, (c.end - c.start) / seconds), len: c.end - c.start }]
      }),
    [spec.cuts, timeline, seconds]
  )

  // ---- overlay bars: drag the middle to move, an end to change when it starts or stops ----
  type BarMode = 'move' | 'start' | 'end'
  // The live position is kept in the ref too: a quick flick can end before React draws it.
  const bar = useRef<{ id: string; mode: BarMode; x0: number; left: number; end: number; moved: boolean; live: { left: number; end: number } | null } | null>(null)
  const [barLive, setBarLive] = useState<{ id: string; left: number; end: number } | null>(null)
  const first = timeline.introFrames
  const last = timeline.videoEnd // frame after the video's last
  const minFrames = Math.round(FPS / 2)
  const framesPerPx = () => total / (content.current?.getBoundingClientRect().width || 1)

  const barDown = (e: PointerEvent<HTMLElement>, id: string, mode: BarMode) => {
    if (e.button !== 0) return
    e.stopPropagation()
    const o = overlays.find((b) => b.id === id)
    if (!o) return
    e.currentTarget.setPointerCapture(e.pointerId)
    bar.current = { id, mode, x0: e.clientX, left: o.left, end: o.end, moved: false, live: null }
  }
  const barMove = (e: PointerEvent<HTMLElement>) => {
    const b = bar.current
    if (!b) return
    if (!b.moved && Math.abs(e.clientX - b.x0) < 4) return
    b.moved = true
    const d = Math.round((e.clientX - b.x0) * framesPerPx())
    let left = b.left
    let end = b.end
    if (b.mode === 'move') {
      const shift = Math.max(first - b.left, Math.min(last - b.end, d))
      left += shift
      end += shift
    } else if (b.mode === 'start') left = Math.max(first, Math.min(b.end - minFrames, b.left + d))
    else end = Math.min(last, Math.max(b.left + minFrames, b.end + d))
    b.live = { left, end }
    setBarLive({ id: b.id, left, end })
  }
  const barUp = (e: PointerEvent<HTMLElement>) => {
    const b = bar.current
    bar.current = null
    if (!b) return
    e.stopPropagation()
    const live = b.live
    setBarLive(null)
    if (!b.moved || !live) {
      onOverlay(b.id)
      return
    }
    // Within a few frames of the clip's ends counts as "from the start" / "to the end".
    const snap = 3
    const from = live.left <= first + snap ? null : sourceTimeAt(timeline, live.left, FPS)
    const lastShown = live.end >= last - snap ? null : sourceTimeAt(timeline, live.end - 1, FPS)
    onOverlayTime(b.id, from, lastShown === null ? null : lastShown + 1 / FPS)
  }

  // ---- zoom, keeping one point of the timeline still ----
  const zoomTo = (next: number, clientX?: number) => {
    const el = scroller.current
    const z = Math.min(MAX_ZOOM, Math.max(1, next))
    if (!el || z === zoom) return
    const r = el.getBoundingClientRect()
    const width = el.scrollWidth
    const playheadX = (frame / total) * width - el.scrollLeft
    const x = clientX !== undefined ? clientX - r.left : playheadX >= 0 && playheadX <= el.clientWidth ? playheadX : el.clientWidth / 2
    anchor.current = { frac: (el.scrollLeft + x) / width, x }
    setZoom(z)
  }
  useLayoutEffect(() => {
    const el = scroller.current
    const a = anchor.current
    if (!el || !a) return
    anchor.current = null
    el.scrollLeft = a.frac * el.scrollWidth - a.x
  }, [zoom])

  // Ctrl/⌘ + wheel zooms; a plain wheel scrolls sideways once zoomed in.
  const zoomRef = useRef(zoomTo)
  zoomRef.current = zoomTo
  const zoomRefValue = useRef(zoom)
  zoomRefValue.current = zoom
  useEffect(() => {
    const el = scroller.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault()
        zoomRef.current(zoomRefValue.current * Math.exp(-e.deltaY * 0.002), e.clientX)
      } else if (zoomRefValue.current > 1 && Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
        e.preventDefault()
        el.scrollLeft += e.deltaY
      }
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [])

  // Keep the playhead in view (while playing, or after a seek from elsewhere).
  useEffect(() => {
    const el = scroller.current
    if (!el || zoom <= 1 || drag.current) return
    const x = (frame / total) * el.scrollWidth
    if (x < el.scrollLeft || x > el.scrollLeft + el.clientWidth - 24) el.scrollLeft = x - el.clientWidth * (playing ? 0.1 : 0.4)
  }, [frame, total, zoom, playing])

  // ---- scrubbing ----
  const frameAt = (clientX: number) => {
    const r = content.current!.getBoundingClientRect()
    return Math.round(Math.min(1, Math.max(0, (clientX - r.left) / r.width)) * (total - 1))
  }
  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0 || (e.target as HTMLElement).closest('button')) return
    e.currentTarget.setPointerCapture(e.pointerId)
    const wasPlaying = player.isPlaying()
    if (wasPlaying) player.pause()
    drag.current = { wasPlaying, pending: null, raf: 0 }
    setDragging(true)
    seekFrame(frameAt(e.clientX))
  }
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current
    if (!d) return
    const el = scroller.current
    if (el) {
      const r = el.getBoundingClientRect()
      if (e.clientX > r.right - 24) el.scrollLeft += 14
      else if (e.clientX < r.left + 24) el.scrollLeft -= 14
    }
    d.pending = frameAt(e.clientX)
    if (!d.raf)
      d.raf = requestAnimationFrame(() => {
        d.raf = 0
        if (d.pending !== null) seekFrame(d.pending)
        d.pending = null
      })
  }
  const endDrag = () => {
    const d = drag.current
    if (!d) return
    if (d.raf) cancelAnimationFrame(d.raf)
    if (d.pending !== null) seekFrame(d.pending)
    drag.current = null
    setDragging(false)
    if (d.wasPlaying) player.play()
  }
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const step = (e.shiftKey ? 5 : 1) * FPS
    const to = e.key === 'ArrowRight' ? frame + step : e.key === 'ArrowLeft' ? frame - step : e.key === 'Home' ? 0 : e.key === 'End' ? total - 1 : null
    if (to === null) return
    e.preventDefault()
    seekFrame(Math.max(0, Math.min(total - 1, to)))
  }

  return (
    <div className="card timeline">
      <div className="tl-row tl-words-row">
        <span className="lane-label">Captions</span>
        <div className="words">
          {visibleWords.map(({ w, i }) => {
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
      </div>

      <div className="tl-body">
        <div className="labels" aria-hidden="true">
          <span className="lane-label ruler-row" />
          {overlays.length > 0 && (
            <span className="lane-label" style={{ height: overlayLaneHeight }}>
              Overlays
            </span>
          )}
          <span className="lane-label fx-row">Effects</span>
          <span className="lane-label cut-row">Cuts</span>
        </div>
        <div className="tl-scroll" ref={scroller}>
          <div
            className={`tl-content ${dragging ? 'dragging' : ''}`}
            ref={content}
            style={{ width: `${zoom * 100}%` }}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={endDrag}
            onPointerCancel={endDrag}
          >
            <div
              className="ruler ruler-row"
              role="slider"
              tabIndex={0}
              aria-label="Playhead position"
              aria-valuemin={0}
              aria-valuemax={Math.round(seconds)}
              aria-valuenow={Math.round(frame / FPS)}
              aria-valuetext={exact(frame)}
              onKeyDown={onKey}
            >
              {ticks.map((t) => (
                <span key={t} style={{ left: pct(t * FPS) }}>
                  {clock(t, long)}
                </span>
              ))}
              {marks.map((m, k) => (
                <i key={k} className="note-mark" style={{ left: pct(m.frame) }} title={m.label} />
              ))}
            </div>
            {overlays.length > 0 && (
              <div className="ov" style={{ height: overlayLaneHeight }}>
                {overlays.map((o) => {
                  const live = barLive?.id === o.id ? barLive : null
                  const left = live ? live.left : o.left
                  const width = live ? (live.end - live.left) / total : o.width
                  return (
                    <button
                      key={o.id}
                      className={[o.id === selectedOverlay && 'on', live && 'moving'].filter(Boolean).join(' ')}
                      style={{ left: pct(left), width: `${width * 100}%`, top: o.row * (OV_BAR + OV_GAP), height: OV_BAR }}
                      title={`Overlay ${o.name}: drag to move, drag an end to change when it shows`}
                      aria-label={`Overlay ${o.name}, ${exact(left)} to ${exact(live ? live.end : o.end)}`}
                      onPointerDown={(e) => barDown(e, o.id, 'move')}
                      onPointerMove={barMove}
                      onPointerUp={barUp}
                      onPointerCancel={() => {
                        bar.current = null
                        setBarLive(null)
                      }}
                      onClick={(e) => e.preventDefault()}
                      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && onOverlay(o.id)}
                    >
                      <span className="ov-edge start" aria-hidden="true" onPointerDown={(e) => barDown(e, o.id, 'start')} onPointerMove={barMove} onPointerUp={barUp} />
                      <span className="ov-label">{o.name}</span>
                      <span className="ov-edge end" aria-hidden="true" onPointerDown={(e) => barDown(e, o.id, 'end')} onPointerMove={barMove} onPointerUp={barUp} />
                      {live && <span className="ov-when">{`${exact(live.left)}–${exact(live.end)}`}</span>}
                    </button>
                  )
                })}
              </div>
            )}
            <div className="fx fx-row">
              {effects.map((e) => (
                <button
                  key={e.index}
                  className={[e.long && 'long', e.index === selectedEffect && 'on'].filter(Boolean).join(' ')}
                  style={{ left: pct(e.left), width: `max(6px, ${e.width * 100}%)` }}
                  aria-label={`${fxLabel(e.type)} at ${exact(e.left)}`}
                  title={`${fxLabel(e.type)} at ${exact(e.left)} · click to edit`}
                  onClick={() => onEffect(e.index)}
                >
                  {e.long ? fxLabel(e.type) : null}
                </button>
              ))}
            </div>
            <div className="cuts cut-row">
              {timeline.introOnScreen > 0 && (
                <b className="bookend" style={{ left: 0, width: pct(timeline.introOnScreen) }} title="Intro">
                  Intro
                </b>
              )}
              {timeline.hasOutro && (
                <b className="bookend" style={{ left: pct(timeline.outroStart), right: 0 }} title="Outro">
                  Outro
                </b>
              )}
              {timeline.transitions.map((m) => (
                <i key={m.from} className="transition-mark" style={{ left: pct(m.from + m.frames / 2) }} title={`${fxLabel(m.type)} transition`} />
              ))}
              {cuts.map((c, k) => (
                <span key={k} style={{ left: pct(c.left), width: `${c.width * 100}%` }} title={`Cut ${c.len.toFixed(1)} s`} />
              ))}
            </div>
            <div className="playhead" style={{ left: pct(frame) }}>
              <i className="grip" />
              {dragging && <span className="when">{exact(frame)}</span>}
            </div>
          </div>
        </div>
      </div>

      <div className="tl-tools">
        <span className="muted small">Drag the orange line to any moment</span>
        <span className="spacer" />
        <label className="zoom" htmlFor="tl-zoom">
          Zoom
        </label>
        <input id="tl-zoom" type="range" min={0} max={100} step={1} value={Math.round((Math.log(zoom) / Math.log(MAX_ZOOM)) * 100)} onChange={(e) => zoomTo(Math.pow(MAX_ZOOM, Number(e.target.value) / 100))} />
        <button className="sm" disabled={zoom === 1} onClick={() => zoomTo(1)}>
          Fit
        </button>
      </div>
    </div>
  )
}
