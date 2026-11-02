// One audio element for the whole editor, so only one track preview plays at a
// time. Plays a file, or loops a range of it, and tells listeners where it is.
import { useEffect, useState } from 'react'

export interface PreviewState {
  url: string | null
  playing: boolean
  time: number
}

let state: PreviewState = { url: null, playing: false, time: 0 }
let range: [number, number | null] = [0, null]
let audio: HTMLAudioElement | null = null
let raf = 0
const listeners = new Set<(s: PreviewState) => void>()

const publish = (next: Partial<PreviewState>) => {
  state = { ...state, ...next }
  listeners.forEach((l) => l(state))
}

const tick = () => {
  if (!audio || audio.paused) return
  if (range[1] !== null && audio.currentTime >= range[1]) audio.currentTime = range[0]
  publish({ time: audio.currentTime })
  raf = requestAnimationFrame(tick)
}

export function stopPreview() {
  cancelAnimationFrame(raf)
  audio?.pause()
  if (state.playing) publish({ playing: false })
}

/** Start `url` at `from`; with `to`, keep looping from..to. */
export async function playPreview(url: string, from = 0, to: number | null = null) {
  if (!audio) {
    audio = new Audio()
    audio.addEventListener('ended', () => {
      if (audio && range[1] !== null) {
        audio.currentTime = range[0] // a range running to the track's end loops too
        audio.play().then(tick, stopPreview)
      } else stopPreview()
    })
  }
  cancelAnimationFrame(raf)
  range = [from, to]
  if (state.url !== url) audio.src = url
  audio.currentTime = from
  publish({ url, playing: true, time: from })
  try {
    await audio.play()
    tick()
  } catch {
    publish({ playing: false }) // unsupported file, or the browser refused
  }
}

export function useAudioPreview(): PreviewState {
  const [current, setCurrent] = useState(state)
  useEffect(() => {
    listeners.add(setCurrent)
    return () => {
      listeners.delete(setCurrent)
    }
  }, [])
  return current
}
