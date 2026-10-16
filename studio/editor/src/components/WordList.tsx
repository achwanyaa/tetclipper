import { useEffect, useState } from 'react'
import { invoke } from '../api'

interface Glossary {
  phrases: string[]
  fixes: { heard: string; said: string; count?: number }[]
  suggestions?: string[]
}

/** The learning word list: fixes the app remembers (applied to every new clip)
 *  and phrases it hints to the speech model. */
export function WordList({ onClose, setError }: { onClose: () => void; setError: (e: string | null) => void }) {
  const [g, setG] = useState<Glossary | null>(null)
  const [phrase, setPhrase] = useState('')

  useEffect(() => {
    invoke<Glossary>('glossary_get').then(setG).catch((e) => setError(String(e.message ?? e)))
  }, [setError])

  const save = async (next: Glossary) => {
    setG(next)
    try {
      setG(await invoke<Glossary>('glossary_save', { data: { phrases: next.phrases, fixes: next.fixes } }))
    } catch (e) {
      setError(String((e as Error).message ?? e))
    }
  }

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <div className="drawer" onClick={(e) => e.stopPropagation()}>
        <header>
          <strong>Word list</strong>
          <button className="link" onClick={onClose}>
            close
          </button>
        </header>
        {!g ? (
          <p className="muted">Loading…</p>
        ) : (
          <>
            <h4>Learned fixes</h4>
            <p className="muted small">Every caption fix is remembered and applied to new clips automatically.</p>
            {g.fixes.length === 0 && <p className="muted small">None yet.</p>}
            <table className="effects">
              <tbody>
                {g.fixes.map((f, i) => (
                  <tr key={i}>
                    <td className="muted">{f.heard}</td>
                    <td>→ {f.said || <em className="muted">(removed)</em>}</td>
                    <td className="muted small">×{f.count ?? 1}</td>
                    <td>
                      <button className="link" onClick={() => save({ ...g, fixes: g.fixes.filter((_, j) => j !== i) })}>
                        ✕
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <h4>Phrases</h4>
            <p className="muted small">Swahili/Sheng words, names and phrases the speech model should expect.</p>
            <div className="chips">
              {g.phrases.map((p) => (
                <span key={p} className="chip">
                  {p}
                  <button className="link" onClick={() => save({ ...g, phrases: g.phrases.filter((x) => x !== p) })}>
                    ✕
                  </button>
                </span>
              ))}
            </div>
            {(g.suggestions ?? []).length > 0 && (
              <>
                <p className="muted small">Common sermon words — click to add the ones this speaker uses:</p>
                <div className="chips">
                  {(g.suggestions ?? []).map((p) => (
                    <button key={p} className="chip suggest" onClick={() => save({ ...g, phrases: [...g.phrases, p] })}>
                      + {p}
                    </button>
                  ))}
                </div>
              </>
            )}
            <form
              className="row"
              onSubmit={(e) => {
                e.preventDefault()
                if (phrase.trim()) save({ ...g, phrases: [...g.phrases, phrase.trim()] })
                setPhrase('')
              }}
            >
              <input placeholder="add a word or phrase (e.g. Pst Catherine)" value={phrase} onChange={(e) => setPhrase(e.target.value)} />
              <button disabled={!phrase.trim()}>Add</button>
            </form>
          </>
        )}
      </div>
    </div>
  )
}
