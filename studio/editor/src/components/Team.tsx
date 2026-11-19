import { useCallback, useEffect, useState } from 'react'
import { ROLE_LABEL, ROLE_SEES, invoke, when, type Role } from '../api'

interface Person {
  id: string
  email: string
  name: string
  role: Role
  status: 'active' | 'invited'
  lastSignIn: string | null
  invitedAt: string | null
  locked: boolean
  you: boolean
}

const ROLES: Role[] = ['editor', 'reviewer', 'head_reviewer', 'admin']

/** The admin's people page: invite someone with a role, and change anyone's role. */
export function Team({ setError }: { setError: (e: string | null) => void }) {
  const [people, setPeople] = useState<Person[] | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [role, setRole] = useState<Role>('editor')
  const [busy, setBusy] = useState<string | null>(null)
  const [sent, setSent] = useState<string | null>(null)

  const load = useCallback(() => {
    invoke<Person[]>('users_list')
      .then((p) => {
        setPeople(p)
        setProblem(null)
      })
      .catch((e) => setProblem(String((e as Error).message ?? e)))
  }, [])
  useEffect(load, [load])

  const invite = async () => {
    setBusy('invite')
    setSent(null)
    try {
      setPeople(await invoke<Person[]>('users_invite', { email, role, name: name || null }))
      setSent(`Invite sent to ${email.trim()}. They get an email with a link to set their password.`)
      setEmail('')
      setName('')
    } catch (e) {
      setError(String((e as Error).message ?? e))
    } finally {
      setBusy(null)
    }
  }

  const change = async (p: Person, next: Role) => {
    setBusy(p.id)
    try {
      setPeople(await invoke<Person[]>('users_set_role', { id: p.id, role: next }))
    } catch (e) {
      setError(String((e as Error).message ?? e))
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="record team">
      <div className="record-head">
        <h1>Team</h1>
        <span className="muted">Who can sign in, and what each person sees.</span>
      </div>

      {problem ? (
        <div className="card empty-card">
          <b>People can’t be managed from here yet.</b>
          <span className="muted">{problem}</span>
        </div>
      ) : (
        <>
          <form
            className="card team-invite"
            onSubmit={(e) => {
              e.preventDefault()
              if (email.trim()) invite()
            }}
          >
            <b>Invite someone</b>
            <div className="team-invite-row">
              <label className="field">
                <span className="label">Email</span>
                <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@example.com" autoComplete="off" />
              </label>
              <label className="field">
                <span className="label">Name (optional)</span>
                <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Mercy" autoComplete="off" />
              </label>
              <label className="field">
                <span className="label">Role</span>
                <select value={role} onChange={(e) => setRole(e.target.value as Role)}>
                  {ROLES.map((r) => (
                    <option key={r} value={r}>
                      {ROLE_LABEL[r]} · sees {ROLE_SEES[r].toLowerCase()}
                    </option>
                  ))}
                </select>
              </label>
              <button className="primary" disabled={busy === 'invite' || !email.trim()}>
                {busy === 'invite' ? 'Sending…' : 'Send invite'}
              </button>
            </div>
            {sent && <span className="small team-sent">{sent}</span>}
          </form>

          <div className="card record-table">
            <table>
              <thead>
                <tr>
                  <th scope="col">Person</th>
                  <th scope="col">Role</th>
                  <th scope="col">Sees</th>
                  <th scope="col">Status</th>
                </tr>
              </thead>
              <tbody>
                {people === null ? (
                  <tr>
                    <td colSpan={4} className="muted">
                      Loading…
                    </td>
                  </tr>
                ) : (
                  people.map((p) => (
                    <tr key={p.id}>
                      <th scope="row">
                        {p.name}
                        {p.you && <span className="muted small"> (you)</span>}
                        <div className="muted small team-email">{p.email}</div>
                      </th>
                      <td>
                        {p.locked ? (
                          <span>{ROLE_LABEL[p.role]}</span>
                        ) : (
                          <select aria-label={`Role for ${p.name}`} value={p.role} disabled={busy === p.id} onChange={(e) => change(p, e.target.value as Role)}>
                            {ROLES.map((r) => (
                              <option key={r} value={r}>
                                {ROLE_LABEL[r]}
                              </option>
                            ))}
                          </select>
                        )}
                      </td>
                      <td className="muted">{ROLE_SEES[p.role]}</td>
                      <td className="muted">{p.status === 'active' ? `Signed in ${when(p.lastSignIn)}` : `Invited ${when(p.invitedAt)}, hasn’t joined yet`}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
          <p className="muted small">
            Editors see editing only. Reviewers see Review only. The head reviewer sees Review and Record. The admin sees everything, including this page. A role change applies the next
            time the person’s page loads.
          </p>
        </>
      )}
    </div>
  )
}
