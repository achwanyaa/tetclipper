import type { Word } from '../spec'

/** Break words into on-screen groups: at punctuation, at a pause > 0.6 s,
 *  or when the group reaches maxWords. */
export function chunkWords(words: Word[], maxWords: number): Word[][] {
  const chunks: Word[][] = []
  let current: Word[] = []
  words.forEach((word, i) => {
    current.push(word)
    const next = words[i + 1]
    const brk =
      !next ||
      current.length >= maxWords ||
      /[.!?,;:]$/.test(word.text) ||
      next.start - word.end > 0.6
    if (brk) {
      chunks.push(current)
      current = []
    }
  })
  return chunks
}
