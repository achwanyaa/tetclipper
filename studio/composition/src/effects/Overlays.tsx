// Effects drawn over the video. Camera moves and framing (punch-in, shake,
// digital zoom, vertigo, pull-back, zoom-through, phone, frame-break,
// background) change the video itself — see VideoLayer. Two layers here:
//   behind — between the background and the cut-out speaker (spec.matte)
//   front  — over everything except captions
import { AbsoluteFill, Img, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion'
import { PRESETS } from '../captions/presets'
import type { ClipSpec, Effect } from '../spec'
import { type Timeline, useSourceTime } from '../timeline'
import { Cover, WallText } from './behind'
import { Chart, Checklist, GlassText, HeadlineWall } from './graphics'
import { Doodle, Orbit, PaperText, UiCards } from './styles'

function Overlay({ effect, local, fps }: { effect: Effect; local: number; fps: number }) {
  const p = local / effect.duration
  const fadeOut = interpolate(p, [0.85, 1], [1, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' })
  const pop = spring({ frame: local * fps, fps, config: { damping: 9, stiffness: 180 } })

  switch (effect.type) {
    case 'flash':
      return (
        <AbsoluteFill
          style={{ backgroundColor: '#fff', opacity: interpolate(p, [0, 0.15, 1], [0, 0.9, 0]) }}
        />
      )
    case 'emoji':
      return (
        <div
          style={{
            position: 'absolute',
            left: `${effect.x * 100}%`,
            top: `${effect.y * 100}%`,
            fontSize: effect.size,
            transform: `translate(-50%,-50%) scale(${pop}) rotate(${(1 - pop) * -25}deg)`,
            opacity: fadeOut
          }}
        >
          {effect.emoji}
        </div>
      )
    case 'hook':
      return (
        <div
          style={{
            position: 'absolute',
            top: '9%',
            left: '50%',
            maxWidth: '84%',
            transform: `translateX(-50%) scale(${pop})`,
            opacity: fadeOut,
            background: effect.background,
            color: effect.color,
            fontFamily: PRESETS.hormozi.fontFamily,
            fontSize: 64,
            lineHeight: 1.15,
            textAlign: 'center',
            padding: '22px 34px',
            borderRadius: 20,
            boxShadow: '0 10px 30px rgba(0,0,0,.45)'
          }}
        >
          {effect.text}
        </div>
      )
    case 'image':
      return (
        <AbsoluteFill
          style={{
            opacity: Math.min(1, p * 8) * fadeOut,
            ...(effect.layout === 'top'
              ? { top: 0, height: '45%', bottom: 'auto' }
              : {})
          }}
        >
          <Img src={effect.src} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
        </AbsoluteFill>
      )
    case 'checklist':
      return <Checklist effect={effect} local={local} fps={fps} />
    case 'headline-wall':
      return <HeadlineWall effect={effect} local={local} fps={fps} />
    case 'chart':
      return <Chart effect={effect} local={local} fps={fps} />
    case 'glass-text':
      return <GlassText effect={effect} local={local} fps={fps} />
    case 'ui-cards':
      return <UiCards effect={effect} local={local} fps={fps} />
    case 'paper-text':
      return <PaperText effect={effect} local={local} fps={fps} />
    case 'doodle':
      return <Doodle effect={effect} local={local} fps={fps} />
    default:
      return null
  }
}

/** Pieces of an effect that belong in `layer` (null = none). */
function Piece({ effect, local, fps, layer, matte }: { effect: Effect; local: number; fps: number; layer: 'behind' | 'front'; matte: boolean }) {
  switch (effect.type) {
    case 'wall-text':
      return layer === 'behind' ? <WallText effect={effect} local={local} fps={fps} /> : null
    case 'cover':
      return <Cover effect={effect} local={local} fps={fps} part={layer === 'behind' ? 'masthead' : 'lines'} />
    case 'orbit':
      if (!matte) return layer === 'front' ? <Orbit effect={effect} local={local} fps={fps} half="all" /> : null
      return <Orbit effect={effect} local={local} fps={fps} half={layer === 'behind' ? 'back' : 'front'} />
    default:
      return layer === 'front' ? <Overlay effect={effect} local={local} fps={fps} /> : null
  }
}

export function Overlays({ spec, tl, layer = 'front' }: { spec: ClipSpec; tl: Timeline; layer?: 'behind' | 'front' }) {
  const frame = useCurrentFrame()
  const { fps, durationInFrames } = useVideoConfig()
  const t = useSourceTime(tl)
  if (t === null) return null // intro still is on screen
  const videoFrames = Math.max(1, durationInFrames - tl.introFrames)
  return (
    <AbsoluteFill>
      {spec.effects
        .filter((e) => t >= e.at && t <= e.at + e.duration)
        .map((e, i) => (
          <Piece key={i} effect={e} local={t - e.at} fps={fps} layer={layer} matte={!!spec.matte} />
        ))}
      {layer === 'front' && spec.progressBar.enabled && (
        <div
          style={{
            position: 'absolute',
            left: 0,
            bottom: 0,
            height: 12,
            width: `${((frame - tl.introFrames) / videoFrames) * 100}%`,
            background: spec.progressBar.color
          }}
        />
      )}
    </AbsoluteFill>
  )
}
