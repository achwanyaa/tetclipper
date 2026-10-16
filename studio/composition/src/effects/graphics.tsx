// Information graphics: checklist, headline wall, chart, glass text.
import { AbsoluteFill, interpolate, spring } from 'remotion'
import { loadFont as loadInter } from '@remotion/google-fonts/Inter'
import { loadFont as loadPlayfair } from '@remotion/google-fonts/PlayfairDisplay'
import type { Effect } from '../spec'

const inter = loadInter('normal', { weights: ['600', '800'], subsets: ['latin'] }).fontFamily
const playfair = loadPlayfair('normal', { weights: ['700'], subsets: ['latin'] }).fontFamily

type Of<T extends Effect['type']> = Extract<Effect, { type: T }>
export interface FxProps<T extends Effect['type']> {
  effect: Of<T>
  local: number // seconds since the effect started
  fps: number
}

const fade = (local: number, duration: number, secs = 0.3) =>
  interpolate(Math.min(local, duration - local), [0, secs], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' })

export function Checklist({ effect, local, fps }: FxProps<'checklist'>) {
  const n = effect.items.length
  const ticks = effect.ticks?.length === n ? effect.ticks.map((t) => t - effect.at) : effect.items.map((_, i) => 0.4 + (i * (effect.duration - 0.8)) / n)
  const enter = spring({ frame: local * fps, fps, config: { damping: 16 } })
  return (
    <AbsoluteFill style={{ opacity: fade(local, effect.duration) }}>
      <div
        style={{ position: 'absolute', left: '8%', right: '8%', top: `${effect.y * 100}%`, transform: `translateY(-50%) scale(${0.9 + 0.1 * enter})`, background: 'rgba(12,12,16,.82)', borderRadius: 36, padding: '40px 46px', fontFamily: inter, color: '#fff', boxShadow: '0 30px 80px rgba(0,0,0,.45)' }}
      >
        {effect.title && <div style={{ fontSize: 50, fontWeight: 800, marginBottom: 22 }}>{effect.title}</div>}
        {effect.items.map((item, i) => {
          const shown = local >= ticks[i] - 0.25
          const done = spring({ frame: (local - ticks[i]) * fps, fps, config: { damping: 12, stiffness: 200 } })
          return (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 26, margin: '16px 0', opacity: shown ? 1 : 0.35, fontSize: 46, fontWeight: 600 }}>
              <div style={{ width: 62, height: 62, borderRadius: 16, border: `5px solid ${effect.accent}`, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, background: local >= ticks[i] ? effect.accent : 'transparent' }}>
                {local >= ticks[i] && <span style={{ fontSize: 44, color: '#0b0b0d', transform: `scale(${done})` }}>✓</span>}
              </div>
              <span style={{ textDecoration: 'none' }}>{item}</span>
            </div>
          )
        })}
      </div>
    </AbsoluteFill>
  )
}

export function HeadlineWall({ effect, local, fps }: FxProps<'headline-wall'>) {
  const scripture = effect.look === 'scripture'
  const step = Math.min(0.45, (effect.duration * 0.6) / effect.headlines.length)
  return (
    <AbsoluteFill style={{ padding: '120px 60px', display: 'flex', flexDirection: 'column', gap: 26, justifyContent: 'center', opacity: fade(local, effect.duration) }}>
      {effect.headlines.map((h, i) => {
        const s = spring({ frame: (local - i * step) * fps, fps, config: { damping: 14 } })
        const tilt = ((i * 37) % 9) - 4
        return (
          <div
            key={i}
            style={{ alignSelf: i % 2 ? 'flex-end' : 'flex-start', maxWidth: '88%', transform: `translateY(${(1 - s) * 80}px) rotate(${tilt}deg) scale(${s})`, opacity: s, background: scripture ? '#F6EEDC' : '#FFFFFF', color: '#111', padding: '18px 26px', borderRadius: 6, boxShadow: '0 14px 40px rgba(0,0,0,.4)', fontFamily: scripture ? playfair : inter, fontWeight: scripture ? 700 : 800, fontSize: scripture ? 44 : 48, lineHeight: 1.15, textTransform: scripture ? 'none' : 'uppercase', borderLeft: scripture ? '10px solid #B8860B' : '10px solid #D10000' }}
          >
            {h}
          </div>
        )
      })}
    </AbsoluteFill>
  )
}

