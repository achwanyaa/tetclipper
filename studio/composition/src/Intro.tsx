import { AbsoluteFill, Img, Sequence } from 'remotion'
import type { ClipSpec } from './spec'
import type { Timeline } from './timeline'

/** Full-screen still shown before the clip (spec.intro). */
export function Intro({ spec, tl }: { spec: ClipSpec; tl: Timeline }) {
  if (!spec.intro || tl.introFrames < 1) return null
  const { src, fit } = spec.intro
  return (
    <Sequence durationInFrames={tl.introFrames} layout="none">
      <AbsoluteFill style={{ backgroundColor: '#000' }}>
        {fit === 'contain' && (
          // blurred fill behind a letterboxed photo
          <Img src={src} style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover', filter: 'blur(40px) brightness(.6)', transform: 'scale(1.15)' }} />
        )}
        <Img src={src} style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: fit }} />
      </AbsoluteFill>
    </Sequence>
  )
}
