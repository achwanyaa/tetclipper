// Writes spec.schema.json (JSON Schema of the clip spec) next to package.json.
// The Python pipeline validates spec.json against it, and Claude Code reads it,
// so the zod schema in src/spec.ts stays the single source of truth.
//   npm run schema
import { writeFileSync } from 'node:fs'
import { zodToJsonSchema } from 'zod-to-json-schema'
import { clipSpecSchema } from '../src/spec'

const schema = zodToJsonSchema(clipSpecSchema, { name: 'ClipSpec', target: 'jsonSchema7', $refStrategy: 'none' })
writeFileSync(new URL('../spec.schema.json', import.meta.url), JSON.stringify(schema, null, 2) + '\n')
console.log('wrote spec.schema.json')
