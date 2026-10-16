import type { CSSProperties, ReactNode } from 'react'
import { AbsoluteFill, Easing, Img, OffthreadVideo, Sequence, interpolate, useCurrentFrame, useVideoConfig } from 'remotion'
import { BEHIND_EFFECTS, type ClipSpec, type Effect } from './spec'
import { type Timeline, frameAtSource, sourceTimeAt } from './timeline'

const clamp01 = (v: number) => Math.max(0, Math.min(1, v))
const ease = Easing.inOut(Easing.cubic)

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

/** How the video looks at one moment, from every camera/framing effect. */
export interface Look {
  zoom: number // background and speaker
  bgZoom: number // background only (vertigo): the speaker holds when a matte exists
  dx: number
  dy: number
  blur: number
  glitch: number // 0..1, the digital-zoom hit
  card: { scale: number; rotate: number; radius: number; phone: boolean; backdrop: string | null } | null
  frame: { inset: number; color: string } | null // frame-break: background clipped, speaker free
  background: Extract<Effect, { type: 'background' }> | null
}

/** 0 → 1 → 0 transition at both ends of an effect. */
function ramp(e: Effect, t: number, secs = 0.35) {
  return ease(clamp01(Math.min((t - e.at) / secs, (e.at + e.duration - t) / secs)))
}

export function lookAt(spec: ClipSpec, tl: Timeline, t: number, frame: number, fps: number): Look {
  const look: Look = { zoom: 1, bgZoom: 1, dx: 0, dy: 0, blur: 0, glitch: 0, card: null, frame: null, background: null }
  for (const e of spec.effects) {
    // zoom-through is centred on an output frame (it usually straddles a cut)
    if (e.type === 'zoom-through') {
      const centre = frameAtSource(tl, e.at, fps) ?? tl.segments.find((s) => s.start >= e.at)?.fromFrame
      if (centre === undefined) continue
      const half = Math.max(2, (e.duration * fps) / 2)
      const k = 1 - Math.abs(frame - centre) / half
      if (k <= 0) continue
      look.zoom *= 1 + 2.5 * k * k
      look.blur += 14 * k * k
      continue
    }
    if (t < e.at || t > e.at + e.duration) continue
    const p = (t - e.at) / e.duration
    switch (e.type) {
      case 'punch-in': {
        // fast rise, hold, slower release (tetclipper's director timing shape)
        const env = interpolate(p, [0, 0.12, 0.7, 1], [0, 1, 1, 0], { easing: ease })
        look.zoom *= 1 + (e.amount - 1) * env
        break
      }
      case 'shake': {
        const decay = 1 - p
        look.dx += Math.sin(t * 90) * e.intensity * decay
        look.dy += Math.cos(t * 77) * e.intensity * decay
        break
      }
      case 'digital-zoom': {
        const local = t - e.at
        const env = clamp01(local * 25) * clamp01((e.duration - local) * 12) // snap in, quick out
        look.zoom *= 1 + (e.amount - 1) * env
        if (local < 0.15) {
          look.glitch = Math.max(look.glitch, 1 - local / 0.15)
          look.dx += Math.sin(frame * 3.1) * 22
          look.dy += Math.cos(frame * 2.3) * 14
        }
        break
      }
      case 'vertigo': {
        const env = interpolate(p, [0, 0.85, 1], [0, 1, 0], { easing: ease })
        look.bgZoom *= 1 + (e.amount - 1) * env
        break
      }
      case 'pull-back': {
        look.zoom *= interpolate(p, [0, 0.6, 1], [e.from, 1, 1], { easing: Easing.out(Easing.cubic) })
        if (e.to < 1) {
          const k = interpolate(p, [0.45, 0.75, 0.92, 1], [0, 1, 1, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease })
          look.card = { scale: 1 - (1 - e.to) * k, rotate: 0, radius: 48 * k, phone: false, backdrop: 'blur' }
        }
        break
      }
      case 'phone': {
        const k = ramp(e, t)
        look.card = { scale: 1 - 0.38 * k, rotate: e.tilt * k, radius: 80 * k, phone: k > 0.02, backdrop: e.background }
        break
      }
      case 'frame-break':
        look.frame = { inset: 0.11 * ramp(e, t), color: e.color }
        break
      case 'background':
        look.background = e
        break
    }
  }
  return look
}

/** Absolute style placing the full source frame so the crop window (times
 *  zoom) fills the 9:16 output. */
