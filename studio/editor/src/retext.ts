import type { Word } from '@tetclipper/composition'

/** Put `text` over a span of words without changing the word count — the same
 *  rule as pipeline/tetclipper_pipeline/spec/glossary.py retext(): tokens go on
 *  the first words (overflow joins the last), the rest are hidden, and the
 *  visible words share the span's timing. Keeping indices stable lets the
 *  word list learn every fix. */
export function retext(span: Word[], text: string): Word[] {
  const tokens = text.split(/\s+/).filter(Boolean)
  const out = span.map((w) => ({ ...w }))
  if (!out.length) return out
  if (!tokens.length) return out.map((w) => ({ ...w, hidden: true }))
  const k = out.length
  const toks = tokens.length > k ? [...tokens.slice(0, k - 1), tokens.slice(k - 1).join(' ')] : tokens
  const a = out[0].start
  const step = (out[out.length - 1].end - a) / toks.length
  return out.map((w, i) => {
    if (i >= toks.length) return { ...w, hidden: true }
    const { hidden: _hidden, ...rest } = w
    void _hidden
    return { ...rest, text: toks[i], start: +(a + i * step).toFixed(3), end: +(a + (i + 1) * step).toFixed(3) }
  })
}
