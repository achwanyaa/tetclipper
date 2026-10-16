// The clip spec: one declarative JSON document per clip (jobs/<id>/clips/<n>/spec.json).
// The pipeline writes the first version, the editor UI and Claude Code edit it,
// the Remotion Player previews it live and renderMedia renders it.
//
// Every time is in SOURCE seconds — the position in the downloaded media file —
// so a spec stays valid when the range is widened, narrowed or cut.
// The output timeline is: [intro still] + (source.start..source.end minus cuts).
import { z } from 'zod'

export const SPEC_VERSION = 1

export const CAPTION_STYLES = [
  'classic',
  'beast',
  'hormozi',
  'minimal',
  'karaoke-pop',
  'sermon',
  'one-word',
  'boxed',
  'neon'
] as const

const seconds = z.number().min(0)
const fraction = z.number().min(0).max(1)

export const wordSchema = z.object({
  text: z.string(),
  start: seconds,
  end: seconds,
  emphasis: z.boolean().optional(), // loud / power word — styled with the emphasis colour
  hidden: z.boolean().optional(), // removed from captions (audio is untouched)
  speaker: z.string().optional()
})

export const cropKeyframeSchema = z.object({
  t: seconds,
  x: fraction, // horizontal centre of the crop, fraction of source width
  y: fraction.default(0.5),
  zoom: z.number().min(1).max(4).default(1),
  cut: z.boolean().optional() // jump here instead of easing from the previous keyframe
})

const effectBase = { at: seconds, duration: z.number().positive() }

export const effectSchema = z.discriminatedUnion('type', [
  // Smooth zoom-in on the video, eased in and back out.
  z.object({ type: z.literal('punch-in'), ...effectBase, amount: z.number().min(1).max(2).default(1.12) }),
  // Short camera shake.
  z.object({ type: z.literal('shake'), ...effectBase, intensity: z.number().default(12) }),
  // White flash (cut/transition accent).
  z.object({ type: z.literal('flash'), ...effectBase }),
  // Emoji or short sticker that pops in.
  z.object({
    type: z.literal('emoji'),
    ...effectBase,
    emoji: z.string(),
    x: fraction.default(0.5),
    y: fraction.default(0.3),
    size: z.number().default(180)
  }),
  // Title card near the top ("hook").
  z.object({
    type: z.literal('hook'),
    ...effectBase,
    text: z.string(),
    background: z.string().default('#FFD700'),
    color: z.string().default('#000000')
  }),
  // Image overlay (b-roll): full frame or the top part of the frame.
  z.object({
    type: z.literal('image'),
    ...effectBase,
    src: z.string(),
    layout: z.enum(['full', 'top']).default('top')
  }),

  // ---- graphics ----
  // Points tick in one by one (at `ticks`, source seconds; spread evenly if omitted).
  z.object({
    type: z.literal('checklist'),
    ...effectBase,
    title: z.string().optional(),
    items: z.array(z.string()).min(1).max(8),
    ticks: z.array(seconds).optional(),
    y: fraction.default(0.32),
    accent: z.string().default('#22C55E')
  }),
  // A wall of headlines / quotes stacking up.
  z.object({
    type: z.literal('headline-wall'),
    ...effectBase,
    headlines: z.array(z.string()).min(1).max(12),
    look: z.enum(['news', 'scripture']).default('news')
  }),
  // Animated bar or line chart.
  z.object({
    type: z.literal('chart'),
    ...effectBase,
    kind: z.enum(['bar', 'line']).default('bar'),
    title: z.string().optional(),
    labels: z.array(z.string()).min(1).max(10),
    values: z.array(z.number()).min(1).max(10),
    unit: z.string().optional(),
    color: z.string().default('#F5B83D'),
    y: fraction.default(0.3)
  }),
  // Frosted-glass text card.
  z.object({
    type: z.literal('glass-text'),
    ...effectBase,
    text: z.string(),
    subtitle: z.string().optional(),
    y: fraction.default(0.28)
  }),

  // ---- camera moves (change the video layer) ----
  // Hard punchy zoom with a glitch hit.
  z.object({ type: z.literal('digital-zoom'), ...effectBase, amount: z.number().min(1).max(3).default(1.35) }),
  // Dolly zoom: background stretches while the speaker holds (true effect with a matte).
  z.object({ type: z.literal('vertigo'), ...effectBase, amount: z.number().min(1).max(2).default(1.3) }),
  // Starts tight, pulls back; `to` < 1 ends on a framed card over a blurred backdrop.
  z.object({
    type: z.literal('pull-back'),
    ...effectBase,
    from: z.number().min(1).max(4).default(2),
    to: z.number().min(0.5).max(1).default(1)
  }),
  // Transition: zoom fast into the frame and out the other side, centred on `at`
  // (put `at` on a cut: the start of the part that follows it).
  z.object({ type: z.literal('zoom-through'), ...effectBase }),

  // ---- frames & styles ----
  // The video shrinks into a phone screen.
  z.object({
    type: z.literal('phone'),
    ...effectBase,
    tilt: z.number().min(-20).max(20).default(-6),
    background: z.string().default('#111111')
  }),
  // App-style cards float in 3D.
  z.object({
    type: z.literal('ui-cards'),
    ...effectBase,
    cards: z
      .array(
        z.object({
          kind: z.enum(['notification', 'like', 'comment', 'verse']).default('notification'),
          title: z.string(),
          text: z.string().optional()
        })
      )
      .min(1)
      .max(5)
  }),
  // Cut-out paper strips with stop-motion text.
  z.object({
    type: z.literal('paper-text'),
    ...effectBase,
    text: z.string(),
    color: z.string().default('#FFF6DC'),
    y: fraction.default(0.25)
  }),
  // Hand-drawn doodle that draws on and wiggles ("boil").
  z.object({
    type: z.literal('doodle'),
    ...effectBase,
    shape: z.enum(['arrow', 'circle', 'underline', 'star', 'heart', 'sparkle']).default('circle'),
    x: fraction.default(0.5),
    y: fraction.default(0.4),
    size: z.number().min(40).max(1000).default(320),
    rotation: z.number().default(0),
    color: z.string().default('#FFE500')
  }),
  // Words or emoji circling the speaker's head (passing behind them with a matte).
  z.object({
    type: z.literal('orbit'),
    ...effectBase,
    items: z.array(z.string()).min(1).max(8),
    x: fraction.default(0.5),
    y: fraction.default(0.3),
    radius: z.number().min(100).max(700).default(360)
  }),

  // ---- behind the speaker (need spec.matte; without it they draw in front) ----
  // Big text on the wall behind the speaker.
  z.object({
    type: z.literal('wall-text'),
    ...effectBase,
    text: z.string(),
    color: z.string().default('#FFFFFF'),
    y: fraction.default(0.3)
  }),
  // The video sits in a frame and the speaker steps out over its edge.
  z.object({ type: z.literal('frame-break'), ...effectBase, color: z.string().default('#F5B83D') }),
  // Replace the background behind the speaker.
  z.object({
    type: z.literal('background'),
    ...effectBase,
    mode: z.enum(['blur', 'color', 'image']).default('blur'),
    color: z.string().default('#0E1A2B'),
    src: z.string().optional()
  }),
  // Magazine cover: masthead behind the speaker's head, cover lines in front.
  z.object({
    type: z.literal('cover'),
    ...effectBase,
    title: z.string(),
    lines: z.array(z.string()).max(5).default([]),
    issue: z.string().optional(),
    color: z.string().default('#E11D48')
  })
])

