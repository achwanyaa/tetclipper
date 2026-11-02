import { useMemo } from 'react'
import { AbsoluteFill, Audio, type CalculateMetadataFunction } from 'remotion'
import { Captions } from './captions/Captions'
import { Overlays } from './effects/Overlays'
import { Bookends } from './Bookend'
import { musicGains, musicRange } from './music'
import { FPS, clipSpecSchema, type ClipSpec, type ClipSpecInput } from './spec'
import { buildTimeline } from './timeline'
import { CutTransitions, SpeakerLayer, VideoLayer } from './VideoLayer'

export function VerticalClip(props: ClipSpecInput) {
  // Fill defaults so partial specs (from the UI or hand-written JSON) render.
  const spec = useMemo(() => clipSpecSchema.parse(props), [props])
  const tl = useMemo(() => buildTimeline(spec, FPS), [spec])
  const gains = useMemo(() => musicGains(spec, tl, FPS), [spec, tl])
  const range = spec.music ? musicRange(spec.music) : null
  return (
    <AbsoluteFill style={{ backgroundColor: '#000' }}>
      <VideoLayer spec={spec} tl={tl} />
      <CutTransitions spec={spec} tl={tl} />
      <Overlays spec={spec} tl={tl} layer="behind" />
      <SpeakerLayer spec={spec} tl={tl} />
      <Overlays spec={spec} tl={tl} layer="front" />
      <Captions spec={spec} tl={tl} />
      <Bookends spec={spec} tl={tl} />
      {spec.music && range && (
        <Audio
          src={spec.music.src}
          loop={spec.music.loop}
          trimBefore={Math.round(range[0] * FPS)}
          trimAfter={range[1] === null ? undefined : Math.round(range[1] * FPS)}
          loopVolumeCurveBehavior="extend"
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
