import { AbsoluteFill, Img, OffthreadVideo, Sequence, useCurrentFrame, useVideoConfig } from 'remotion'
import type { Bookend as BookendSpec, ClipSpec } from './spec'
import type { Timeline } from './timeline'
import { transitionLook } from './transitions'

const FILL = { position: 'absolute', inset: 0, width: '100%', height: '100%' } as const
const BLURRED = { ...FILL, objectFit: 'cover', filter: 'blur(40px) brightness(.6)', transform: 'scale(1.15)' } as const

/** The intro or outro picture: a still or a video, optionally letterboxed over a
 *  blurred copy of itself. `gain` is the video's own sound at a local frame. */
function Media({ item, gain }: { item: BookendSpec; gain: (frame: number) => number }) {
  const main = { ...FILL, objectFit: item.fit } as const
  if (item.kind === 'video') {
    return (
      <>
        {item.fit === 'contain' && <OffthreadVideo src={item.src} muted style={BLURRED} />}
        <OffthreadVideo src={item.src} muted={item.volume <= 0} volume={gain} pauseWhenBuffering style={main} />
      </>
    )
  }
  return (
    <>
      {item.fit === 'contain' && <Img src={item.src} style={BLURRED} />}
      <Img src={item.src} style={main} />
    </>
  )
}

function Layer({ item, overlapFrom, overlap, frames, entering }: { item: BookendSpec; overlapFrom: number; overlap: number; frames: number; entering: boolean }) {
  const frame = useCurrentFrame()
  const inWindow = overlap > 0 && item.transition !== null && frame >= overlapFrom && frame < overlapFrom + overlap
  const look = inWindow && item.transition ? transitionLook(item.transition.type, (frame - overlapFrom + 0.5) / overlap, entering) : null
  // The sound crossfades with the speech across the overlap.
  const gain = (f: number) => {
    if (overlap <= 0) return item.volume
    const k = entering ? (f + 1) / overlap : (frames - f) / overlap
    return item.volume * Math.max(0, Math.min(1, k))
  }
  return (
    <AbsoluteFill style={{ overflow: 'hidden' }}>
      <AbsoluteFill style={{ backgroundColor: '#000', ...look?.style }}>
        <Media item={item} gain={gain} />
      </AbsoluteFill>
      {look?.cover && <AbsoluteFill style={look.cover} />}
    </AbsoluteFill>
  )
}

/** Full-screen intro and outro, above everything else. Each overlaps the clip
 *  by its transition's length, so the animation has video to reveal or cover. */
export function Bookends({ spec, tl }: { spec: ClipSpec; tl: Timeline }) {
  const { fps } = useVideoConfig()
  const outroFrames = tl.totalFrames - tl.outroStart
  return (
    <>
      {spec.intro && tl.introOnScreen > 0 && (
        <Sequence durationInFrames={tl.introOnScreen} premountFor={fps}>
          <Layer item={spec.intro} overlapFrom={tl.introFrames} overlap={tl.introOnScreen - tl.introFrames} frames={tl.introOnScreen} entering={false} />
        </Sequence>
      )}
      {spec.outro && outroFrames > 0 && (
        <Sequence from={tl.outroStart} durationInFrames={outroFrames} premountFor={fps}>
          <Layer item={spec.outro} overlapFrom={0} overlap={tl.videoEnd - tl.outroStart} frames={outroFrames} entering />
        </Sequence>
      )}
    </>
  )
}
