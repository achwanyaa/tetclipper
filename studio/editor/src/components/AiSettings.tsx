import { useEffect, useState } from 'react'
import { invoke, type AiSettings as Settings } from '../api'

interface Props {
  onClose: () => void
  onSaved: (s: Settings) => void
}

const money = (n: number) => (n < 1 ? `$${n.toFixed(2)}` : `$${n}`)

/** Admin: which provider, model and API key the Studio chat uses, for every user. */
export function AiSettings({ onClose, onSaved }: Props) {
  const [settings, setSettings] = useState<Settings | null>(null)
  const [provider, setProvider] = useState('')
  const [model, setModel] = useState('')
  const [key, setKey] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [priceIn, setPriceIn] = useState('')
  const [priceOut, setPriceOut] = useState('')
  const [models, setModels] = useState<Record<string, string[]>>({})
  const [loading, setLoading] = useState(false)
  const [testing, setTesting] = useState(false)
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    invoke<Settings>('ai_settings_get')
      .then((s) => {
        setSettings(s)
        pick(s, s.provider, s.model)
      })
      .catch((e) => setError(String(e.message ?? e)))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const pick = (s: Settings, id: string, keepModel?: string) => {
    const p = s.providers.find((x) => x.id === id)!
    setProvider(id)
    setModel(keepModel || p.default || p.models[0] || '')
    setKey('')
    setResult(null)
    setError(null)
    setBaseUrl(id === 'custom' ? s.base_url : '')
    const price = s.prices[id]
    setPriceIn(price?.in != null ? String(price.in) : '')
    setPriceOut(price?.out != null ? String(price.out) : '')
  }

  if (!settings) {
    return (
      <Shell onClose={onClose}>
        <span className="muted">{error ?? 'Loading…'}</span>
      </Shell>
    )
  }

  const p = settings.providers.find((x) => x.id === provider)!
  const api = p.kind !== 'cli'
  const options = models[provider] ?? p.models
  const known = settings.known_prices[model]
  const keyArgs = { provider, ...(key.trim() ? { key: key.trim() } : {}), ...(provider === 'custom' ? { base_url: baseUrl } : {}) }

  const loadModels = async () => {
    setLoading(true)
    setError(null)
    try {
      const list = await invoke<string[]>('ai_models', keyArgs)
      setModels((m) => ({ ...m, [provider]: list }))
      if (list.length && !list.includes(model)) setModel(list.includes(p.default) ? p.default : list[0])
    } catch (e) {
      setError(String((e as Error).message ?? e))
    } finally {
      setLoading(false)
    }
  }

  const test = async () => {
    setTesting(true)
    setResult(null)
    try {
      const r = await invoke<{ ok: boolean; reply?: string; ms?: number; error?: string }>('ai_test', { ...keyArgs, model })
      setResult(r.ok ? { ok: true, text: `Works · ${r.ms} ms · replied “${r.reply}”` } : { ok: false, text: r.error ?? 'Failed' })
    } catch (e) {
      setResult({ ok: false, text: String((e as Error).message ?? e) })
    } finally {
      setTesting(false)
    }
  }

  const save = async (clearKey = false) => {
    setSaving(true)
    setError(null)
    try {
      const num = (v: string) => (v.trim() === '' ? null : Number(v))
      const s = await invoke<Settings>('ai_settings_save', {
        provider,
        model,
        ...(key.trim() ? { key: key.trim() } : {}),
        clear_key: clearKey,
        ...(provider === 'custom' ? { base_url: baseUrl } : {}),
        ...(api && p.kind !== 'anthropic' ? { price_in: num(priceIn), price_out: num(priceOut) } : {})
      })
      setSettings(s)
      setKey('')
      if (!clearKey) {
        onSaved(s)
        onClose()
      }
    } catch (e) {
      setError(String((e as Error).message ?? e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Shell onClose={onClose}>
      <div className="ai-grid">
        <div className="ai-providers">
          {settings.providers.map((x) => (
            <button key={x.id} className={`ai-provider ${x.id === provider ? 'on' : ''}`} onClick={() => pick(settings, x.id, x.id === settings.provider ? settings.model : undefined)}>
              <span className="row" style={{ gap: 8 }}>
                <b>{x.label}</b>
                {x.id === settings.provider && <span className="tag ok">In use</span>}
              </span>
              <span className="small muted">{x.kind === 'cli' ? 'No key needed' : x.key ? `Key ${x.key}` : 'No key yet'}</span>
            </button>
          ))}
        </div>

        <div className="ai-detail">
          <b style={{ fontSize: 16 }}>{p.label}</b>
          {p.note && <span className="small muted">{p.note}</span>}

          {api && (
            <>
              {provider === 'custom' && (
                <label className="field">
                  <span className="label">Base URL</span>
                  <input placeholder="https://openrouter.ai/api/v1" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
                </label>
              )}
              <label className="field">
                <span className="label row" style={{ gap: 6 }}>
                  <span className="spacer">API key</span>
                  {p.key_url && (
                    <a href={p.key_url} target="_blank" rel="noreferrer">
                      Get a key ↗
                    </a>
                  )}
                </span>
                <input type="password" autoComplete="off" placeholder={p.key ? `Saved (${p.key}). Paste a new key to replace it.` : 'Paste the API key'} value={key} onChange={(e) => setKey(e.target.value)} />
                {p.key && (
                  <button className="link small muted" style={{ alignSelf: 'flex-start' }} disabled={saving} onClick={() => save(true)}>
                    Remove the saved key
                  </button>
                )}
              </label>

              <label className="field">
                <span className="label row" style={{ gap: 6 }}>
                  <span className="spacer">Model</span>
                  <button className="link small" disabled={loading || (!key.trim() && !p.key)} onClick={loadModels}>
                    {loading ? 'Loading…' : models[provider] ? `${models[provider].length} models · reload` : `Load ${p.label.split(' (')[0]} models`}
                  </button>
                </span>
                <input list={`models-${provider}`} value={model} onChange={(e) => setModel(e.target.value)} placeholder="model id" />
                <datalist id={`models-${provider}`}>
                  {options.map((m) => (
                    <option key={m} value={m} />
                  ))}
                </datalist>
                {known && (
                  <span className="small muted">
                    {money(known[0])} in / {money(known[1])} out per million tokens · about ${((known[0] * 20000 + known[1] * 1000) / 1e6).toFixed(4)} per message
                  </span>
                )}
              </label>

              {p.kind !== 'anthropic' && (
                <div className="field">
                  <span className="label">Price per million tokens (optional, to show costs)</span>
                  <div className="range-grid">
                    <input placeholder="input $" value={priceIn} onChange={(e) => setPriceIn(e.target.value)} />
                    <input placeholder="output $" value={priceOut} onChange={(e) => setPriceOut(e.target.value)} />
                  </div>
                </div>
              )}

              <div className="row">
                <button className="tonal" disabled={testing || !model || (!key.trim() && !p.key)} onClick={test}>
                  {testing ? 'Testing…' : 'Test'}
                </button>
                {result && <span className="small" style={{ color: result.ok ? 'var(--ok)' : 'var(--dg)' }}>{result.text}</span>}
              </div>
            </>
          )}

          {error && (
            <div className="note dg">
              <b>{error}</b>
            </div>
          )}
          <span className="spacer" />
          <div className="row" style={{ justifyContent: 'flex-end' }}>
            <button onClick={onClose}>Cancel</button>
            <button className="primary" disabled={saving} onClick={() => save()}>
              {saving ? 'Saving…' : provider === settings.provider ? 'Save' : `Use ${p.label.split(' (')[0]}`}
            </button>
          </div>
        </div>
      </div>
    </Shell>
  )
}

function Shell({ onClose, children }: { onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="row">
          <div className="spacer" style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <b style={{ fontSize: 20 }}>AI model</b>
            <span className="small muted">The model behind the Claude chat, for every user. Keys stay on the server.</span>
          </div>
          <button className="link muted" onClick={onClose}>
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}
