// Render one clip spec to mp4 with Remotion.
//
//   node scripts/render.mjs <spec.json> <base_dir> <out> [--concurrency=N]
//                           [--frames=A-B] [--muted] [--audio-only]
//
// --frames/--muted render one silent chunk (Modal renders chunks in parallel
// containers and joins them); --audio-only writes the soundtrack as .wav.
//
// Relative `source.src` / `intro.src` / image `src` paths in the spec are
// resolved against <base_dir> (the job dir) and served by a tiny local HTTP
// server with byte-range support, so the same script works on this PC and in
// the Modal render container. Progress is printed as JSON lines:
//   {"event":"progress","stage":"render","fraction":0.42,"message":"…"}
//   {"event":"result","ok":true,"output":"…"}
import { bundle } from '@remotion/bundler'
import { renderMedia, selectComposition } from '@remotion/renderer'
import { createReadStream, readFileSync, statSync } from 'node:fs'
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const [specPath, baseDir, outPath, ...rest] = process.argv.slice(2)
if (!specPath || !baseDir || !outPath) {
  console.error('usage: render.mjs <spec.json> <base_dir> <out.mp4> [--concurrency=N]')
  process.exit(2)
}
const flag = (name) => rest.find((a) => a.startsWith(`--${name}=`))?.split('=')[1]
const say = (obj) => process.stdout.write(JSON.stringify(obj) + '\n')
const progress = (fraction, message) => say({ event: 'progress', stage: 'render', fraction, message })

const TYPES = { '.webm': 'video/webm', '.mp3': 'audio/mpeg', '.wav': 'audio/wav', '.m4a': 'audio/mp4', '.aac': 'audio/aac', '.ogg': 'audio/ogg', '.flac': 'audio/flac', '.mp4': 'video/mp4', '.webm': 'video/webm', '.mov': 'video/quicktime', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp', '.gif': 'image/gif' }

/** Static file server for base_dir with Range support (OffthreadVideo seeks). */
function serve(root) {
  const rootAbs = path.resolve(root)
  const server = http.createServer((req, res) => {
    const rel = decodeURIComponent(new URL(req.url, 'http://x').pathname).replace(/^\/+/, '')
    const file = path.resolve(rootAbs, rel)
    if (!file.startsWith(rootAbs + path.sep)) return res.writeHead(403).end()
    let size
    try {
      size = statSync(file).size
    } catch {
      return res.writeHead(404).end()
    }
    const type = TYPES[path.extname(file).toLowerCase()] ?? 'application/octet-stream'
    const range = /bytes=(\d*)-(\d*)/.exec(req.headers.range ?? '')
    if (range) {
      const start = range[1] ? Number(range[1]) : size - Number(range[2])
      const end = range[1] && range[2] ? Math.min(Number(range[2]), size - 1) : size - 1
      res.writeHead(206, { 'Content-Type': type, 'Content-Range': `bytes ${start}-${end}/${size}`, 'Content-Length': end - start + 1, 'Accept-Ranges': 'bytes' })
      createReadStream(file, { start, end }).pipe(res)
    } else {
      res.writeHead(200, { 'Content-Type': type, 'Content-Length': size, 'Accept-Ranges': 'bytes' })
      createReadStream(file).pipe(res)
    }
  })
  return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve(server)))
}

const isUrl = (s) => /^(https?:|data:|blob:)/.test(s)

function resolveAssets(spec, base) {
  const url = (src) => (isUrl(src) ? src : `${base}/${src.split(path.sep).join('/').split('/').map(encodeURIComponent).join('/')}`)
  const out = structuredClone(spec)
  out.source.src = url(out.source.src)
  if (out.intro) out.intro.src = url(out.intro.src)
  if (out.music) out.music.src = url(out.music.src)
  if (out.matte) out.matte.src = url(out.matte.src)
  for (const e of out.effects ?? []) if ((e.type === 'image' || e.type === 'background') && e.src) e.src = url(e.src)
  return out
}

async function main() {
  const spec = JSON.parse(readFileSync(specPath, 'utf8'))
  const server = await serve(baseDir)
  const base = `http://127.0.0.1:${server.address().port}`
  try {
    const inputProps = resolveAssets(spec, base)
    const frames = flag('frames')?.split('-').map(Number)
    const audioOnly = rest.includes('--audio-only')
    const prebuilt = process.env.TETCLIPPER_BUNDLE
    let serveUrl = prebuilt
    if (!prebuilt) {
      progress(0.02, 'Bundling composition…')
      const entry = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'src', 'entry.ts')
      serveUrl = await bundle({ entryPoint: entry })
    }
    const composition = await selectComposition({ serveUrl, id: 'VerticalClip', inputProps })
    const count = frames ? frames[1] - frames[0] + 1 : composition.durationInFrames
    progress(0.08, `Rendering ${count} frames…`)
    const concurrency = Number(flag('concurrency') ?? Math.max(1, os.cpus().length - 1))
    let last = 0
    const t0 = Date.now()
    await renderMedia({
      serveUrl,
      composition,
      inputProps,
      ...(audioOnly ? { codec: 'wav' } : { codec: 'h264', crf: 20, audioCodec: 'aac', muted: rest.includes('--muted') }),
      ...(frames ? { frameRange: [frames[0], frames[1]] } : {}),
      outputLocation: outPath,
      concurrency,
      // The frame extractor defaults to 2 threads, which starves 16 browser
      // workers decoding 1080p source video.
      offthreadVideoThreads: Math.max(2, concurrency),
      chromiumOptions: { enableMultiProcessOnLinux: true },
      onProgress: ({ progress: p }) => {
        if (p - last >= 0.02 || p === 1) {
          last = p
          progress(0.08 + p * 0.92, `Rendering… ${Math.round(p * 100)}%`)
        }
      }
    })
    const seconds = (Date.now() - t0) / 1000
    say({ event: 'result', ok: true, output: path.resolve(outPath), seconds, fps: +(count / seconds).toFixed(1) })
  } finally {
    server.close()
  }
}

main().catch((err) => {
  say({ event: 'result', ok: false, error: String(err?.message ?? err) })
  process.exit(1)
})
