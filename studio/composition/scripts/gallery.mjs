// Renders one still per caption style (compositions Style-<name>, see Root.tsx)
// into ../editor/public/styles/<name>.png for the editor's style gallery.
//   npm run gallery            (frame 150 by default)
//   npm run gallery -- 240     (pick another frame)
import { execFileSync } from 'node:child_process'
import { mkdirSync } from 'node:fs'
import path from 'node:path'

const STYLES = ['classic', 'beast', 'hormozi', 'minimal', 'karaoke-pop', 'sermon', 'one-word', 'boxed', 'neon']
const frame = process.argv[2] ?? '150'
const outDir = path.resolve('../editor/public/styles')
mkdirSync(outDir, { recursive: true })
const bin = path.resolve('../node_modules/.bin', process.platform === 'win32' ? 'remotion.cmd' : 'remotion')
for (const style of STYLES) {
  execFileSync(
    bin,
    ['still', 'src/entry.ts', `Style-${style}`, path.join(outDir, `${style}.png`), `--frame=${frame}`, '--scale=0.33'],
    { stdio: 'inherit', shell: process.platform === 'win32' }
  )
}
console.log(`wrote ${STYLES.length} stills to ${outDir}`)
