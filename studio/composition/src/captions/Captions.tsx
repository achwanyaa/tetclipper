import { useMemo, type CSSProperties } from 'react'
import { AbsoluteFill, spring, useVideoConfig } from 'remotion'
import type { ClipSpec, Word } from '../spec'
import { type Timeline, isInCut, useSourceTime } from '../timeline'
import { chunkWords } from './chunk'
import { emojiFor } from './emoji'
import { PRESETS } from './presets'

/** Words that should appear on screen: not hidden, inside the range, not cut. */
export function visibleWords(spec: ClipSpec, tl: Timeline): Word[] {
  const { start, end } = spec.source
  return spec.words.filter(
    (w) => !w.hidden && w.text.trim() && w.end > start && w.start < end && !isInCut(tl, (w.start + w.end) / 2)
  )
}

export function Captions({ spec, tl }: { spec: ClipSpec; tl: Timeline }) {
  const { fps } = useVideoConfig()
  const t = useSourceTime(tl)
  const { captions } = spec
  const preset = PRESETS[captions.style]
  const maxWords = captions.maxWords ?? preset.maxWords

  const chunks = useMemo(() => chunkWords(visibleWords(spec, tl), maxWords), [spec, tl, maxWords])

  if (!captions.enabled || t === null) return null
  // A chunk stays up until the next one starts (no flicker in short gaps).
  const idx = chunks.findIndex((c, i) => {
    const until = Math.min(chunks[i + 1]?.[0].start ?? Infinity, c[c.length - 1].end + 0.6)
    return t >= c[0].start && t < until
  })
  if (idx < 0) return null
  const chunk = chunks[idx]

  const size = captions.size ?? preset.size
  const upper = captions.uppercase ?? preset.uppercase
  const color = captions.color ?? preset.color
  const active = captions.activeColor ?? preset.activeColor
  const emphasis = captions.emphasisColor ?? preset.emphasisColor
  const position = captions.position ?? preset.position
  const showEmoji = captions.emoji ?? preset.emoji
  // springs are driven by elapsed source time so they survive cuts
  const since = (s: number) => Math.max(0, (t - s) * fps)
  const enter = spring({ frame: since(chunk[0].start), fps, config: { damping: 14, stiffness: 220 }, durationInFrames: 8 })

  const single = chunk.length === 1 && maxWords === 1
  const longest = Math.max(...chunk.map((w) => w.text.length))
  const fontSize = single && longest > 7 ? (size * 7) / longest : size
  const emoji = showEmoji ? emojiFor(chunk) : null

  // reveal styles only lay out words already spoken, so the line grows centred
  const shown = preset.reveal ? chunk.filter((w) => t >= w.start) : chunk
  const words = shown.map((w, i) => {
    const isActive = t >= w.start && t < (shown[i + 1]?.start ?? w.end + 0.6)
    const pop = preset.pop && isActive
      ? spring({ frame: since(w.start), fps, config: { damping: 10, stiffness: 300 }, durationInFrames: 6 })
      : 0
    const fill = isActive ? active : w.emphasis ? emphasis : color
    const style: CSSProperties = {
      display: 'inline-block',
      color: fill,
      WebkitTextStroke: preset.stroke ? `${preset.stroke}px #000` : undefined,
      paintOrder: 'stroke fill',
      textShadow: preset.glow
        ? `0 0 6px ${fill}, 0 0 18px ${fill}, 0 0 40px ${isActive ? active : 'rgba(255,255,255,.35)'}`
        : preset.shadow,
      transform: `scale(${1 + 0.06 * pop})`,
      transformOrigin: 'center bottom',
      fontStyle: preset.italicEmphasis && w.emphasis ? 'italic' : undefined,
      opacity: preset.reveal ? Math.min(1, since(w.start) / (0.18 * fps)) : 1,
      background: isActive && preset.activeBox ? preset.activeBox : undefined,
      borderRadius: preset.activeBox ? fontSize * 0.18 : undefined,
      padding: preset.activeBox ? `0 ${fontSize * 0.16}px` : undefined
    }
    return (
      <span key={`${w.start}-${i}`} style={style}>
        {upper ? w.text.toUpperCase() : w.text}
      </span>
    )
  })

  const textBlock = preset.lineBox ? (
    <span
      style={{
        background: preset.lineBox,
        padding: `${fontSize * 0.12}px ${fontSize * 0.3}px`,
        borderRadius: fontSize * 0.16,
        boxDecorationBreak: 'clone',
        WebkitBoxDecorationBreak: 'clone',
        lineHeight: 1.5
      }}
    >
      {words.flatMap((el, i) => (i ? [' ', el] : [el]))}
    </span>
  ) : (
    words
  )

  return (
    <AbsoluteFill style={{ justifyContent: 'flex-start', alignItems: 'center' }}>
      <div
        style={{
          position: 'absolute',
          top: `${position * 100}%`,
          transform: `translateY(-50%) scale(${preset.pop ? 0.85 + 0.15 * enter : 1})`,
          width: '86%',
          display: preset.lineBox ? 'block' : 'flex',
          flexWrap: 'wrap',
          justifyContent: 'center',
          gap: `${fontSize * 0.12}px ${fontSize * 0.3}px`,
          fontFamily: preset.fontFamily,
          fontWeight: preset.fontWeight,
          fontSize,
          lineHeight: 1.12,
          textAlign: 'center'
        }}
      >
        {emoji && (
          <div
            style={{
              position: 'absolute',
              left: 0,
              right: 0,
              bottom: '100%',
              marginBottom: fontSize * 0.3,
              fontSize: fontSize * 1.25,
              transform: `scale(${spring({ frame: since(chunk[0].start), fps, config: { damping: 9, stiffness: 180 } })})`
            }}
          >
            {emoji}
          </div>
        )}
        {textBlock}
      </div>
    </AbsoluteFill>
  )
}
