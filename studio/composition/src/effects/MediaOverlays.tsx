// Photos, GIFs and videos placed on top of the clip (spec.overlays). Drawn
// above the front effects and under the captions, never over the intro or
// outro. They are silent: the soundtrack is built without them.
import { Gif } from '@remotion/gif'
import { AbsoluteFill, Img, Loop, OffthreadVideo, Sequence, useVideoConfig } from 'remotion'
import type { ClipSpec, Overlay } from '../spec'
import { type Timeline, outputSpan } from '../timeline'

/** Where an overlay sits, as fractions of the frame: its centre, width and
 *  height. The editor's drag boxes use the same numbers. */
export function overlayBox(o: Pick<Overlay, 'x' | 'y' | 'width' | 'aspect'>, frameWidth: number, frameHeight: number) {
  const width = o.width
  const height = (o.width * frameWidth) / o.aspect / frameHeight
  return { x: o.x, y: o.y, width, height }
}

function Media({ overlay, px, py }: { overlay: Overlay; px: number; py: number }) {
  const { fps } = useVideoConfig()
  const fill = { width: '100%', height: '100%', display: 'block' } as const
  if (overlay.kind === 'gif') {
    return <Gif src={overlay.src} width={Math.round(px)} height={Math.round(py)} fit="fill" loopBehavior="loop" style={fill} />
  }
  if (overlay.kind === 'video') {
    const video = <OffthreadVideo src={overlay.src} muted style={{ ...fill, objectFit: 'fill' }} />
    const loop = overlay.duration ? Math.max(1, Math.round(overlay.duration * fps)) : 0
    return loop ? (
      <Loop durationInFrames={loop} layout="none">
        {video}
      </Loop>
    ) : (
      video
    )
  }
  return <Img src={overlay.src} style={{ ...fill, objectFit: 'fill' }} />
}

export function MediaOverlays({ spec, tl }: { spec: ClipSpec; tl: Timeline }) {
  const { fps, width, height } = useVideoConfig()
  if (!spec.overlays.length) return null
  return (
    <AbsoluteFill style={{ pointerEvents: 'none' }}>
      {spec.overlays.map((o) => {
        const span = outputSpan(tl, o.from, o.to, fps)
        if (!span) return null
        const box = overlayBox(o, width, height)
        return (
          <Sequence key={o.id} from={span[0]} durationInFrames={span[1] - span[0]} layout="none">
            <div
              style={{
                position: 'absolute',
                left: `${box.x * 100}%`,
                top: `${box.y * 100}%`,
                width: `${box.width * 100}%`,
                height: `${box.height * 100}%`,
                transform: `translate(-50%, -50%) rotate(${o.rotation}deg)`,
                opacity: o.opacity
              }}
            >
              <Media overlay={o} px={box.width * width} py={box.height * height} />
            </div>
          </Sequence>
        )
      })}
    </AbsoluteFill>
  )
}