export function Chart({ effect, local, fps }: FxProps<'chart'>) {
  const n = Math.min(effect.labels.length, effect.values.length)
  const max = Math.max(...effect.values.slice(0, n), 1)
  const grow = spring({ frame: (local - 0.2) * fps, fps, config: { damping: 18, mass: 1.2 }, durationInFrames: Math.round(fps * 1.2) })
  const W = 860
  const Hc = 520
  return (
    <AbsoluteFill style={{ opacity: fade(local, effect.duration) }}>
      <div style={{ position: 'absolute', left: '50%', top: `${effect.y * 100}%`, transform: 'translate(-50%,-50%)', width: W + 80, background: 'rgba(12,12,16,.85)', borderRadius: 34, padding: 40, fontFamily: inter, color: '#fff' }}>
        {effect.title && <div style={{ fontSize: 46, fontWeight: 800, marginBottom: 20 }}>{effect.title}</div>}
        <svg width={W} height={Hc + 60}>
          {effect.kind === 'bar'
            ? effect.values.slice(0, n).map((v, i) => {
                const bw = (W / n) * 0.62
                const x = (W / n) * i + (W / n - bw) / 2
                const h = (v / max) * Hc * grow
                return (
                  <g key={i}>
                    <rect x={x} y={Hc - h} width={bw} height={h} rx={12} fill={effect.color} />
                    <text x={x + bw / 2} y={Hc - h - 14} fill="#fff" fontSize={34} fontWeight={800} textAnchor="middle" opacity={grow}>
                      {Math.round(v * grow)}
                      {effect.unit ?? ''}
                    </text>
                    <text x={x + bw / 2} y={Hc + 44} fill="#bbb" fontSize={30} textAnchor="middle">
                      {effect.labels[i]}
                    </text>
                  </g>
                )
              })
            : (() => {
                const pts = effect.values.slice(0, n).map((v, i) => [(W / Math.max(1, n - 1)) * i, Hc - (v / max) * Hc] as const)
                const d = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x},${y}`).join(' ')
                const len = pts.reduce((acc, p, i) => (i ? acc + Math.hypot(p[0] - pts[i - 1][0], p[1] - pts[i - 1][1]) : 0), 0)
                return (
                  <g>
                    <path d={d} fill="none" stroke={effect.color} strokeWidth={12} strokeLinecap="round" strokeLinejoin="round" strokeDasharray={len} strokeDashoffset={len * (1 - grow)} />
                    {pts.map(([x, y], i) => (
                      <g key={i} opacity={grow > i / n ? 1 : 0}>
                        <circle cx={x} cy={y} r={14} fill={effect.color} />
                        <text x={x} y={Hc + 44} fill="#bbb" fontSize={28} textAnchor="middle">
                          {effect.labels[i]}
                        </text>
                      </g>
                    ))}
                  </g>
                )
              })()}
        </svg>
      </div>
    </AbsoluteFill>
  )
}

export function GlassText({ effect, local, fps }: FxProps<'glass-text'>) {
  const s = spring({ frame: local * fps, fps, config: { damping: 15 } })
  return (
    <AbsoluteFill style={{ opacity: fade(local, effect.duration) }}>
      <div
        style={{ position: 'absolute', left: '7%', right: '7%', top: `${effect.y * 100}%`, transform: `translateY(-50%) translateY(${(1 - s) * 40}px)`, background: 'rgba(255,255,255,.14)', backdropFilter: 'blur(26px) saturate(1.4)', WebkitBackdropFilter: 'blur(26px) saturate(1.4)', border: '2px solid rgba(255,255,255,.35)', borderRadius: 40, padding: '44px 50px', boxShadow: '0 24px 70px rgba(0,0,0,.35)', fontFamily: inter, color: '#fff', textAlign: 'center' }}
      >
        <div style={{ fontSize: 72, fontWeight: 800, lineHeight: 1.08, textShadow: '0 2px 18px rgba(0,0,0,.35)' }}>{effect.text}</div>
        {effect.subtitle && <div style={{ fontSize: 38, fontWeight: 600, marginTop: 18, opacity: 0.85 }}>{effect.subtitle}</div>}
      </div>
    </AbsoluteFill>
  )
}
