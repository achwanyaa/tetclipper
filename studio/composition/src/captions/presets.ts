// The caption looks. The first five follow tetclipper's ASS presets
// (pipeline/tetclipper_pipeline/captions/ass.py), adapted to word-by-word web
// rendering; the last four are web-only styles.
import { loadFont as loadAnton } from '@remotion/google-fonts/Anton'
import { loadFont as loadArchivo } from '@remotion/google-fonts/ArchivoBlack'
import { loadFont as loadInter } from '@remotion/google-fonts/Inter'
import { loadFont as loadMontserrat } from '@remotion/google-fonts/Montserrat'
import { loadFont as loadPlayfair } from '@remotion/google-fonts/PlayfairDisplay'
import type { CaptionStyle } from '../spec'

const inter = loadInter('normal', { weights: ['700', '800'], subsets: ['latin'] }).fontFamily
const anton = loadAnton('normal', { subsets: ['latin'] }).fontFamily
const archivo = loadArchivo('normal', { subsets: ['latin'] }).fontFamily
const montserrat = loadMontserrat('normal', { weights: ['800', '900'], subsets: ['latin'] }).fontFamily
const playfair = loadPlayfair('normal', { weights: ['600', '700'], subsets: ['latin'] }).fontFamily
loadPlayfair('italic', { weights: ['700'], subsets: ['latin'] })

export interface Preset {
  label: string
  blurb: string
  fontFamily: string
  fontWeight: number
  size: number
  color: string
  activeColor: string
  emphasisColor: string
  stroke: number // px text outline
  shadow: string
  uppercase: boolean
  maxWords: number
  position: number // vertical centre, fraction of frame height
  pop: boolean // the chunk springs in and the active word scales up
  activeBox?: string // pill behind the active word
  lineBox?: string // bar behind the whole line
  glow?: boolean // neon glow in the active colour
  reveal?: boolean // words appear as they're spoken (not-yet-spoken words are invisible)
  italicEmphasis?: boolean
  emoji: boolean // auto emoji on key words by default
}

export const PRESETS: Record<CaptionStyle, Preset> = {
  classic: {
    label: 'Classic', blurb: 'White with a gold spoken word',
    fontFamily: inter, fontWeight: 800, size: 72,
    color: '#FFFFFF', activeColor: '#FFD700', emphasisColor: '#FFD700',
    stroke: 8, shadow: '0 4px 8px rgba(0,0,0,.6)', uppercase: false,
    maxWords: 4, position: 0.7, pop: false, emoji: false
  },
  beast: {
    label: 'Beast', blurb: 'MrBeast caps, yellow and red',
    fontFamily: anton, fontWeight: 400, size: 96,
    color: '#FFFFFF', activeColor: '#FFE500', emphasisColor: '#FF4500',
    stroke: 12, shadow: '0 6px 0 rgba(0,0,0,.9)', uppercase: true,
    maxWords: 3, position: 0.68, pop: true, emoji: false
  },
  hormozi: {
    label: 'Hormozi', blurb: 'Bold caps, green spoken word',
    fontFamily: archivo, fontWeight: 400, size: 82,
    color: '#FFFFFF', activeColor: '#00FF00', emphasisColor: '#FFD700',
    stroke: 10, shadow: 'none', uppercase: true,
    maxWords: 3, position: 0.7, pop: true, emoji: false
  },
  minimal: {
    label: 'Minimal', blurb: 'Clean white, no highlight',
    fontFamily: inter, fontWeight: 700, size: 60,
    color: '#FFFFFF', activeColor: '#FFFFFF', emphasisColor: '#FFFFFF',
    stroke: 0, shadow: '0 2px 12px rgba(0,0,0,.8)', uppercase: false,
    maxWords: 5, position: 0.75, pop: false, emoji: false
  },
  'karaoke-pop': {
    label: 'Karaoke pop', blurb: 'Blue pill on the spoken word',
    fontFamily: archivo, fontWeight: 400, size: 78,
    color: '#E8E8E8', activeColor: '#FFFFFF', emphasisColor: '#FFD700',
    stroke: 10, shadow: '0 4px 0 rgba(0,0,0,.8)', uppercase: false,
    maxWords: 4, position: 0.7, pop: true, activeBox: '#0095FF', emoji: false
  },
  sermon: {
    label: 'Sermon', blurb: 'Elegant serif, words fade in',
    fontFamily: playfair, fontWeight: 700, size: 74,
    color: '#FFFFFF', activeColor: '#FFF4D6', emphasisColor: '#F2C46D',
    stroke: 0, shadow: '0 3px 18px rgba(0,0,0,.85), 0 1px 3px rgba(0,0,0,.9)', uppercase: false,
    maxWords: 6, position: 0.72, pop: false, reveal: true, italicEmphasis: true, emoji: false
  },
  'one-word': {
    label: 'One word', blurb: 'One big word at a time',
    fontFamily: anton, fontWeight: 400, size: 150,
    color: '#FFFFFF', activeColor: '#FFFFFF', emphasisColor: '#FFE500',
    stroke: 14, shadow: '0 8px 0 rgba(0,0,0,.85)', uppercase: true,
    maxWords: 1, position: 0.62, pop: true, emoji: false
  },
  boxed: {
    label: 'Boxed', blurb: 'White text on a black bar',
    fontFamily: montserrat, fontWeight: 900, size: 64,
    color: '#FFFFFF', activeColor: '#FFE500', emphasisColor: '#FFE500',
    stroke: 0, shadow: 'none', uppercase: false,
    maxWords: 4, position: 0.72, pop: false, lineBox: 'rgba(0,0,0,.86)', emoji: false
  },
  neon: {
    label: 'Neon', blurb: 'Glowing caps with emoji',
    fontFamily: montserrat, fontWeight: 900, size: 78,
    color: '#FFFFFF', activeColor: '#3DF5FF', emphasisColor: '#FF4FD8',
    stroke: 0, shadow: 'none', uppercase: true,
    maxWords: 3, position: 0.7, pop: true, glow: true, emoji: true
  }
}