/** Effect types that move or reframe the video layer itself. */
export const CAMERA_EFFECTS = ['punch-in', 'shake', 'digital-zoom', 'vertigo', 'pull-back', 'zoom-through', 'phone', 'frame-break', 'background'] as const
/** Effect types drawn between the background and the cut-out speaker. */
export const BEHIND_EFFECTS = ['wall-text', 'cover', 'orbit', 'frame-break', 'background', 'vertigo'] as const

export const cutSchema = z.object({ start: seconds, end: seconds })

export const clipSpecSchema = z.object({
  version: z.literal(SPEC_VERSION).default(SPEC_VERSION),
  title: z.string().optional(),
  source: z.object({
    src: z.string(), // URL the Player/renderer can load the media from
    start: seconds,
    end: seconds,
    width: z.number().int().positive().default(1920),
    height: z.number().int().positive().default(1080)
  }),
  // Full-screen still shown before the clip starts.
  intro: z
    .object({
      src: z.string(),
      duration: z.number().min(0.5).max(5).default(2),
      fit: z.enum(['cover', 'contain']).default('cover')
    })
    .nullable()
    .default(null),
  cuts: z.array(cutSchema).default([]),
  // Music bed under the whole output (intro included). Ducks while anyone speaks.
  music: z
    .object({
      src: z.string(),
      volume: fraction.default(0.25),
      duck: fraction.default(0.35), // multiplier on `volume` while speech plays
      offset: seconds.default(0), // start this far into the track
      fadeIn: z.number().min(0).max(10).default(1),
      fadeOut: z.number().min(0).max(10).default(1.5),
      loop: z.boolean().default(true)
    })
    .nullable()
    .default(null),
  words: z.array(wordSchema).default([]),
  // Speaker cut out from the background (transparent video, same geometry and
  // timing as the source from `start`): lets effects sit behind the speaker.
  matte: z
    .object({ src: z.string(), start: seconds.default(0) })
    .nullable()
    .default(null),
  // Caption spans worth checking by ear (the composition ignores these). `alt`
  // is what a Swahili-forced second listen heard; from/to index `words`.
  doubts: z
    .array(
      z.object({
        from: z.number().int().min(0),
        to: z.number().int().min(0),
        reason: z.string(),
        alt: z.string().optional()
      })
    )
    .default([]),
  captions: z
    .object({
      enabled: z.boolean().default(true),
      style: z.enum(CAPTION_STYLES).default('hormozi'),
      position: fraction.optional(), // vertical centre, fraction of frame height (style default if unset)
      maxWords: z.number().int().min(1).max(8).optional(),
      size: z.number().positive().optional(), // px override
      color: z.string().optional(),
      activeColor: z.string().optional(),
      emphasisColor: z.string().optional(),
      uppercase: z.boolean().optional(),
      emoji: z.boolean().optional() // auto emoji on key words (style default if unset)
    })
    .default({}),
  crop: z
    .object({
      keyframes: z.array(cropKeyframeSchema).default([]) // empty = centre crop
    })
    .default({}),
  effects: z.array(effectSchema).default([]),
  progressBar: z
    .object({
      enabled: z.boolean().default(false),
      color: z.string().default('#FFD700')
    })
    .default({})
})

export type Word = z.infer<typeof wordSchema>
export type CropKeyframe = z.infer<typeof cropKeyframeSchema>
export type Effect = z.infer<typeof effectSchema>
export type EffectInput = z.input<typeof effectSchema>
export type Cut = z.infer<typeof cutSchema>
export type Doubt = z.infer<typeof clipSpecSchema>['doubts'][number]
export type Music = NonNullable<z.infer<typeof clipSpecSchema>['music']>
export type ClipSpec = z.infer<typeof clipSpecSchema>
export type ClipSpecInput = z.input<typeof clipSpecSchema>
export type CaptionStyle = (typeof CAPTION_STYLES)[number]

export const FPS = 30
export const WIDTH = 1080
export const HEIGHT = 1920
