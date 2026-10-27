import { useState, type FormEvent } from 'react'
import { sendReset, setPassword, signIn } from '../auth'
import { STILL } from './Home'

type View = 'sign-in' | 'forgot' | 'sent' | 'set-password'

/** Online sign-in (design 2a): form on the left, the product on the right.
 *  Invite-only: no sign-up link. Also sets a password after an invite or reset link. */
export function SignIn({ setPasswordMode = false, onPasswordSet }: { setPasswordMode?: boolean; onPasswordSet?: () => void }) {
  const [view, setView] = useState<View>(setPasswordMode ? 'set-password' : 'sign-in')
  const [email, setEmail] = useState('')
  const [password, setPw] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    if (view === 'sign-in') setError(await signIn(email.trim(), password))
    else if (view === 'forgot') {
      const err = await sendReset(email.trim())
      if (err) setError(err)
      else setView('sent')
    } else if (view === 'set-password') {
      if (password.length < 8) setError('Use at least 8 characters.')
      else {
        const err = await setPassword(password)
        if (err) setError(err)
        else onPasswordSet?.()
      }
    }
    setBusy(false)
  }

  return (
    <div className="signin">
      <div className="signin-form">
        <span className="logo" style={{ fontSize: 20, cursor: 'default' }}>
          tetclipper
        </span>
        <form onSubmit={submit}>
          {view === 'sent' ? (
            <>
              <div className="signin-head">
                <h1>Check your email</h1>
                <span className="muted">We sent a reset link to {email}. Open it on this device.</span>
              </div>
              <button type="button" className="tonal lg" onClick={() => setView('sign-in')}>
                Back to sign in
              </button>
            </>
          ) : (
            <>
              <div className="signin-head">
                <h1>{view === 'set-password' ? 'Set your password' : view === 'forgot' ? 'Reset your password' : 'Welcome back'}</h1>
                <span className="muted">
                  {view === 'set-password' ? 'Choose a password to open your studio.' : view === 'forgot' ? 'We’ll email you a link.' : 'Sign in to your studio.'}
                </span>
              </div>
              {view !== 'set-password' && (
                <label className="field">
                  <span className="label" style={{ color: 'var(--ink)' }}>
                    Email
                  </span>
                  <input type="email" autoComplete="email" required autoFocus value={email} onChange={(e) => setEmail(e.target.value)} />
                </label>
              )}
              {view !== 'forgot' && (
                <label className="field">
                  <span className="label row" style={{ color: 'var(--ink)' }}>
                    <span className="spacer">{view === 'set-password' ? 'New password' : 'Password'}</span>
                    {view === 'sign-in' && (
                      <button type="button" className="link small" onClick={() => setView('forgot')}>
                        Forgot password?
                      </button>
                    )}
                  </span>
                  <input
                    type="password"
                    autoComplete={view === 'set-password' ? 'new-password' : 'current-password'}
                    required
                    autoFocus={view === 'set-password'}
                    value={password}
                    onChange={(e) => setPw(e.target.value)}
                  />
                </label>
              )}
              {error && (
                <div className="note dg">
                  <b>{error}</b>
                </div>
              )}
              <button className="primary lg" disabled={busy}>
                {busy ? 'Please wait…' : view === 'set-password' ? 'Set password' : view === 'forgot' ? 'Send reset link' : 'Sign in'}
              </button>
              {view === 'forgot' ? (
                <button type="button" className="link small muted" onClick={() => setView('sign-in')}>
                  Back to sign in
                </button>
              ) : (
                view === 'sign-in' && <span className="small muted" style={{ textAlign: 'center' }}>tetclipper is invite-only. Ask the owner for an invite.</span>
              )}
            </>
          )}
        </form>
      </div>
      <div className="signin-art">
        <img src={STILL('sermon')} alt="" className="side left" />
        <img src={STILL('hormozi')} alt="" className="side right" />
        <img src={STILL('beast')} alt="" className="main" />
        <div className="signin-copy">
          <b>
            Long sermons in.
            <br />
            Vertical clips out.
          </b>
          <span>Captions in English, Swahili and Sheng. Claude edits with you.</span>
        </div>
      </div>
    </div>
  )
}
