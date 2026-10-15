import { AbsoluteFill, Easing, OffthreadVideo, Sequence, interpolate, useVideoConfig } from 'remotion'
import type { ClipSpec } from './spec'
import { type Timeline, useSourceTime } from './timeline'

/** Crop centre/zoom at source time t. Keyframes interpolate linearly (the
 *  pipeline's camera path is already smoothed and simplified to keyframes)
 *  unless the next keyframe is marked `cut`: then the previous one holds and jumps. */
export function cropAt(spec: ClipSpec, t: number) {
  const kfs = spec.crop.keyframes
  if (kfs.length === 0) return { x: 0.5, y: 0.5, zoom: 1 }
  if (t <= kfs[0].t) return kfs[0]
  for (let i = 1; i < kfs.length; i++) {
    const a = kfs[i - 1]
    const b = kfs[i]
    if (t >= b.t) continue
    if (b.cut || b.t <= a.t) return a
    const p = (t - a.t) / (b.t - a.t)
    return { x: a.x + (b.x - a.x) * p, y: a.y + (b.y - a.y) * p, zoom: a.zoom + (b.zoom - a.zoom) * p }
  }
  return kfs[kfs.length - 1]
}

/** Zoom multiplier and pixel shake from punch-in / shake effects at time t. */
function motionAt(spec: ClipSpec, t: number) {
  let zoom = 1
  let dx = 0
  let dy = 0
  for (const e of spec.effects) {
    if (t < e.at || t > e.at + e.duration) continue
    const p = (t - e.at) / e.duration
    if (e.type === 'punch-in') {
      // fast rise, hold, slower release (tetclipper's director timing shape)
      const env = interpolate(p, [0, 0.12, 0.7, 1], [0, 1, 1, 0], { easing: Easing.inOut(Easing.cubic) })
      zoom *= 1 + (e.amount - 1) * env
    } else if (e.type === 'shake') {
      const decay = 1 - p
      dx += Math.sin(t * 90) * e.intensity * decay
      dy += Math.cos(t * 77) * e.intensity * decay
    }
  }
  return { zoom, dx, dy }
}

/** Style that places the full source frame so the crop window fills the 9:16
 *  output. Computed from the global frame, outside the per-segment Sequences. */
function useFramedStyle(spec: ClipSpec, tl: Timeline) {
  const { width: W, height: H } = useVideoConfig()
  const t = useSourceTime(tl) ?? spec.source.start
  const crop = cropAt(spec, t)
  const motion = motionAt(spec, t)
  const { width: sw, height: sh } = spec.source
  const scale = Math.max(W / sw, H / sh) * crop.zoom * motion.zoom
  const vw = sw * scale
  const vh = sh * scale
  const clamp = (v: number, min: number) => Math.min(0, Math.max(min, v))
  return {
    position: 'absolute' as const,
    left: clamp(W / 2 - crop.x * vw, W - vw) + motion.dx,
    top: clamp(H / 2 - crop.y * vh, H - vh) + motion.dy,
    width: vw,
    height: vh,
    maxWidth: 'none'
  }
}

export function VideoLayer({ spec, tl }: { spec: ClipSpec; tl: Timeline }) {
  const { fps } = useVideoConfig()
  const style = useFramedStyle(spec, tl)
  return (
    <AbsoluteFill style={{ backgroundColor: '#000', overflow: 'hidden' }}>
      {tl.segments.map((s) => (
        <Sequence key={`${s.start}-${s.fromFrame}`} from={s.fromFrame} durationInFrames={s.frames} layout="none">
          <OffthreadVideo src={spec.source.src} trimBefore={Math.round(s.start * fps)} style={style} />
        </Sequence>
      ))}
    </AbsoluteFill>
  )
}
