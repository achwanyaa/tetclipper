// Effects drawn on top of the video: flash, emoji, hook card, image, progress bar.
// (punch-in and shake move the video itself — see VideoLayer.)
import { AbsoluteFill, Img, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion'
import { PRESETS } from '../captions/presets'
import type { ClipSpec, Effect } from '../spec'
import { type Timeline, useSourceTime } from '../timeline'

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
    default:
      return null
  }
}

export function Overlays({ spec, tl }: { spec: ClipSpec; tl: Timeline }) {
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
          <Overlay key={i} effect={e} local={t - e.at} fps={fps} />
        ))}
      {spec.progressBar.enabled && (
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