function placement(spec: ClipSpec, t: number, zoom: number, dx: number, dy: number, W: number, H: number): CSSProperties {
  const crop = cropAt(spec, t)
  const { width: sw, height: sh } = spec.source
  const scale = Math.max(W / sw, H / sh) * crop.zoom * zoom
  const vw = sw * scale
  const vh = sh * scale
  const clamp = (v: number, min: number) => Math.min(0, Math.max(min, v))
  return {
    position: 'absolute',
    left: clamp(W / 2 - crop.x * vw, W - vw) + dx,
    top: clamp(H / 2 - crop.y * vh, H - vh) + dy,
    width: vw,
    height: vh,
    maxWidth: 'none'
  }
}

/** One video file cut to the clip's kept segments (optionally only inside
 *  output-frame `windows`), all sharing one placement style. */
function Track({ src, offset, tl, style, transparent, windows }: {
  src: string
  offset: number // source seconds at which this file's frame 0 sits
  tl: Timeline
  style: CSSProperties
  transparent?: boolean
  windows?: [number, number][]
}) {
  const { fps } = useVideoConfig()
  const pieces: { from: number; frames: number; start: number }[] = []
  for (const s of tl.segments) {
    for (const [a, b] of windows ?? [[s.fromFrame, s.fromFrame + s.frames]]) {
      const from = Math.max(a, s.fromFrame)
      const to = Math.min(b, s.fromFrame + s.frames)
      if (to - from >= 1) pieces.push({ from, frames: to - from, start: s.start + (from - s.fromFrame) / fps })
    }
  }
  return (
    <>
      {pieces.map((piece) => (
        <Sequence key={`${src}-${piece.from}`} from={piece.from} durationInFrames={piece.frames} layout="none">
          <OffthreadVideo
            src={src}
            transparent={transparent}
            muted={transparent}
            trimBefore={Math.max(0, Math.round((piece.start - offset) * fps))}
            style={style}
          />
        </Sequence>
      ))}
    </>
  )
}

/** Card / phone / frame wrapper shared by the background and speaker layers. */
function Framing({ look, children, clipToFrame }: { look: Look; children: ReactNode; clipToFrame: boolean }) {
  const { width: W, height: H } = useVideoConfig()
  let style: CSSProperties = { position: 'absolute', inset: 0, overflow: 'hidden' }
  if (look.card) {
    style = { ...style, transform: `scale(${look.card.scale}) rotate(${look.card.rotate}deg)`, borderRadius: look.card.radius / Math.max(0.3, look.card.scale) }
  }
  if (look.frame && clipToFrame) {
    style = { ...style, clipPath: `inset(${look.frame.inset * H * 0.7}px ${look.frame.inset * W}px round 36px)` }
  }
  if (look.blur > 0.3) style = { ...style, filter: `blur(${look.blur}px)` }
  return <div style={style}>{children}</div>
}

function Glitch({ amount }: { amount: number }) {
  const frame = useCurrentFrame()
  if (amount <= 0) return null
  const bars = [0.18, 0.41, 0.63, 0.82].map((y, i) => ({ y: (y + ((frame * (i + 3)) % 7) / 50) % 1, h: 18 + ((frame * 7 + i * 13) % 40) }))
  return (
    <AbsoluteFill style={{ mixBlendMode: 'screen', opacity: amount }}>
      {bars.map((b, i) => (
        <div
          key={i}
          style={{ position: 'absolute', left: 0, right: 0, top: `${b.y * 100}%`, height: b.h, background: i % 2 ? 'rgba(255,0,80,.45)' : 'rgba(0,220,255,.45)', transform: `translateX(${(i % 2 ? 1 : -1) * 30}px)` }}
        />
      ))}
    </AbsoluteFill>
  )
}

/** Phone body drawn around a card-framed video. */
function PhoneBezel({ look }: { look: Look }) {
  const { width: W, height: H } = useVideoConfig()
  if (!look.card?.phone) return null
  return (
    <AbsoluteFill style={{ justifyContent: 'center', alignItems: 'center', pointerEvents: 'none' }}>
      <div
        style={{ width: W * look.card.scale + 44, height: H * look.card.scale + 44, borderRadius: 96, border: '22px solid #0b0b0d', boxShadow: '0 40px 120px rgba(0,0,0,.6), inset 0 0 0 3px #2a2a2e', transform: `rotate(${look.card.rotate}deg)`, position: 'relative' }}
      >
        <div style={{ position: 'absolute', top: 18, left: '50%', width: 210, height: 54, marginLeft: -105, borderRadius: 30, background: '#0b0b0d' }} />
      </div>
    </AbsoluteFill>
  )
}

