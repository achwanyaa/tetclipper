// Public surface used by the editor (Player preview) and the Modal render script.
export * from './spec'
export * from './timeline'
export { VerticalClip, calculateClipMetadata, clipDurationInFrames } from './VerticalClip'
export { PRESETS, type Preset } from './captions/presets'
export { chunkWords } from './captions/chunk'
export { visibleWords } from './captions/Captions'
export { musicGains, speechSpans } from './music'
