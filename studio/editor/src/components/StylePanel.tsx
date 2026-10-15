import { CAPTION_STYLES, PRESETS, type CaptionStyle } from '@tetclipper/composition'
import type { PanelProps } from './Canvas'

const STILL = (s: string) => `${import.meta.env.BASE_URL}styles/${s}.png`

/** Caption style gallery (stills rendered on real footage) + fine controls. */
export function StylePanel({ spec, update }: PanelProps) {
  const captions = spec.captions ?? {}
  const style: CaptionStyle = captions.style ?? 'hormozi'
  const preset = PRESETS[style]
  const set = (patch: Record<string, unknown>, reason: string) =>
    update({ ...spec, captions: { ...captions, ...patch } }, reason)

  return (
    <div className="style-panel">
      <div className="gallery">
        {CAPTION_STYLES.map((s) => (
          <button
            key={s}
            className={`style-card ${s === style ? 'active' : ''}`}
            onClick={() => set({ style: s, size: undefined, color: undefined, activeColor: undefined, emphasisColor: undefined, uppercase: undefined, maxWords: undefined, position: undefined, emoji: undefined }, `captions: ${s}`)}
            title={PRESETS[s].blurb}
          >
            <img src={STILL(s)} alt={PRESETS[s].label} loading="lazy" />
            <span>{PRESETS[s].label}</span>
          </button>
        ))}
      </div>

      <div className="controls">
        <label className="toggle">
          <input type="checkbox" checked={captions.enabled ?? true} onChange={(e) => set({ enabled: e.target.checked }, 'captions on/off')} />
          Captions
        </label>
        <label>
          Position <span>{Math.round((captions.position ?? preset.position) * 100)}%</span>
          <input type="range" min={0.15} max={0.92} step={0.01} value={captions.position ?? preset.position} onChange={(e) => set({ position: +e.target.value }, 'caption position')} />
        </label>
        <label>
          Size <span>{Math.round(captions.size ?? preset.size)}px</span>
          <input type="range" min={36} max={200} step={2} value={captions.size ?? preset.size} onChange={(e) => set({ size: +e.target.value }, 'caption size')} />
        </label>
        <label>
          Words per line <span>{captions.maxWords ?? preset.maxWords}</span>
          <input type="range" min={1} max={8} step={1} value={captions.maxWords ?? preset.maxWords} onChange={(e) => set({ maxWords: +e.target.value }, 'words per line')} />
        </label>
        <div className="row">
          <label className="color">
            Text <input type="color" value={captions.color ?? preset.color} onChange={(e) => set({ color: e.target.value }, 'caption colour')} />
          </label>
          <label className="color">
            Spoken <input type="color" value={captions.activeColor ?? preset.activeColor} onChange={(e) => set({ activeColor: e.target.value }, 'highlight colour')} />
          </label>
          <label className="color">
            Emphasis <input type="color" value={captions.emphasisColor ?? preset.emphasisColor} onChange={(e) => set({ emphasisColor: e.target.value }, 'emphasis colour')} />
          </label>
        </div>
        <div className="row">
          <label className="toggle">
            <input type="checkbox" checked={captions.uppercase ?? preset.uppercase} onChange={(e) => set({ uppercase: e.target.checked }, 'uppercase')} />
            UPPERCASE
          </label>
          <label className="toggle">
            <input type="checkbox" checked={captions.emoji ?? preset.emoji} onChange={(e) => set({ emoji: e.target.checked }, 'auto emoji')} />
            Auto emoji
          </label>
          <label className="toggle">
            <input
              type="checkbox"
              checked={spec.progressBar?.enabled ?? false}
              onChange={(e) => update({ ...spec, progressBar: { color: '#FFD700', ...spec.progressBar, enabled: e.target.checked } }, 'progress bar')}
            />
            Progress bar
          </label>
        </div>
      </div>
    </div>
  )
}
