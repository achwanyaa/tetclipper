// The app says "AI": fail the build check if a provider's name reaches the
// browser bundle. Run after `npm run build -w editor`.
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'

const DIST = new URL('../dist', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')
const NAMES = /claude|anthropic|\bhaiku\b|\bsonnet\b/i

const files = (dir) =>
  readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    return statSync(path).isDirectory() ? files(path) : [path]
  })

let bad = 0
for (const file of files(DIST)) {
  if (!/\.(js|css|html|map|json|txt)$/.test(file)) continue
  const text = readFileSync(file, 'utf8')
  const hit = NAMES.exec(text)
  if (hit) {
    bad++
    console.error(`${file}: "${hit[0]}" in …${text.slice(Math.max(0, hit.index - 60), hit.index + 60)}…`)
  }
}
if (bad) process.exit(1)
console.log('no provider names in the bundle')
