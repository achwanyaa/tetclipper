import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'
import { playPreview, stopPreview, useAudioPreview } from '../audioPreview'

const BARS = 96
const MIN_SPAN = 1
const round = (t: number) => Math.round(t * 10) / 10
const clock = (s: number) => `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, '0')}`

interface Wave {
  peaks: number[] | null // null: couldn't decode, plain bars instead
  duration: number
}

const waves = new Map<string, Promise<Wave>>()

/** Peaks and length of a track, decoded once in the browser. */
function loadWave(url: string): Promise<Wave> {
  let wave = waves.get(url)
  if (!wave) {
    wave = fetch(url)
      .then((r) => {
        if (!r.ok) throw new Error(String(r.status))
        return r.arrayBuffer()
      })
      .then((bytes) => new OfflineAudioContext(1, 1, 44100).decodeAudioData(bytes))
      .then((audio) => {
        const data = audio.getChannelData(0)
        const size = Math.max(1, Math.floor(data.length / BARS))
        const peaks: number[] = []
        for (let i = 0; i < BARS; i++) {
          let max = 0
          for (let j = i * size; j < Math.min(data.length, (i + 1) * size); j += 64) max = Math.max(max, Math.abs(data[j]))
          peaks.push(max)
        }
        const top = Math.max(...peaks, 0.01)
        return { peaks: peaks.map((p) => p / top), duration: audio.duration }
      })
      .catch(
        () =>
          new Promise<Wave>((resolve) => {
            const probe = new Audio()
            probe.preload = 'metadata'
            probe.onloadedmetadata = () => resolve({ peaks: null, duration: Number.isFinite(probe.duration) ? probe.duration : 0 })
            probe.onerror = () => resolve({ peaks: null, duration: 0 })
            probe.src = url
          })
      )
    waves.set(url, wave)
  }
  return wave
}

interface Props {
  url: string
  start: number
  end: number | null
  clipSeconds: number
  loop: boolean
  beforePlay: () => void
  onChange: (start: number, end: number | null, reason: string) => void
}

/** Pick the part of the track to use: drag either handle or the window itself.
 *  The spec only changes on release, so one drag is one undo step. */
