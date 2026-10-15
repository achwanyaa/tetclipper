// Writes spec.schema.json (JSON Schema of the clip spec) next to package.json
// and into the Python package (pipeline/tetclipper_pipeline/spec/), which
// validates every spec.json against it. Claude Code reads it too, so the zod
// schema in src/spec.ts stays the single source of truth.
//   npm run schema
import { writeFileSync } from 'node:fs'
import { zodToJsonSchema } from 'zod-to-json-schema'
import { clipSpecSchema } from '../src/spec'

const schema = zodToJsonSchema(clipSpecSchema, { name: 'ClipSpec', target: 'jsonSchema7', $refStrategy: 'none' })
const text = JSON.stringify(schema, null, 2) + '\n'
for (const target of ['../spec.schema.json', '../../../pipeline/tetclipper_pipeline/spec/spec.schema.json']) {
  writeFileSync(new URL(target, import.meta.url), text)
}
console.log('wrote spec.schema.json (studio + pipeline)')
