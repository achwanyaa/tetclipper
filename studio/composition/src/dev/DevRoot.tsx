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

// One composition per effect (3 s in, lasting 6 s), for checking how each looks.
const FX: Record<string, NonNullable<ClipSpecInput['effects']>[number]> = {
  checklist: { type: 'checklist', at: 3, duration: 6, title: 'A worthy life', items: ['Humble like a lamb', 'Bold like a lion', 'Obedient to God'] },
  'headline-wall': { type: 'headline-wall', at: 3, duration: 6, look: 'scripture', headlines: ['Behold, the Lion of the tribe of Judah', 'Worthy is the Lamb who was slain', 'He has prevailed to open the scroll'] },
  chart: { type: 'chart', at: 3, duration: 6, title: 'Faith over the years', labels: ['2019', '2021', '2023', '2025'], values: [20, 45, 60, 92], unit: '%' },
  'glass-text': { type: 'glass-text', at: 3, duration: 6, text: 'His power vs. his love', subtitle: 'Revelation 5' },
  'digital-zoom': { type: 'digital-zoom', at: 3, duration: 1.5, amount: 1.4 },
  vertigo: { type: 'vertigo', at: 3, duration: 4, amount: 1.4 },
  'pull-back': { type: 'pull-back', at: 3, duration: 4, from: 2.2, to: 0.8 },
  'zoom-through': { type: 'zoom-through', at: 4, duration: 0.8 },
  phone: { type: 'phone', at: 3, duration: 6, tilt: -6 },
  'ui-cards': { type: 'ui-cards', at: 3, duration: 6, cards: [{ kind: 'verse', title: 'Revelation 5:5', text: 'Weep not: behold, the Lion…' }, { kind: 'like', title: '12.4K likes' }, { kind: 'comment', title: 'Amen 🙏', text: 'This word is for me' }] },
  'paper-text': { type: 'paper-text', at: 3, duration: 6, text: 'Worthy is the Lamb' },
  doodle: { type: 'doodle', at: 3, duration: 6, shape: 'circle', x: 0.5, y: 0.33, size: 420 },
  orbit: { type: 'orbit', at: 3, duration: 6, items: ['🔥', 'LION', '🐑', 'LAMB', '🙏'], x: 0.5, y: 0.32 },
  'wall-text': { type: 'wall-text', at: 3, duration: 6, text: 'Worthy' },
  'frame-break': { type: 'frame-break', at: 3, duration: 6 },
  background: { type: 'background', at: 3, duration: 6, mode: 'color', color: '#13294B' },
  cover: { type: 'cover', at: 3, duration: 6, title: 'WORTHY', issue: 'ISSUE 05', lines: ['Lion in authority', 'Lamb in obedience', 'Why both matter'] }
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
      {Object.entries(FX).map(([name, fx]) => (
        <Composition key={name} id={`Fx-${name}`} {...comp} defaultProps={{ ...base, captions: { enabled: false }, effects: [fx] }} />
      ))}
      {CAPTION_STYLES.map((style) => (
        <Composition key={style} id={`Style-${style}`} {...comp} defaultProps={{ ...base, captions: { style } }} />
      ))}
    </>
  )
}
