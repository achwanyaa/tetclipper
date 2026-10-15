// Pre-bundle the composition once (the Modal render image does this at build
// time) so each render skips webpack:  node scripts/bundle.mjs <out_dir>
// render.mjs uses it when TETCLIPPER_BUNDLE points at that directory.
import { bundle } from '@remotion/bundler'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const out = process.argv[2]
if (!out) {
  console.error('usage: bundle.mjs <out_dir>')
  process.exit(2)
}
const entry = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'src', 'entry.ts')
await bundle({ entryPoint: entry, outDir: path.resolve(out) })
console.log(`bundled to ${path.resolve(out)}`)