export function MusicRange({ url, start, end, clipSeconds, loop, beforePlay, onChange }: Props) {
  const [wave, setWave] = useState<Wave | null>(null)
  const [drag, setDrag] = useState<[number, number] | null>(null)
  const track = useRef<HTMLDivElement>(null)
  const grab = useRef<{ mode: 'start' | 'end' | 'move'; x: number; from: [number, number] } | null>(null)
  const preview = useAudioPreview()
  const duration = wave?.duration ?? 0
  const playing = preview.playing && preview.url === url

  useEffect(() => {
    let live = true
    setWave(null)
    loadWave(url).then((w) => live && setWave(w))
    return () => {
      live = false
      stopPreview()
    }
  }, [url])

  const saved: [number, number] = [Math.min(start, duration), end === null ? duration : Math.min(end, duration)]
  const [a, b] = drag ?? saved
  const pct = (t: number) => (duration > 0 ? (t / duration) * 100 : 0)

  const moved = (mode: 'start' | 'end' | 'move', from: [number, number], by: number): [number, number] => {
    if (mode === 'start') return [round(Math.max(0, Math.min(from[1] - MIN_SPAN, from[0] + by))), from[1]]
    if (mode === 'end') return [from[0], round(Math.min(duration, Math.max(from[0] + MIN_SPAN, from[1] + by)))]
    const shift = Math.max(-from[0], Math.min(duration - from[1], by))
    return [round(from[0] + shift), round(from[1] + shift)]
  }

  const commit = (next: [number, number], reason: string) => {
    onChange(next[0], next[1] >= duration ? null : next[1], reason)
    if (playing) play(next)
  }

  const play = (range: [number, number]) => {
    beforePlay()
    playPreview(url, range[0], range[1])
  }

  const onDown = (mode: 'start' | 'end' | 'move') => (e: PointerEvent<HTMLElement>) => {
    if (!duration) return
    e.preventDefault()
    e.stopPropagation()
    e.currentTarget.setPointerCapture(e.pointerId)
    grab.current = { mode, x: e.clientX, from: [a, b] }
    setDrag([a, b])
  }
  const onMove = (e: PointerEvent<HTMLElement>) => {
    const g = grab.current
    const width = track.current?.getBoundingClientRect().width
    if (!g || !width) return
    setDrag(moved(g.mode, g.from, ((e.clientX - g.x) / width) * duration))
  }
  const onUp = () => {
    const g = grab.current
    grab.current = null
    if (g && drag) commit(drag, g.mode === 'move' ? 'music range' : `music ${g.mode}`)
    setDrag(null)
  }
  const onKey = (mode: 'start' | 'end' | 'move') => (e: KeyboardEvent<HTMLElement>) => {
    const step = e.shiftKey ? 1 : 0.1
    const by = e.key === 'ArrowLeft' || e.key === 'ArrowDown' ? -step : e.key === 'ArrowRight' || e.key === 'ArrowUp' ? step : 0
    if (!by || !duration) return
    e.preventDefault()
    commit(moved(mode, [a, b], by), mode === 'move' ? 'music range' : `music ${mode}`)
  }

  const span = b - a
  const hint = span >= clipSeconds ? 'ends with the clip' : loop ? 'loops' : 'stops early'

  return (
    <div className="music-range">
      <div className="range-top">
        <button
          className="round-play"
          disabled={!duration}
          aria-label={playing ? 'Pause the preview' : 'Play the selected part'}
          onClick={() => (playing ? stopPreview() : play([a, b]))}
        >
          {playing ? '❚❚' : '▶'}
        </button>
        <span className="range-times">
          <b>{clock(a)}</b>
          <span className="muted"> – </span>
          <b>{clock(b)}</b>
        </span>
        <span className="spacer" />
        <button className="sm" disabled={!duration} onClick={() => commit([a, round(Math.min(duration, a + clipSeconds))], 'music fit to clip')}>
          Fit to clip
        </button>
      </div>

      <div className={`range-track ${duration ? '' : 'loading'}`} ref={track}>
        <div className="range-bars">
          {Array.from({ length: BARS }, (_, i) => {
            const at = ((i + 0.5) / BARS) * duration
            const peak = wave?.peaks?.[i] ?? 0.45
            return <i key={i} className={at >= a && at <= b ? 'in' : ''} style={{ height: `${12 + peak * 88}%` }} />
          })}
        </div>
        {duration > 0 && (
          <>
            <div
              className="range-window"
              style={{ left: `${pct(a)}%`, width: `${pct(b - a)}%` }}
              role="slider"
              tabIndex={0}
              aria-label="Move the selected part"
              aria-valuemin={0}
              aria-valuemax={duration}
              aria-valuenow={a}
              aria-valuetext={`${clock(a)} to ${clock(b)}`}
              onPointerDown={onDown('move')}
              onPointerMove={onMove}
              onPointerUp={onUp}
              onPointerCancel={onUp}
              onKeyDown={onKey('move')}
            >
              {(['start', 'end'] as const).map((mode) => (
                <span
                  key={mode}
                  className={`range-handle ${mode}`}
                  role="slider"
                  tabIndex={0}
                  aria-label={mode === 'start' ? 'Music start' : 'Music end'}
                  aria-valuemin={0}
                  aria-valuemax={duration}
                  aria-valuenow={mode === 'start' ? a : b}
                  aria-valuetext={clock(mode === 'start' ? a : b)}
                  onPointerDown={onDown(mode)}
                  onPointerMove={onMove}
                  onPointerUp={onUp}
                  onPointerCancel={onUp}
                  onKeyDown={(e) => {
                    e.stopPropagation()
                    onKey(mode)(e)
                  }}
                />
              ))}
            </div>
            {playing && preview.time >= a && preview.time <= b && <div className="range-playhead" style={{ left: `${pct(preview.time)}%` }} />}
          </>
        )}
      </div>

      <p className="muted small">
        {duration
          ? `Clip ${clock(clipSeconds)} · selection ${clock(span)} · ${hint}. Track ${clock(duration)}.`
          : wave
            ? "Couldn't read this track."
            : 'Reading the track…'}
      </p>
    </div>
  )
}
