// Music bed gain per output frame. The Python render (pipeline/tetclipper_pipeline/
// spec/music.py) implements the same rules so the preview and the final mix match:
//   speech spans = words merged across gaps < MERGE_GAP, padded by PAD
//   duck: move toward `duck` while speech plays, back to 1 after, at most
//         (1 - duck) per RAMP seconds
//   fades: linear in over fadeIn, out over fadeOut (output timeline); a range
//         that won't loop and ends early fades out where it ends
//   an intro or outro video with its own sound counts as speech
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

/** The track range in use: [start, end], end null = the track's end. */
export function musicRange(m: NonNullable<ClipSpec['music']>): [number, number | null] {
  return [m.offset, m.end !== null && m.end > m.offset ? m.end : null]
}

/** The spans are disjoint and sorted: merging leaves gaps wider than the padding. */
function inSpans(spans: [number, number][], t: number): boolean {
  let lo = 0
  let hi = spans.length - 1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (t < spans[mid][0]) hi = mid - 1
    else if (t > spans[mid][1]) lo = mid + 1
    else return true
  }
  return false
}

const hasSound = (b: ClipSpec['intro']) => b !== null && b.kind === 'video' && b.volume > 0

export function musicGains(spec: ClipSpec, tl: Timeline, fps: number): number[] {
  const m = spec.music
  const n = tl.totalFrames
  if (!m) return new Array(n).fill(0)
  const spans = speechSpans(spec.words)
  const [from, to] = musicRange(m)
  const last = !m.loop && to !== null ? Math.min(n, Math.round((to - from) * fps)) : n
  const introSounds = hasSound(spec.intro)
  const outroSounds = hasSound(spec.outro)
  const step = (1 - m.duck) / Math.max(1, RAMP * fps)
  const gains: number[] = []
  let duck = 1
  for (let f = 0; f < n; f++) {
    const t = sourceTimeAt(tl, f, fps)
    const speaking =
      (t !== null && inSpans(spans, t)) || (introSounds && f < tl.introOnScreen) || (outroSounds && f >= tl.outroStart)
    const target = speaking ? m.duck : 1
    duck += Math.max(-step, Math.min(step, target - duck))
    const fadeIn = m.fadeIn > 0 ? f / (m.fadeIn * fps) : 1
    const fadeOut = m.fadeOut > 0 ? (last - 1 - f) / (m.fadeOut * fps) : f < last ? 1 : 0
    gains.push(m.volume * duck * Math.max(0, Math.min(1, fadeIn, fadeOut)))
  }
  return gains
}
