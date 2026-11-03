import { useEffect, useLayoutEffect, useRef, type CSSProperties } from 'react'
import { Internals, useBufferState } from 'remotion'

const MAX_DRIFT = 0.5 // seconds the picture may slip before it's put right

/** The preview's video: one element for the whole clip that jumps across cuts.
 *  A <Sequence> per kept piece starts each piece from nothing, which on a slow
 *  connection means a stall (or black) at every cut, while the footage just past
 *  a cut is usually already downloaded. Renders still use a Sequence per piece.
 *  While the element waits for data the timeline waits too, so picture, sound
 *  and captions stay together. */
export function PreviewVideo({ src, time, segment, active, style }: {
  src: string
  time: number // source seconds to show now
  segment: number // changes at a cut: time to jump
  active: boolean // the video is on screen (not before the intro ends or after the last piece)
  style: CSSProperties
}) {
  const ref = useRef<HTMLVideoElement>(null)
  const playing = Internals.Timeline.usePlaying()
  const [volume] = Internals.useMediaVolumeState()
  const [muted] = Internals.usePlayerMutedState()
  const buffer = useBufferState()
  const shown = useRef(segment)

  useEffect(() => {
    const v = ref.current
    if (!v) return
    let handle: { unblock: () => void } | null = null
    const wait = () => {
      handle = handle ?? buffer.delayPlayback()
    }
    const go = () => {
      handle?.unblock()
      handle = null
    }
    const maybeGo = () => {
      if (v.readyState >= 2 && !v.seeking) go()
    }
    for (const name of ['loadstart', 'waiting', 'seeking']) v.addEventListener(name, wait)
    for (const name of ['canplay', 'playing', 'seeked']) v.addEventListener(name, maybeGo)
    v.addEventListener('error', go) // a broken file mustn't hold the timeline forever
    return () => {
      for (const name of ['loadstart', 'waiting', 'seeking']) v.removeEventListener(name, wait)
      for (const name of ['canplay', 'playing', 'seeked']) v.removeEventListener(name, maybeGo)
      v.removeEventListener('error', go)
      go()
    }
  }, [buffer])

  useLayoutEffect(() => {
    const v = ref.current
    if (!v) return
    const jumped = shown.current !== segment
    shown.current = segment
    v.volume = Math.max(0, Math.min(1, volume))
    v.muted = muted
    if (!active || !playing) {
      if (!v.paused) v.pause()
      if (Math.abs(v.currentTime - time) > 0.02) v.currentTime = time
      return
    }
    const drift = v.currentTime - time
    if (jumped || Math.abs(drift) > MAX_DRIFT) v.currentTime = time
    // Catch small slips without seeking: a seek can mean another wait for data.
    const size = Math.abs(drift)
    const rate = jumped || size < 0.06 ? 1 : 1 - Math.sign(drift) * (size < 0.2 ? 0.05 : 0.1)
    if (v.playbackRate !== rate) v.playbackRate = rate
    if (v.paused && !v.ended) v.play().catch(() => undefined)
  })

  return <video ref={ref} src={src} preload="auto" playsInline style={style} />
}
