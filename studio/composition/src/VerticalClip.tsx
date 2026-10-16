import { useMemo } from 'react'
import { AbsoluteFill, Audio, type CalculateMetadataFunction } from 'remotion'
import { Captions } from './captions/Captions'
import { Overlays } from './effects/Overlays'
import { Intro } from './Intro'
import { musicGains } from './music'
import { FPS, clipSpecSchema, type ClipSpec, type ClipSpecInput } from './spec'
import { buildTimeline } from './timeline'
import { SpeakerLayer, VideoLayer } from './VideoLayer'

export function VerticalClip(props: ClipSpecInput) {
  // Fill defaults so partial specs (from the UI or hand-written JSON) render.
  const spec = useMemo(() => clipSpecSchema.parse(props), [props])
  const tl = useMemo(() => buildTimeline(spec, FPS), [spec])
  const gains = useMemo(() => musicGains(spec, tl, FPS), [spec, tl])
  return (
    <AbsoluteFill style={{ backgroundColor: '#000' }}>
      <VideoLayer spec={spec} tl={tl} />
      <Overlays spec={spec} tl={tl} layer="behind" />
      <SpeakerLayer spec={spec} tl={tl} />
      <Overlays spec={spec} tl={tl} layer="front" />
      <Captions spec={spec} tl={tl} />
      <Intro spec={spec} tl={tl} />
      {spec.music && (
        <Audio
          src={spec.music.src}
          loop={spec.music.loop}
          trimBefore={Math.round(spec.music.offset * FPS)}
          volume={(f) => gains[Math.min(gains.length - 1, Math.max(0, f))] ?? 0}
        />
      )}
    </AbsoluteFill>
  )
}

export const clipDurationInFrames = (spec: ClipSpecInput) =>
  buildTimeline(clipSpecSchema.parse(spec), FPS).totalFrames

export const calculateClipMetadata: CalculateMetadataFunction<ClipSpecInput> = ({ props }) => ({
  durationInFrames: clipDurationInFrames(props),
  fps: FPS
})
