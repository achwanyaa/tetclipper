// Behind-the-speaker pieces: drawn between the background and the cut-out
// speaker (spec.matte). Without a matte they still draw, in front.
import { AbsoluteFill, interpolate, spring } from 'remotion'
import { loadFont as loadAnton } from '@remotion/google-fonts/Anton'
import { loadFont as loadPlayfair } from '@remotion/google-fonts/PlayfairDisplay'
import { loadFont as loadInter } from '@remotion/google-fonts/Inter'
import type { FxProps } from './graphics'

const anton = loadAnton('normal', { subsets: ['latin'] }).fontFamily
const playfair = loadPlayfair('normal', { weights: ['700'], subsets: ['latin'] }).fontFamily
const inter = loadInter('normal', { weights: ['800'], subsets: ['latin'] }).fontFamily

const fade = (local: number, duration: number, secs = 0.35) =>
  interpolate(Math.min(local, duration - local), [0, secs], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' })

export function WallText({ effect, local, fps }: FxProps<'wall-text'>) {
  const s = spring({ frame: local * fps, fps, config: { damping: 18 } })
  const words = effect.text.split(/\s+/)
  return (
    <AbsoluteFill style={{ opacity: fade(local, effect.duration) }}>
      <div style={{ position: 'absolute', left: 0, right: 0, top: `${effect.y * 100}%`, transform: `translateY(-50%) scale(${0.92 + 0.08 * s})`, textAlign: 'center', fontFamily: anton, color: effect.color, fontSize: words.length > 2 ? 210 : 300, lineHeight: 0.9, textTransform: 'uppercase', letterSpacing: 4, textShadow: '0 10px 40px rgba(0,0,0,.35)' }}>
        {words.map((w, i) => (
          <div key={i} style={{ opacity: local >= i * 0.12 ? 1 : 0 }}>
            {w}
          </div>
        ))}
      </div>
    </AbsoluteFill>
  )
}

/** Masthead (behind) or cover lines (front). */
export function Cover({ effect, local, fps, part }: FxProps<'cover'> & { part: 'masthead' | 'lines' }) {
  const s = spring({ frame: local * fps, fps, config: { damping: 16 } })
  if (part === 'masthead') {
    return (
      <AbsoluteFill style={{ opacity: fade(local, effect.duration) }}>
        <div style={{ position: 'absolute', top: '5%', left: 0, right: 0, textAlign: 'center', fontFamily: playfair, fontWeight: 700, fontSize: effect.title.length > 8 ? 190 : 260, color: effect.color, letterSpacing: -6, transform: `translateY(${(1 - s) * -60}px)`, lineHeight: 1 }}>
          {effect.title}
        </div>
      </AbsoluteFill>
    )
  }
  return (
    <AbsoluteFill style={{ opacity: fade(local, effect.duration) }}>
      {effect.issue && (
        <div style={{ position: 'absolute', top: '19%', right: '7%', fontFamily: inter, fontWeight: 800, fontSize: 30, color: '#fff', letterSpacing: 3, textShadow: '0 2px 10px rgba(0,0,0,.6)' }}>{effect.issue}</div>
      )}
      <div style={{ position: 'absolute', left: '6%', bottom: '18%', display: 'flex', flexDirection: 'column', gap: 18, maxWidth: '62%' }}>
        {effect.lines.map((line, i) => {
          const k = spring({ frame: (local - 0.3 - i * 0.25) * fps, fps, config: { damping: 15 } })
          return (
            <div key={i} style={{ fontFamily: inter, fontWeight: 800, fontSize: 48, lineHeight: 1.05, color: '#fff', textTransform: 'uppercase', textShadow: '0 3px 14px rgba(0,0,0,.7)', borderLeft: `8px solid ${effect.color}`, paddingLeft: 16, transform: `translateX(${(1 - k) * -60}px)`, opacity: k }}>
              {line}
            </div>
          )
        })}
      </div>
    </AbsoluteFill>
  )
}
