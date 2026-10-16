// Music bed gain per output frame. The Python render (pipeline/tetclipper_pipeline/
// spec/music.py) implements the same rules so the preview and the final mix match:
//   speech spans = words merged across gaps < MERGE_GAP, padded by PAD
//   duck: move toward `duck` while speech plays, back to 1 after, at most
//         (1 - duck) per RAMP seconds
//   fades: linear in over fadeIn, out over fadeOut (output timeline)
import type { ClipSpec } from './spec'
import { type Timeline, sourceTimeAt } from './timeline'

export const MERGE_GAP = 0.35
export const PAD = 0.08
export const RAMP = 0.15

export function speechSpans(words: ClipSpec['words']): [number, number][] {
  const spans: [number, number][] = []
  for (const w of [...words].sort((a, b) => a.start - b.start)) {
    const last = spans[spans.length - 1]
    if (last && w.start - last[1] < MERGE_GAP) last[1] = Math.max(last[1], w.end)
    else spans.push([w.start, w.end])
  }
  return spans.map(([a, b]) => [a - PAD, b + PAD])
}

export function musicGains(spec: ClipSpec, tl: Timeline, fps: number): number[] {
  const m = spec.music
  const n = tl.totalFrames
  if (!m) return new Array(n).fill(0)
  const spans = speechSpans(spec.words)
  const step = (1 - m.duck) / Math.max(1, RAMP * fps)
  const gains: number[] = []
  let duck = 1
  for (let f = 0; f < n; f++) {
    const t = sourceTimeAt(tl, f, fps)
    const speaking = t !== null && spans.some(([a, b]) => t >= a && t <= b)
    const target = speaking ? m.duck : 1
    duck += Math.max(-step, Math.min(step, target - duck))
    const fadeIn = m.fadeIn > 0 ? f / (m.fadeIn * fps) : 1
    const fadeOut = m.fadeOut > 0 ? (n - 1 - f) / (m.fadeOut * fps) : 1
    gains.push(m.volume * duck * Math.max(0, Math.min(1, fadeIn, fadeOut)))
  }
  return gains
}
