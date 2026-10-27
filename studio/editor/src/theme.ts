import { useCallback, useEffect, useState } from 'react'

export type ThemePref = 'light' | 'dark' | 'system'
const KEY = 'tetclipper-theme'
const query = () => window.matchMedia('(prefers-color-scheme: dark)')

function readPref(): ThemePref {
  try {
    const v = localStorage.getItem(KEY)
    return v === 'light' || v === 'dark' ? v : 'system'
  } catch {
    return 'system'
  }
}

function apply(pref: ThemePref) {
  const dark = pref === 'dark' || (pref === 'system' && query().matches)
  document.documentElement.dataset.theme = dark ? 'dark' : 'light'
}

/** Light / dark / system, remembered per browser. index.html applies it before first paint. */
export function useTheme() {
  const [pref, setPref] = useState<ThemePref>(readPref)

  useEffect(() => {
    apply(pref)
    if (pref !== 'system') return
    const q = query()
    const onChange = () => apply('system')
    q.addEventListener('change', onChange)
    return () => q.removeEventListener('change', onChange)
  }, [pref])

  const set = useCallback((next: ThemePref) => {
    setPref(next)
    try {
      localStorage.setItem(KEY, next)
    } catch {
      /* private mode: theme still applies for this visit */
    }
  }, [])

  const toggle = useCallback(() => set(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'), [set])

  return { pref, set, toggle }
}