/** What shows around a shrunken card: a blurred copy of the video or a colour. */
function Backdrop({ spec, look, tl, style }: { spec: ClipSpec; look: Look; tl: Timeline; style: CSSProperties }) {
  const backdrop = look.card?.backdrop ?? (look.frame && look.frame.inset > 0 ? 'blur' : null)
  if (!backdrop) return null
  if (backdrop !== 'blur') return <AbsoluteFill style={{ background: backdrop }} />
  return (
    <AbsoluteFill style={{ filter: 'blur(40px) brightness(.55)', transform: 'scale(1.1)' }}>
      <Track src={spec.source.src} offset={0} tl={tl} style={style} />
    </AbsoluteFill>
  )
}

/** Output frame ranges where a behind-the-speaker effect is active. */
export function behindWindows(spec: ClipSpec, tl: Timeline, fps: number): [number, number][] {
  const behind = new Set<string>(BEHIND_EFFECTS)
  const ranges: [number, number][] = []
  for (const e of spec.effects) {
    if (!behind.has(e.type)) continue
    let a: number | null = null
    let b: number | null = null
    for (const s of tl.segments) {
      const lo = Math.max(e.at, s.start)
      const hi = Math.min(e.at + e.duration, s.end)
      if (hi <= lo) continue
      const fa = s.fromFrame + Math.floor((lo - s.start) * fps)
      const fb = s.fromFrame + Math.ceil((hi - s.start) * fps)
      a = a === null ? fa : Math.min(a, fa)
      b = b === null ? fb : Math.max(b, fb)
    }
    if (a !== null && b !== null) ranges.push([a, b])
  }
  ranges.sort((x, y) => x[0] - y[0])
  const merged: [number, number][] = []
  for (const r of ranges) {
    const last = merged[merged.length - 1]
    if (last && r[0] <= last[1]) last[1] = Math.max(last[1], r[1])
    else merged.push([r[0], r[1]])
  }
  return merged
}

/** Background layer: the source video (or its replacement) with every camera
 *  move and framing applied. */
export function VideoLayer({ spec, tl }: { spec: ClipSpec; tl: Timeline }) {
  const frame = useCurrentFrame()
  const { fps, width: W, height: H } = useVideoConfig()
  const t = sourceTimeAt(tl, frame, fps) ?? spec.source.start
  const look = lookAt(spec, tl, t, frame, fps)
  const bgStyle = placement(spec, t, look.zoom * look.bgZoom, look.dx, look.dy, W, H)
  const plain = placement(spec, t, 1, 0, 0, W, H)
  const bg = spec.matte ? look.background : null // replacing the background needs the speaker cut out
  return (
    <AbsoluteFill style={{ backgroundColor: '#000', overflow: 'hidden' }}>
      <Backdrop spec={spec} look={look} tl={tl} style={plain} />
      <Framing look={look} clipToFrame>
        {bg && bg.mode === 'color' ? (
          <AbsoluteFill style={{ background: bg.color }} />
        ) : bg && bg.mode === 'image' && bg.src ? (
          <Img src={bg.src} style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover' }} />
        ) : (
          <div style={bg ? { position: 'absolute', inset: 0, filter: 'blur(36px) brightness(.7)', transform: 'scale(1.1)' } : { position: 'absolute', inset: 0 }}>
            <Track src={spec.source.src} offset={0} tl={tl} style={bgStyle} />
          </div>
        )}
      </Framing>
      {look.frame && look.frame.inset > 0.005 && (
        <div
          style={{ position: 'absolute', left: look.frame.inset * W, right: look.frame.inset * W, top: look.frame.inset * H * 0.7, bottom: look.frame.inset * H * 0.7, border: `14px solid ${look.frame.color}`, borderRadius: 36, pointerEvents: 'none' }}
        />
      )}
      <PhoneBezel look={look} />
      <Glitch amount={look.glitch} />
    </AbsoluteFill>
  )
}

/** The cut-out speaker (spec.matte) drawn over behind-the-speaker effects with
 *  the background's placement (minus vertigo), only while one is active. */
export function SpeakerLayer({ spec, tl }: { spec: ClipSpec; tl: Timeline }) {
  const frame = useCurrentFrame()
  const { fps, width: W, height: H } = useVideoConfig()
  if (!spec.matte) return null
  const windows = behindWindows(spec, tl, fps)
  if (!windows.length) return null
  const t = sourceTimeAt(tl, frame, fps) ?? spec.source.start
  const look = lookAt(spec, tl, t, frame, fps)
  const style = placement(spec, t, look.zoom, look.dx, look.dy, W, H)
  return (
    <AbsoluteFill style={{ pointerEvents: 'none' }}>
      <Framing look={look} clipToFrame={false}>
        <Track src={spec.matte.src} offset={spec.matte.start} tl={tl} style={style} transparent windows={windows} />
      </Framing>
    </AbsoluteFill>
  )
}
