// Output timeline ↔ source time. The output is the intro still followed by
// the source range with every cut removed; all maths is done in whole frames
// so segments butt together with no gaps or overlaps.
import { useCurrentFrame, useVideoConfig } from 'remotion'
import type { ClipSpec, Cut } from './spec'

export interface Segment {
  start: number // source seconds
  end: number
  fromFrame: number // first output frame of this segment
  frames: number
}

export interface Timeline {
  introFrames: number
  segments: Segment[]
  totalFrames: number
}

/** Merge overlapping cuts and clamp them to the source range. */
export function normalizeCuts(cuts: Cut[], start: number, end: number): Cut[] {
  const sorted = cuts
    .map((c) => ({ start: Math.max(start, Math.min(c.start, c.end)), end: Math.min(end, Math.max(c.start, c.end)) }))
    .filter((c) => c.end > c.start)
    .sort((a, b) => a.start - b.start)
  const merged: Cut[] = []
  for (const c of sorted) {
    const last = merged[merged.length - 1]
    if (last && c.start <= last.end) last.end = Math.max(last.end, c.end)
    else merged.push({ ...c })
  }
  return merged
}

export function buildTimeline(spec: Pick<ClipSpec, 'source' | 'cuts' | 'intro'>, fps: number): Timeline {
  const { start, end } = spec.source
  const introFrames = spec.intro ? Math.round(spec.intro.duration * fps) : 0
  const segments: Segment[] = []
  let cursor = start
  let frame = introFrames
  const push = (a: number, b: number) => {
    const frames = Math.round((b - a) * fps)
    if (frames < 1) return
    segments.push({ start: a, end: b, fromFrame: frame, frames })
    frame += frames
  }
  for (const c of normalizeCuts(spec.cuts, start, end)) {
    push(cursor, c.start)
    cursor = c.end
  }
  push(cursor, end)
  return { introFrames, segments, totalFrames: Math.max(1, frame) }
}

/** Source time shown at an output frame, or null while the intro is on screen. */
export function sourceTimeAt(tl: Timeline, frame: number, fps: number): number | null {
  if (frame < tl.introFrames) return null
  for (const s of tl.segments) {
    if (frame < s.fromFrame + s.frames) return s.start + Math.max(0, frame - s.fromFrame) / fps
  }
  const last = tl.segments[tl.segments.length - 1]
  return last ? last.end : null
}

/** Output frame at which a source time is shown (null if it was cut). */
export function frameAtSource(tl: Timeline, t: number, fps: number): number | null {
  for (const s of tl.segments) {
    if (t >= s.start && t < s.end) return s.fromFrame + Math.round((t - s.start) * fps)
  }
  return null
}

export function isInCut(tl: Timeline, t: number): boolean {
  return !tl.segments.some((s) => t >= s.start && t < s.end)
}

/** Hook: current source time for the clip being rendered (null during the intro). */
export function useSourceTime(tl: Timeline): number | null {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  return sourceTimeAt(tl, frame, fps)
}
