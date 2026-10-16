// Frames & styles drawn over the video: UI cards, paper cut text, doodles, orbit.
import { AbsoluteFill, interpolate, random, spring } from 'remotion'
import { loadFont as loadInter } from '@remotion/google-fonts/Inter'
import { loadFont as loadPermanent } from '@remotion/google-fonts/PermanentMarker'
import type { FxProps } from './graphics'

const inter = loadInter('normal', { weights: ['600', '800'], subsets: ['latin'] }).fontFamily
const marker = loadPermanent('normal', { subsets: ['latin'] }).fontFamily

const fade = (local: number, duration: number, secs = 0.3) =>
  interpolate(Math.min(local, duration - local), [0, secs], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' })

const CARD_ICON = { notification: '🔔', like: '❤️', comment: '💬', verse: '📖' } as const

export function UiCards({ effect, local, fps }: FxProps<'ui-cards'>) {
  return (
    <AbsoluteFill style={{ perspective: 1400, opacity: fade(local, effect.duration) }}>
      {effect.cards.map((card, i) => {
        const s = spring({ frame: (local - i * 0.35) * fps, fps, config: { damping: 13 } })
        const side = i % 2 ? 1 : -1
        const drift = Math.sin((local + i) * 1.3) * 14
        return (
          <div
            key={i}
            style={{ position: 'absolute', top: `${14 + i * 15}%`, left: side < 0 ? '6%' : undefined, right: side > 0 ? '6%' : undefined, width: '66%', transform: `translateY(${drift}px) rotateY(${side * 18 * (1 - 0.4 * s)}deg) rotateX(6deg) translateZ(${s * 60}px) scale(${s})`, opacity: s, background: card.kind === 'verse' ? 'rgba(250,244,230,.96)' : 'rgba(255,255,255,.95)', color: '#111', borderRadius: 34, padding: '26px 30px', boxShadow: '0 30px 80px rgba(0,0,0,.4)', fontFamily: inter, display: 'flex', gap: 22, alignItems: 'center' }}
          >
            <div style={{ fontSize: 56 }}>{CARD_ICON[card.kind]}</div>
            <div>
              <div style={{ fontSize: 36, fontWeight: 800 }}>{card.title}</div>
              {card.text && <div style={{ fontSize: 30, fontWeight: 600, color: '#555', marginTop: 4 }}>{card.text}</div>}
            </div>
          </div>
        )
      })}
    </AbsoluteFill>
  )
}

export function PaperText({ effect, local, fps }: FxProps<'paper-text'>) {
  const step = Math.floor(local * 8) // stop-motion: 8 poses a second
  const words = effect.text.split(/\s+/)
  return (
    <AbsoluteFill style={{ opacity: fade(local, effect.duration, 0.15) }}>
      <svg width="0" height="0" style={{ position: 'absolute' }}>
        <filter id="paper-grain">
          <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed={3} />
          <feColorMatrix values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 0.08 0" />
          <feComposite in2="SourceGraphic" operator="in" />
          <feBlend in="SourceGraphic" mode="multiply" />
        </filter>
      </svg>
      <div style={{ position: 'absolute', left: '6%', right: '6%', top: `${effect.y * 100}%`, display: 'flex', flexWrap: 'wrap', justifyContent: 'center', gap: 18 }}>
        {words.map((w, i) => {
          const appear = local >= i * 0.18
          const r = (random(`${i}-${step}`) - 0.5) * 6
          const y = (random(`y${i}-${step}`) - 0.5) * 8
          return (
            <span
              key={i}
              style={{ visibility: appear ? 'visible' : 'hidden', display: 'inline-block', background: effect.color, color: '#1b1b1b', fontFamily: marker, fontSize: 82, padding: '6px 22px 2px', transform: `rotate(${r}deg) translateY(${y}px)`, clipPath: 'polygon(2% 6%, 98% 0, 100% 92%, 4% 100%)', boxShadow: '6px 8px 0 rgba(0,0,0,.35)', filter: 'url(#paper-grain)' }}
            >
              {w}
            </span>
          )
        })}
      </div>
    </AbsoluteFill>
  )
}

const DOODLES: Record<string, string> = {
  arrow: 'M10,70 C40,60 70,50 90,30 M90,30 L72,30 M90,30 L86,48',
  circle: 'M50,8 C78,6 94,30 92,52 C90,78 64,94 42,90 C16,86 4,62 8,40 C12,20 30,9 54,10',
  underline: 'M5,60 C30,52 60,66 95,54 M12,72 C40,66 70,76 90,68',
  star: 'M50,6 L61,38 L95,38 L67,58 L78,92 L50,71 L22,92 L33,58 L5,38 L39,38 Z',
  heart: 'M50,88 C20,66 4,48 10,28 C16,10 40,8 50,28 C60,8 84,10 90,28 C96,48 80,66 50,88 Z',
  sparkle: 'M50,8 L56,44 L92,50 L56,56 L50,92 L44,56 L8,50 L44,44 Z'
}

export function Doodle({ effect, local, fps }: FxProps<'doodle'>) {
  const boil = Math.floor(local * 12) // redraw jitter 12×/s
  const draw = interpolate(local, [0, 0.5], [0, 1], { extrapolateRight: 'clamp' })
  const id = `boil-${boil % 3}`
  return (
    <AbsoluteFill style={{ opacity: fade(local, effect.duration, 0.2) }}>
      <svg
        viewBox="0 0 100 100"
        width={effect.size}
        height={effect.size}
        style={{ position: 'absolute', left: `${effect.x * 100}%`, top: `${effect.y * 100}%`, transform: `translate(-50%,-50%) rotate(${effect.rotation}deg)`, overflow: 'visible' }}
      >
        <filter id={id}>
          <feTurbulence type="turbulence" baseFrequency="0.04" numOctaves="2" seed={boil % 3} />
          <feDisplacementMap in="SourceGraphic" scale="3" />
        </filter>
        <path
          d={DOODLES[effect.shape]}
          fill="none"
          stroke={effect.color}
          strokeWidth={5}
          strokeLinecap="round"
          strokeLinejoin="round"
          pathLength={1}
          strokeDasharray={1}
          strokeDashoffset={1 - draw}
          filter={`url(#${id})`}
          style={{ filter: 'drop-shadow(0 3px 4px rgba(0,0,0,.45))' }}
        />
      </svg>
    </AbsoluteFill>
  )
}

/** Orbit items; `half` picks the back (behind the speaker) or front arc. */
export function Orbit({ effect, local, fps, half }: FxProps<'orbit'> & { half: 'back' | 'front' | 'all' }) {
  const n = effect.items.length
  const spin = local * 1.1
  const grow = spring({ frame: local * fps, fps, config: { damping: 14 } })
  return (
    <AbsoluteFill style={{ opacity: fade(local, effect.duration) }}>
      {effect.items.map((item, i) => {
        const a = spin + (i / n) * Math.PI * 2
        const depth = Math.sin(a) // > 0 = front
        if (half === 'back' && depth > 0) return null
        if (half === 'front' && depth <= 0) return null
        const x = Math.cos(a) * effect.radius * grow
        const y = depth * effect.radius * 0.28
        const scale = 0.75 + 0.35 * (depth + 1) / 2
        const emoji = /\p{Extended_Pictographic}/u.test(item) && item.length <= 4
        return (
          <div
            key={i}
            style={{ position: 'absolute', left: `${effect.x * 100}%`, top: `${effect.y * 100}%`, transform: `translate(-50%,-50%) translate(${x}px, ${y}px) scale(${scale})`, opacity: 0.55 + 0.45 * (depth + 1) / 2, fontFamily: inter, fontWeight: 800, fontSize: emoji ? 110 : 56, color: '#fff', textShadow: '0 4px 18px rgba(0,0,0,.6)', whiteSpace: 'nowrap' }}
          >
            {item}
          </div>
        )
      })}
    </AbsoluteFill>
  )
}
