import { describe, expect, it } from 'vitest'

import { contrastRatio } from './color'
import {
  BUILTIN_THEME_LIST,
  BUILTIN_THEMES,
  DEFAULT_SKIN_NAME,
  DEFAULT_TYPOGRAPHY,
  EMOJI_FALLBACK,
  financeMateTheme,
  nousAltTheme
} from './presets'

// #40364: none of the UI text/mono fonts carry emoji glyphs, so every font
// stack must end with a color-emoji fallback or emoji render as tofu on
// platforms whose default font lacks them (e.g. Linux).
describe('theme typography emoji fallback (#40364)', () => {
  const stacks: Array<[string, string]> = [
    ['DEFAULT_TYPOGRAPHY.fontSans', DEFAULT_TYPOGRAPHY.fontSans],
    ['DEFAULT_TYPOGRAPHY.fontMono', DEFAULT_TYPOGRAPHY.fontMono],
    // A theme may override only fontMono (fontSans then falls back to the
    // default, which already carries the emoji stack), so skip undefined.
    ...BUILTIN_THEME_LIST.flatMap(theme =>
      (
        [
          [`${theme.name}.fontSans`, theme.typography?.fontSans],
          [`${theme.name}.fontMono`, theme.typography?.fontMono]
        ] as Array<[string, string | undefined]>
      ).filter((entry): entry is [string, string] => typeof entry[1] === 'string')
    )
  ]

  it.each(stacks)('%s includes a color-emoji font', (_label, stack) => {
    expect(stack).toMatch(/Apple Color Emoji|Segoe UI Emoji|Noto Color Emoji|(^|,\s*)emoji\b/)
  })

  it('EMOJI_FALLBACK lists the major platform emoji fonts', () => {
    expect(EMOJI_FALLBACK).toContain('Apple Color Emoji')
    expect(EMOJI_FALLBACK).toContain('Segoe UI Emoji')
    expect(EMOJI_FALLBACK).toContain('Noto Color Emoji')
  })
})

// The pre-GitHub Nous palette stays available as nous-alt; the default name
// still means GitHub chrome + brand blue.
describe('nous-alt is the retired Nous, not the default', () => {
  it('is registered under its own name and leaves nous as the default', () => {
    expect(DEFAULT_SKIN_NAME).toBe('nous')
    expect(BUILTIN_THEMES['nous-alt']).toBe(nousAltTheme)
    expect(BUILTIN_THEMES.nous).not.toBe(nousAltTheme)
    expect(nousAltTheme.darkColors?.background).toBe('#0D2F86')
    expect(BUILTIN_THEMES.nous.darkColors?.background).not.toBe(nousAltTheme.darkColors?.background)
  })
})

describe('Finance Mate theme', () => {
  it('is registered as a selectable built-in without replacing the default', () => {
    expect(BUILTIN_THEMES['finance-mate']).toBe(financeMateTheme)
    expect(financeMateTheme.label).toBe('Finance Mate')
    expect(DEFAULT_SKIN_NAME).toBe('nous')
  })

  it.each([
    ['light foreground', financeMateTheme.colors.foreground, financeMateTheme.colors.background],
    ['light muted text', financeMateTheme.colors.mutedForeground, financeMateTheme.colors.background],
    ['light primary action', financeMateTheme.colors.primary, financeMateTheme.colors.primaryForeground],
    [
      'light sidebar accent',
      financeMateTheme.colors.primary,
      financeMateTheme.colors.sidebarBackground ?? financeMateTheme.colors.background
    ],
    ['dark foreground', financeMateTheme.darkColors?.foreground ?? '', financeMateTheme.darkColors?.background ?? ''],
    [
      'dark muted text',
      financeMateTheme.darkColors?.mutedForeground ?? '',
      financeMateTheme.darkColors?.background ?? ''
    ],
    [
      'dark primary action',
      financeMateTheme.darkColors?.primary ?? '',
      financeMateTheme.darkColors?.primaryForeground ?? ''
    ]
  ])('%s meets WCAG AA contrast', (_label, foreground, background) => {
    expect(contrastRatio(foreground, background)).toBeGreaterThanOrEqual(4.5)
  })

  it('carries dedicated terminal palettes for both appearance modes', () => {
    expect(financeMateTheme.terminal?.blue).toBe(financeMateTheme.colors.primary)
    expect(financeMateTheme.darkTerminal?.blue).toBe(financeMateTheme.darkColors?.primary)
  })
})
