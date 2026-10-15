import { useMemo } from 'react'
import { AbsoluteFill, type CalculateMetadataFunction } from 'remotion'
import { Captions } from './captions/Captions'
import { Overlays } from './effects/Overlays'
import { Intro } from './Intro'
import { FPS, clipSpecSchema, type ClipSpec, type ClipSpecInput } from './spec'
import { buildTimeline } from './timeline'
import { VideoLayer } from './VideoLayer'

export function VerticalClip(props: ClipSpecInput) {
  // Fill defaults so partial specs (from the UI or hand-written JSON) render.
  const spec = useMemo(() => clipSpecSchema.parse(props), [props])
  const tl = useMemo(() => buildTimeline(spec, FPS), [spec])
  return (
    <AbsoluteFill style={{ backgroundColor: '#000' }}>
      <VideoLayer spec={spec} tl={tl} />
      <Overlays spec={spec} tl={tl} />
      <Captions spec={spec} tl={tl} />
      <Intro spec={spec} tl={tl} />
    </AbsoluteFill>
  )
}

export const clipDurationInFrames = (spec: ClipSpecInput) =>
  buildTimeline(clipSpecSchema.parse(spec), FPS).totalFrames

export const calculateClipMetadata: CalculateMetadataFunction<ClipSpecInput> = ({ props }) => ({
  durationInFrames: clipDurationInFrames(props),
  fps: FPS
})
