// Dev helper: cut a range out of a local video + whisperX transcript into
// public/fixtures/ so the Remotion studio has real footage and real word
// timings to style against.
//
//   node scripts/make-fixture.mjs <job_dir> <start_sec> <end_sec> [name]
//
// job_dir must hold media.mp4 and asr.json (whisperX segments with words).
// Needs ffmpeg on PATH or FFMPEG=<path>.
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'

const [jobDir, startArg, endArg, name = 'sample'] = process.argv.slice(2)
if (!jobDir || !startArg || !endArg) {
  console.error('usage: make-fixture.mjs <job_dir> <start_sec> <end_sec> [name]')
  process.exit(1)
}
const start = Number(startArg)
const end = Number(endArg)
const ffmpeg = process.env.FFMPEG ?? 'ffmpeg'
const outDir = path.resolve('public/fixtures')
fs.mkdirSync(outDir, { recursive: true })

execFileSync(
  ffmpeg,
  [
    '-y', '-ss', String(start), '-to', String(end), '-i', path.join(jobDir, 'media.mp4'),
    '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p',
    '-c:a', 'aac', '-b:a', '160k', '-movflags', '+faststart',
    path.join(outDir, `${name}.mp4`)
  ],
  { stdio: 'inherit' }
)

const asr = JSON.parse(fs.readFileSync(path.join(jobDir, 'asr.json'), 'utf8')).data
const words = asr.segments
  .flatMap((s) => s.words ?? [])
  .filter((w) => w.start != null && w.start >= start && w.end <= end)
  .map((w) => ({
    text: w.word.trim(),
    start: +(w.start - start).toFixed(3),
    end: +(w.end - start).toFixed(3)
  }))

fs.writeFileSync(
  path.join(outDir, `${name}.json`),
  JSON.stringify({ duration: +(end - start).toFixed(3), words }, null, 1)
)
console.log(`wrote ${name}.mp4 + ${name}.json (${words.length} words)`)
