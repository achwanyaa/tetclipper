import { Composition } from 'remotion'
import { FPS, HEIGHT, WIDTH, clipSpecSchema, type ClipSpecInput } from './spec'
import { VerticalClip, calculateClipMetadata } from './VerticalClip'

// Production root: one composition, every prop supplied by the caller
// (scripts/render.mjs passes the clip's spec as inputProps).
const placeholder: ClipSpecInput = { source: { src: '', start: 0, end: 1 } }

export function Root() {
  return (
    <Composition
      id="VerticalClip"
      component={VerticalClip}
      schema={clipSpecSchema}
      defaultProps={placeholder}
      calculateMetadata={calculateClipMetadata}
      durationInFrames={FPS}
      fps={FPS}
      width={WIDTH}
      height={HEIGHT}
    />
  )
}
