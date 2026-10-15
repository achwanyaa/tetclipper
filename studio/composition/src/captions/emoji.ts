// Auto emoji for key words (neon style, or captions.emoji = true).
// Matched on the lower-cased word stripped of punctuation; first match in a
// chunk wins. Kept small and literal so the result is predictable.
const EMOJI: Record<string, string> = {
  god: '🙏', jesus: '✝️', lord: '🙏', pray: '🙏', prayer: '🙏', amen: '🙌', hallelujah: '🙌',
  faith: '🙏', bless: '✨', blessed: '✨', blessing: '✨', grace: '🕊️', spirit: '🕊️', heaven: '☁️',
  love: '❤️', loves: '❤️', loved: '❤️', heart: '❤️', fire: '🔥', power: '⚡', powerful: '⚡',
  strong: '💪', strength: '💪', king: '👑', queen: '👑', money: '💰', rich: '💰', gold: '🥇',
  win: '🏆', victory: '🏆', light: '💡', truth: '💯', true: '💯', never: '🚫', stop: '🛑',
  time: '⏳', world: '🌍', life: '🌱', grow: '🌱', laugh: '😂', funny: '😂', cry: '😢',
  tears: '😢', think: '🤔', why: '🤔', secret: '🤫', important: '❗', now: '⏰', today: '📅',
  war: '⚔️', fight: '🥊', peace: '🕊️', joy: '😊', happy: '😊', family: '👨‍👩‍👧', children: '👶'
}

export function emojiFor(words: { text: string }[]): string | null {
  for (const w of words) {
    const key = w.text.toLowerCase().replace(/[^a-z']/g, '')
    if (EMOJI[key]) return EMOJI[key]
  }
  return null
}
