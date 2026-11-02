import { TRANSITIONS, type Transition, type TransitionType } from '@tetclipper/composition'

export const TRANSITION_LABELS: Record<TransitionType, string> = {
  fade: 'Fade',
  'dip-black': 'Dip to black',
  'dip-white': 'Flash',
  'slide-left': 'Slide left',
  'slide-up': 'Slide up',
  zoom: 'Zoom',
  wipe: 'Wipe',
  blur: 'Blur'
}

interface Props {
  value: Partial<Transition> | null | undefined
  onChange: (next: { type: TransitionType; duration: number } | null, reason: string) => void
  onPreview?: () => void
}

/** Hard cut or an animated effect, its length, and a way to see it in the preview.
 *  Each tile plays a tiny version of its effect on hover. */
export function TransitionPicker({ value, onChange, onPreview }: Props) {
  const duration = value?.duration ?? 0.5
  return (
    <div className="transition-picker">
      <div className="transition-tiles">
        <button className={`transition-tile ${value ? '' : 'on'}`} aria-pressed={!value} onClick={() => onChange(null, 'hard cut')}>
          <span className="tile-art none" />
          None
        </button>
        {TRANSITIONS.map((type) => (
          <button key={type} className={`transition-tile ${value?.type === type ? 'on' : ''}`} aria-pressed={value?.type === type} onClick={() => onChange({ type, duration }, `transition: ${TRANSITION_LABELS[type]}`)}>
            <span className={`tile-art ${type}`}>
              <i />
            </span>
            {TRANSITION_LABELS[type]}
          </button>
        ))}
      </div>
      {value?.type && (
        <div className="row">
          <label className="spacer">
            Length <span>{duration.toFixed(1)} s</span>
            <input type="range" min={0.2} max={2} step={0.1} value={duration} onChange={(e) => onChange({ type: value.type as TransitionType, duration: +e.target.value }, 'transition length')} />
          </label>
          {onPreview && (
            <button className="sm" onClick={onPreview}>
              ▶ Preview
            </button>
          )}
        </div>
      )}
    </div>
  )
}
