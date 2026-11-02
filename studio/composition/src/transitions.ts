// How a transition looks at one moment. Pure and frame-based, so every render
// chunk and the preview draw exactly the same picture. One layer animates over
// another: a leaving layer reveals what's under it, an entering layer covers it.
import type { CSSProperties } from 'react'
import { Easing } from 'remotion'
import type { TransitionType } from './spec'

const ease = Easing.inOut(Easing.cubic)

export interface TransitionLook {
  style: CSSProperties // on the animated layer
  cover: CSSProperties | null // a full-frame colour drawn over both layers
}

/** `progress` runs 0 → 1 across the transition. */
export function transitionLook(type: TransitionType, progress: number, entering = false): TransitionLook {
  const p = Math.max(0, Math.min(1, progress))
  const gone = ease(entering ? 1 - p : p) // 0 = fully on screen, 1 = fully off
  const side = entering ? 1 : -1 // leaves to the left/top, enters from the right/bottom
  switch (type) {
    case 'fade':
      return { style: { opacity: 1 - gone }, cover: null }
    case 'dip-black':
    case 'dip-white':
      return {
        style: { opacity: gone < 0.5 ? 1 : 0 },
        cover: { background: type === 'dip-black' ? '#000' : '#fff', opacity: 1 - Math.abs(2 * gone - 1) }
      }
    case 'slide-left':
      return { style: { transform: `translateX(${side * gone * 100}%)` }, cover: null }
    case 'slide-up':
      return { style: { transform: `translateY(${side * gone * 100}%)` }, cover: null }
    case 'zoom':
      return { style: { transform: `scale(${1 + gone * 1.5})`, opacity: 1 - gone }, cover: null }
    case 'wipe':
      return { style: { clipPath: `inset(0 ${gone * 100}% 0 0)` }, cover: null }
    case 'blur':
      return { style: { filter: `blur(${gone * 48}px)`, opacity: 1 - gone }, cover: null }
  }
}
