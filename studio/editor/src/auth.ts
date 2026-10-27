// Online sign-in (Supabase). The desktop app's server says mode "none" and the
// editor skips all of this. Invite and password-reset emails land back here
// with a link the Supabase client reads; we remember which kind it was so the
// app can ask for a new password.
import { useEffect, useState } from 'react'
import { createClient, type Session } from '@supabase/supabase-js'

const SB_URL = import.meta.env.VITE_SUPABASE_URL as string | undefined
const KEY = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY as string | undefined

// Read before the client consumes and clears the link's hash.
const linkType = /type=(invite|recovery)/.exec(window.location.hash)?.[1] as 'invite' | 'recovery' | undefined

export const supabase = SB_URL && KEY ? createClient(SB_URL, KEY) : null

export type AuthStage = 'loading' | 'signed-out' | 'set-password' | 'signed-in'

export function useSession() {
  const [session, setSession] = useState<Session | null>(null)
  const [stage, setStage] = useState<AuthStage>('loading')

  useEffect(() => {
    if (!supabase) {
      setStage('signed-out')
      return
    }
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session)
      setStage(data.session ? (linkType ? 'set-password' : 'signed-in') : 'signed-out')
    })
    const { data } = supabase.auth.onAuthStateChange((event, s) => {
      setSession(s)
      if (event === 'PASSWORD_RECOVERY') setStage('set-password')
      else if (event === 'SIGNED_OUT') setStage('signed-out')
      else if (s) setStage((cur) => (cur === 'set-password' ? cur : 'signed-in'))
    })
    return () => data.subscription.unsubscribe()
  }, [])

  return { session, stage, setStage }
}

export async function signIn(email: string, password: string): Promise<string | null> {
  if (!supabase) return 'Sign-in isn’t set up for this site.'
  const { error } = await supabase.auth.signInWithPassword({ email, password })
  if (!error) return null
  return /invalid login/i.test(error.message) ? 'Wrong email or password.' : error.message
}

export async function sendReset(email: string): Promise<string | null> {
  if (!supabase) return 'Sign-in isn’t set up for this site.'
  const { error } = await supabase.auth.resetPasswordForEmail(email, { redirectTo: window.location.origin + import.meta.env.BASE_URL })
  return error ? error.message : null
}

export async function setPassword(password: string): Promise<string | null> {
  if (!supabase) return 'Sign-in isn’t set up for this site.'
  const { error } = await supabase.auth.updateUser({ password })
  return error ? error.message : null
}

export async function signOut() {
  await supabase?.auth.signOut()
}
