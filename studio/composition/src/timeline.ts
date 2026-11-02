// Output timeline ↔ source time. The output is the intro, then the source range
// with every cut removed, then the outro; all maths is done in whole frames so
// segments butt together with no gaps or overlaps. Python mirror: spec/timeline.py.
import { useCurrentFrame, useVideoConfig } from 'remotion'
import type { ClipSpec, Cut, TransitionType } from './spec'

export interface Segment {
  start: number // source seconds
  end: number
  fromFrame: number // first output frame of this segment
  frames: number
}

/** A dissolve-style move across one cut, centred on it. The clip's length and
 *  sound don't change: each side just keeps playing into the removed footage. */
export interface CutTransition {
  type: TransitionType
  from: number // first output frame
  frames: number
  outgoing: number // source seconds of the outgoing shot at `from`
  incoming: number // source seconds of the incoming shot at `from`
}

export interface Timeline {
  introFrames: number // first frame of the video
  introOnScreen: number // the intro stays this long, past introFrames while its transition runs
  segments: Segment[]
  transitions: CutTransition[]
  videoEnd: number // frame after the video's last
  outroStart: number // the outro's first frame, before videoEnd while its transition runs
  hasOutro: boolean
  totalFrames: number
}

/** Merge overlapping cuts and clamp them to the source range. */
export function normalizeCuts(cuts: Cut[], start: number, end: number): Cut[] {
  const sorted = cuts
    .map((c) => ({ ...c, start: Math.max(start, Math.min(c.start, c.end)), end: Math.min(end, Math.max(c.start, c.end)) }))
    .filter((c) => c.end > c.start)
    .sort((a, b) => a.start - b.start)
  const merged: Cut[] = []
  for (const c of sorted) {
    const last = merged[merged.length - 1]
    if (last && c.start <= last.end) {
      last.end = Math.max(last.end, c.end)
      last.transition = last.transition ?? c.transition
    } else merged.push({ ...c })
  }
  return merged
}

/** Frames on screen and frames overlapping the video, for an intro or outro. */
function bookendFrames(item: ClipSpec['intro'], videoFrames: number, fps: number): [number, number] {
  if (!item) return [0, 0]
  const onScreen = Math.round(item.duration * fps)
  const wanted = item.transition ? Math.round(item.transition.duration * fps) : 0
  return [onScreen, Math.max(0, Math.min(wanted, onScreen - 1, videoFrames))]
}

export function buildTimeline(spec: Pick<ClipSpec, 'source' | 'cuts' | 'intro' | 'outro'>, fps: number): Timeline {
  const { start, end } = spec.source
  const pieces: { start: number; end: number; frames: number; transition: Cut['transition'] }[] = []
  let cursor = start
  let entering: Cut['transition'] = null
  const push = (a: number, b: number) => {
    const frames = Math.round((b - a) * fps)
    if (frames < 1) return
    pieces.push({ start: a, end: b, frames, transition: pieces.length ? entering : null })
    entering = null
  }
  for (const c of normalizeCuts(spec.cuts, start, end)) {
    push(cursor, c.start)
    cursor = c.end
    entering = entering ?? c.transition
  }
  push(cursor, end)

  const videoFrames = pieces.reduce((sum, p) => sum + p.frames, 0)
  const [introOnScreen, introOverlap] = bookendFrames(spec.intro, videoFrames, fps)
  const [outroOnScreen, outroOverlap] = bookendFrames(spec.outro, videoFrames, fps)
  const introFrames = introOnScreen - introOverlap

  const segments: Segment[] = []
  const transitions: CutTransition[] = []
  let frame = introFrames
  for (const p of pieces) {
    const prev = segments[segments.length - 1]
    if (prev && p.transition) {
      // Half on each side of the cut, never more than half of either neighbour.
      const half = Math.floor(Math.min(Math.round(p.transition.duration * fps), prev.frames, p.frames) / 2)
      if (half >= 1) {
        transitions.push({
          type: p.transition.type,
          from: frame - half,
          frames: half * 2,
          outgoing: prev.start + (prev.frames - half) / fps,
          incoming: Math.max(0, p.start - half / fps)
        })
      }
    }
    segments.push({ start: p.start, end: p.end, fromFrame: frame, frames: p.frames })
    frame += p.frames
  }
  const outroStart = frame - outroOverlap
  return {
    introFrames,
    introOnScreen,
    segments,
    transitions,
    videoEnd: frame,
    outroStart,
    hasOutro: outroOnScreen > 0,
    totalFrames: Math.max(1, outroStart + outroOnScreen)
  }
}

/** Source time shown at an output frame, or null during the intro or a finished clip's outro. */
export function sourceTimeAt(tl: Timeline, frame: number, fps: number): number | null {
  if (frame < tl.introFrames || (tl.hasOutro && frame >= tl.videoEnd)) return null
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
