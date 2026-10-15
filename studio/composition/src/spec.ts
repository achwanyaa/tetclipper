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
  })
])

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
  words: z.array(wordSchema).default([]),
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
export type Cut = z.infer<typeof cutSchema>
export type ClipSpec = z.infer<typeof clipSpecSchema>
export type ClipSpecInput = z.input<typeof clipSpecSchema>
export type CaptionStyle = (typeof CAPTION_STYLES)[number]

export const FPS = 30
export const WIDTH = 1080
export const HEIGHT = 1920
