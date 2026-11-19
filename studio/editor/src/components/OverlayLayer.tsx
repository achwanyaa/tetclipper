import { useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'
import { FPS, outputSpan, overlayBox, type Overlay, type Timeline } from '@tetclipper/composition'

export type OverlayPatch = Partial<Pick<Overlay, 'x' | 'y' | 'width'>>

interface Props {
  overlays: Overlay[]
  timeline: Timeline
  frame: number
  frameWidth: number
  frameHeight: number
  selected: string | null
  onSelect: (id: string) => void
  onChange: (id: string, patch: OverlayPatch, reason: string) => void
}

const SNAP = 0.012
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))
const name = (o: Overlay) => o.src.split(/[\\/]/).pop() ?? 'overlay'

interface Op {
  id: string
  mode: 'move' | 'resize'
  startX: number
  startY: number
  base: Overlay
  raf: number
  next: OverlayPatch | null
}

/** Invisible boxes over the preview, one per overlay on screen now: click to
 *  select, drag to move, pull a corner to resize. Empty video still plays and
 *  pauses on click: only the boxes take the pointer. */
export function OverlayLayer({ overlays, timeline, frame, frameWidth, frameHeight, selected, onSelect, onChange }: Props) {
  const layer = useRef<HTMLDivElement>(null)
  const op = useRef<Op | null>(null)
  const [live, setLive] = useState<{ id: string; patch: OverlayPatch } | null>(null)
  const [guides, setGuides] = useState({ v: false, h: false })

  const shown = overlays.filter((o) => {
    const span = outputSpan(timeline, o.from, o.to, FPS)
    return span !== null && frame >= span[0] && frame < span[1]
  })

  const flush = (o: Op, final: boolean) => {
    if (o.raf) cancelAnimationFrame(o.raf)
    o.raf = 0
    if (o.next) onChange(o.id, o.next, o.mode === 'move' ? 'move overlay' : 'resize overlay')
    if (final) o.next = null
  }

  const start = (e: PointerEvent<HTMLElement>, o: Overlay, mode: Op['mode']) => {
    if (e.button !== 0) return
    e.stopPropagation()
    e.preventDefault()
    onSelect(o.id)
    e.currentTarget.setPointerCapture(e.pointerId)
    op.current = { id: o.id, mode, startX: e.clientX, startY: e.clientY, base: o, raf: 0, next: null }
  }

  const move = (e: PointerEvent<HTMLElement>) => {
    const o = op.current
    const r = layer.current?.getBoundingClientRect()
    if (!o || !r) return
    const b = o.base
    let patch: OverlayPatch
    if (o.mode === 'move') {
      const box = overlayBox(b, frameWidth, frameHeight)
      let x = clamp(b.x + (e.clientX - o.startX) / r.width, 0, 1)
      let y = clamp(b.y + (e.clientY - o.startY) / r.height, 0, 1)
      // Light snapping to the centre lines and the frame's edges.
      const v = Math.abs(x - 0.5) < SNAP
      const h = Math.abs(y - 0.5) < SNAP
      if (v) x = 0.5
      else if (Math.abs(x - box.width / 2) < SNAP) x = box.width / 2
      else if (Math.abs(x - (1 - box.width / 2)) < SNAP) x = 1 - box.width / 2
      if (h) y = 0.5
      else if (Math.abs(y - box.height / 2) < SNAP) y = box.height / 2
      else if (Math.abs(y - (1 - box.height / 2)) < SNAP) y = 1 - box.height / 2
      setGuides((g) => (g.v === v && g.h === h ? g : { v, h }))
      patch = { x, y }
    } else {
      // Corners resize about the centre, keeping the overlay's shape.
      const cx = r.left + b.x * r.width
      const cy = r.top + b.y * r.height
      const byWidth = (2 * Math.abs(e.clientX - cx)) / r.width
      const byHeight = ((2 * Math.abs(e.clientY - cy)) / r.height) * (frameHeight / frameWidth) * b.aspect
      patch = { width: clamp(Math.max(byWidth, byHeight), 0.03, 1) }
    }
    setLive({ id: o.id, patch })
    o.next = patch
    if (!o.raf)
      o.raf = requestAnimationFrame(() => {
        o.raf = 0
        flush(o, false)
      })
  }

  const end = () => {
    const o = op.current
    if (!o) return
    flush(o, true)
    op.current = null
    setLive(null)
    setGuides({ v: false, h: false })
  }

  const nudge = (e: KeyboardEvent<HTMLButtonElement>, o: Overlay) => {
    const step = e.shiftKey ? 0.025 : 0.005
    const dx = e.key === 'ArrowLeft' ? -step : e.key === 'ArrowRight' ? step : 0
    const dy = e.key === 'ArrowUp' ? -step : e.key === 'ArrowDown' ? step : 0
    if (!dx && !dy) return
    e.preventDefault()
    onChange(o.id, { x: clamp(o.x + dx, 0, 1), y: clamp(o.y + dy, 0, 1) }, 'move overlay')
  }

  return (
    <div className="overlay-layer" ref={layer}>
      {guides.v && <i className="guide v" />}
      {guides.h && <i className="guide h" />}
      {shown.map((o) => {
        const now = live && live.id === o.id ? { ...o, ...live.patch } : o
        const box = overlayBox(now, frameWidth, frameHeight)
        const on = o.id === selected
        return (
          <button
            key={o.id}
            className={`ov-box ${on ? 'on' : ''}`}
            style={{
              left: `${box.x * 100}%`,
              top: `${box.y * 100}%`,
              width: `${box.width * 100}%`,
              height: `${box.height * 100}%`,
              transform: `translate(-50%, -50%) rotate(${o.rotation}deg)`
            }}
            aria-label={`Overlay ${name(o)}${on ? ', selected' : ''}. Drag to move, arrow keys to nudge.`}
            onPointerDown={(e) => start(e, o, 'move')}
            onPointerMove={move}
            onPointerUp={end}
            onPointerCancel={end}
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => nudge(e, o)}
          >
            {on &&
              (['nw', 'ne', 'sw', 'se'] as const).map((c) => (
                <span
                  key={c}
                  className={`ov-handle ${c}`}
                  aria-hidden="true"
                  onPointerDown={(e) => start(e, o, 'resize')}
                  onPointerMove={move}
                  onPointerUp={end}
                  onPointerCancel={end}
                />
              ))}
          </button>
        )
      })}
    </div>
  )
}
