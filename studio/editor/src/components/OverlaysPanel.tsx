import { useEffect, useRef, useState } from 'react'
import { FPS, frameSize, outputSpan, overlayBox, overlaySchema, sourceTimeAt, type Overlay, type OverlayInput } from '@tetclipper/composition'
import { fileUrl, invoke, parseClock, upload } from '../api'
import type { PanelProps } from './Canvas'

interface LibraryItem {
  name: string
  kind: 'image' | 'gif' | 'video'
  path: string
  size: number
}

interface Props extends PanelProps {
  selected: string | null
  setSelected: (id: string | null) => void
  admin: boolean
}

const MAX_MB = 50
const MARGIN = 0.04 // corners sit this far in from the edge (fraction of the frame width)
const LONG_OVERLAY = 180 // seconds: past this a long video's render gets noticeably slower
const name = (src: string) => src.split(/[\\/]/).pop() ?? src
const newId = () => `ov-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))
const clockOf = (frames: number) => {
  const s = frames / FPS
  return `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, '0')}`
}

const SPOTS = [
  ['Top left', 0, 0],
  ['Top', 1, 0],
  ['Top right', 2, 0],
  ['Left', 0, 1],
  ['Centre', 1, 1],
  ['Right', 2, 1],
  ['Bottom left', 0, 2],
  ['Bottom', 1, 2],
  ['Bottom right', 2, 2]
] as const

/** Photos, GIFs and videos on top of the clip: add from the team's library or
 *  upload, then place them here or by dragging on the video. */
export function OverlaysPanel({ data, spec, editor, update, setError, timeline, selected, setSelected, admin }: Props) {
  const [library, setLibrary] = useState<LibraryItem[] | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const file = useRef<HTMLInputElement>(null)
  const format = spec.format ?? 'vertical'
  const { width: W, height: H } = frameSize(format)
  // One bad overlay (a hand edit) must not take the whole editor down: skip it here.
  const overlays: Overlay[] = (spec.overlays ?? []).flatMap((o) => {
    const r = overlaySchema.safeParse(o)
    return r.success ? [r.data] : []
  })
  const current = overlays.find((o) => o.id === selected) ?? null

  useEffect(() => {
    invoke<LibraryItem[]>('overlay_library')
      .then(setLibrary)
      .catch(() => setLibrary([]))
  }, [])

  const save = (next: OverlayInput[], reason: string) => update({ ...spec, overlays: next }, reason)
  const patch = (id: string, p: Partial<OverlayInput>, reason: string) => save((spec.overlays ?? []).map((o) => (o.id === id ? { ...o, ...p } : o)), reason)

  /** Put a library file on this clip: top right, a quarter of the width, the whole clip. */
  const attach = async (item: LibraryItem) => {
    setBusy(item.name)
    try {
      const res = await invoke<{ src: string; width?: number; height?: number; duration?: number }>('studio_attach', { jobId: data.jobId, clip: data.clip, path: item.path })
      const aspect = res.width && res.height ? res.width / res.height : 1
      const width = 0.25
      const box = overlayBox({ x: 0, y: 0, width, aspect }, W, H)
      const overlay: OverlayInput = {
        id: newId(),
        src: res.src,
        kind: item.kind,
        from: null,
        to: null,
        x: 1 - width / 2 - MARGIN,
        y: box.height / 2 + (MARGIN * W) / H,
        width,
        aspect,
        ...(res.duration && item.kind !== 'image' ? { duration: res.duration } : {})
      }
      save([...(spec.overlays ?? []), overlay], 'add overlay')
      setSelected(overlay.id)
    } catch (e) {
      setError(String((e as Error).message ?? e))
    } finally {
      setBusy(null)
    }
  }

  const onUpload = async (f: File) => {
    if (f.size > MAX_MB * 1024 * 1024) {
      setError(`That file is too big for an overlay (the limit is ${MAX_MB} MB).`)
      return
    }
    setBusy('upload')
    try {
      const item = await invoke<LibraryItem>('overlay_library_add', { path: await upload(f) })
      setLibrary((l) => [item, ...(l ?? [])])
      await attach(item)
    } catch (e) {
      setError(String((e as Error).message ?? e))
    } finally {
      setBusy(null)
    }
  }

  // ---- times: shown and typed as clip time, stored as source seconds ----
  // Shown from where the overlay really starts and stops on screen, so a time
  // that falls inside a cut shows the moment the overlay appears or leaves.
  const shownTimes = (o: Overlay): [string, string] => {
    const span = timeline ? outputSpan(timeline, o.from, o.to, FPS) : null
    if (!span || !timeline) return [o.from === null ? 'start' : '—', o.to === null ? 'end' : '—']
    return [o.from === null ? 'start' : clockOf(span[0]), o.to === null ? 'end' : clockOf(span[1])]
  }
  const typedTime = (text: string): number | null => {
    if (!timeline) return null
    const s = parseClock(text)
    if (!Number.isFinite(s)) return null
    return sourceTimeAt(timeline, Math.round(s * FPS), FPS)
  }
  const setTime = (o: Overlay, key: 'from' | 'to', t: number | null) => {
    const from = key === 'from' ? t : o.from
    const to = key === 'to' ? t : o.to
    if (from !== null && to !== null && to <= from) {
      setError('“Leaves at” must be after “Appears at”.')
      return
    }
    patch(o.id, { [key]: t }, key === 'from' ? 'overlay start' : 'overlay end')
  }
  const commitTime = (o: Overlay, key: 'from' | 'to', text: string) => {
    if (text.trim() === '') return setTime(o, key, null)
    const t = typedTime(text)
    if (t === null) {
      setError('Type a time inside the clip, like 0:12.5.')
      return
    }
    setTime(o, key, t)
  }

  const span = current && timeline ? outputSpan(timeline, current.from, current.to, FPS) : null
  const onScreen = span ? (span[1] - span[0]) / FPS : 0

  return (
    <div className="overlays-panel">
      <div className="panel-title">Overlays</div>
      <p className="muted small">A logo, a GIF or a short video on top of the clip. Drag it on the video to move it; pull a corner to resize.</p>

      <button className="tonal lg" disabled={busy !== null} onClick={() => file.current?.click()}>
        {busy === 'upload' ? 'Uploading…' : 'Add a photo, GIF or video'}
      </button>
      <input
        ref={file}
        type="file"
        hidden
        accept="image/png,image/jpeg,image/webp,image/gif,video/mp4,video/quicktime,video/webm"
        onChange={(e) => {
          const f = e.target.files?.[0]
          e.target.value = ''
          if (f) onUpload(f)
        }}
      />

      {overlays.length > 0 && (
        <div className="field">
          <span className="label">On this clip</span>
          <div className="ov-list">
            {overlays.map((o) => (
              <button key={o.id} className={o.id === selected ? 'on' : ''} onClick={() => setSelected(o.id === selected ? null : o.id)}>
                <span className="ov-name">{name(o.src)}</span>
                <span className="muted small mono">{o.from === null && o.to === null ? 'whole clip' : shownTimes(o).join('–')}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {current && (
        <div className="ov-settings">
          <div className="row">
            <b className="ov-name">{name(current.src)}</b>
            <span className="spacer" />
            <button
              className="sm danger"
              onClick={() => {
                save((spec.overlays ?? []).filter((o) => o.id !== current.id), 'remove overlay')
                setSelected(null)
              }}
            >
              Remove
            </button>
          </div>

          <div className="ov-place">
            <div className="field">
              <span className="label">Snap to</span>
              <div className="snap-grid" role="group" aria-label="Snap to a spot">
                {SPOTS.map(([label, col, row]) => {
                  const box = overlayBox(current, W, H)
                  const mx = MARGIN
                  const my = (MARGIN * W) / H
                  const x = [box.width / 2 + mx, 0.5, 1 - box.width / 2 - mx][col]
                  const y = [box.height / 2 + my, 0.5, 1 - box.height / 2 - my][row]
                  const on = Math.abs(current.x - x) < 0.002 && Math.abs(current.y - y) < 0.002
                  return <button key={label} className={on ? 'on' : ''} aria-label={label} aria-pressed={on} title={label} onClick={() => patch(current.id, { x: clamp(x, 0, 1), y: clamp(y, 0, 1) }, 'move overlay')} />
                })}
              </div>
            </div>
            <p className="muted small">Or drag it on the video. Arrow keys nudge it once it’s selected.</p>
          </div>

          <div className="controls">
            <label className="slider">
              Size <span>{Math.round(current.width * 100)}%</span>
              <input type="range" min={3} max={100} value={Math.round(current.width * 100)} onChange={(e) => patch(current.id, { width: Number(e.target.value) / 100 }, 'resize overlay')} />
            </label>
            <label className="slider">
              See-through <span>{Math.round((1 - current.opacity) * 100)}%</span>
              <input type="range" min={0} max={90} value={Math.round((1 - current.opacity) * 100)} onChange={(e) => patch(current.id, { opacity: 1 - Number(e.target.value) / 100 }, 'overlay see-through')} />
            </label>
            <label className="slider">
              Turn <span>{Math.round(current.rotation)}°</span>
              <input type="range" min={-180} max={180} value={Math.round(current.rotation)} onChange={(e) => patch(current.id, { rotation: Number(e.target.value) }, 'turn overlay')} />
            </label>
          </div>

          <div className="field">
            <label className="toggle">
              <input
                type="checkbox"
                checked={current.from === null && current.to === null}
                onChange={(e) =>
                  e.target.checked ? patch(current.id, { from: null, to: null }, 'overlay whole clip') : patch(current.id, { from: editor.playhead ?? spec.source.start, to: null }, 'overlay start')
                }
              />
              Whole clip
            </label>
            <div className="ov-times">
              <TimeBox
                label="Appears at"
                value={shownTimes(current)[0]}
                onCommit={(text) => commitTime(current, 'from', text)}
                onPlayhead={() => editor.playhead !== null && setTime(current, 'from', editor.playhead)}
              />
              <TimeBox
                label="Leaves at"
                value={shownTimes(current)[1]}
                onCommit={(text) => commitTime(current, 'to', text)}
                onPlayhead={() => editor.playhead !== null && setTime(current, 'to', editor.playhead)}
              />
            </div>
          </div>

          {format === 'landscape' && onScreen > LONG_OVERLAY && (
            <p className="note wn">On a long video, every minute an overlay is on screen makes the render slower and cost more (about $5 for a whole hour). Shorten it if it doesn’t need to stay.</p>
          )}
        </div>
      )}

      <div className="field">
        <span className="label">Team overlays</span>
        {library === null ? (
          <span className="muted small">Loading…</span>
        ) : library.length === 0 ? (
          <span className="muted small">Nothing yet. Files you add here are shared with the whole team.</span>
        ) : (
          <div className="ov-library">
            {library.map((item) => (
              <div key={item.path} className="ov-tile">
                <button disabled={busy !== null} onClick={() => attach(item)} title={`Put ${item.name} on this clip`}>
                  {item.kind === 'video' ? <video src={fileUrl(item.path)} muted preload="metadata" /> : <img src={fileUrl(item.path)} alt="" loading="lazy" />}
                  <span>{busy === item.name ? 'Adding…' : item.name}</span>
                </button>
                {admin && (
                  <button
                    className="ov-remove"
                    aria-label={`Remove ${item.name} from the team overlays`}
                    title="Remove from the team overlays (clips that use it keep it)"
                    onClick={async () => {
                      try {
                        setLibrary(await invoke<LibraryItem[]>('overlay_library_remove', { name: item.name }))
                      } catch (e) {
                        setError(String((e as Error).message ?? e))
                      }
                    }}
                  >
                    ✕
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function TimeBox({ label, value, onCommit, onPlayhead }: { label: string; value: string; onCommit: (text: string) => void; onPlayhead: () => void }) {
  const [text, setText] = useState(value)
  useEffect(() => setText(value), [value])
  const id = `ov-${label.replace(/\s+/g, '-').toLowerCase()}`
  return (
    <div className="field">
      <label className="label" htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        className="mono"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={() => text !== value && onCommit(/^(start|end)$/i.test(text) ? '' : text)}
        onKeyDown={(e) => e.key === 'Enter' && (e.target as HTMLInputElement).blur()}
      />
      <button className="link small" onClick={onPlayhead}>
        Set to the playhead
      </button>
    </div>
  )
}
