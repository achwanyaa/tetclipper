import { Composition, staticFile } from 'remotion'
import sample from '../../public/fixtures/sample.json'
import { CAPTION_STYLES, FPS, HEIGHT, WIDTH, clipSpecSchema, type ClipSpecInput } from '../spec'
import { VerticalClip, calculateClipMetadata } from '../VerticalClip'

// Dev compositions on the local fixture (scripts/make-fixture.mjs, gitignored):
// Remotion Studio (`npm run studio`) and the style gallery stills.
const base: ClipSpecInput = {
  source: { src: staticFile('fixtures/sample.mp4'), start: 0, end: sample.duration },
  words: sample.words,
  captions: { style: 'hormozi' },
  progressBar: { enabled: true },
  effects: [
    { type: 'punch-in', at: 4, duration: 2, amount: 1.12 },
    { type: 'emoji', at: 8, duration: 1.6, emoji: '🔥' }
  ]
}

const withIntro: ClipSpecInput = {
  ...base,
  intro: { src: staticFile('fixtures/intro.jpg'), duration: 2 },
  cuts: [{ start: 6, end: 7.5 }],
  effects: [...(base.effects ?? []), { type: 'hook', at: 0, duration: 3, text: 'His power vs. his love' }]
}

const comp = {
  component: VerticalClip,
  schema: clipSpecSchema,
  calculateMetadata: calculateClipMetadata,
  durationInFrames: FPS * 30,
  fps: FPS,
  width: WIDTH,
  height: HEIGHT
}

export function DevRoot() {
  return (
    <>
      <Composition id="VerticalClip" {...comp} defaultProps={base} />
      <Composition id="WithIntro" {...comp} defaultProps={withIntro} />
      {/* one composition per caption style, for the gallery stills */}
      {CAPTION_STYLES.map((style) => (
        <Composition key={style} id={`Style-${style}`} {...comp} defaultProps={{ ...base, captions: { style } }} />
      ))}
    </>
  )
}
