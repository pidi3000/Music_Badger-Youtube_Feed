// WCAG contrast helpers used to keep randomized tag colors legible: tag
// chips always render white text (see styles/tag-chip.css), and the plain
// color swatch on the Tags page sits on the app's light background — so a
// "random" color still needs to pass real contrast checks against both,
// not just look different from the last one.

function hexToRgb(hex: string): [number, number, number] {
  const clean = hex.replace('#', '');
  const value = parseInt(clean, 16);
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
}

function relativeLuminance([r, g, b]: [number, number, number]): number {
  const channel = (c: number) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

export function contrastRatio(hexA: string, hexB: string): number {
  const luminanceA = relativeLuminance(hexToRgb(hexA));
  const luminanceB = relativeLuminance(hexToRgb(hexB));
  const lighter = Math.max(luminanceA, luminanceB);
  const darker = Math.min(luminanceA, luminanceB);
  return (lighter + 0.05) / (darker + 0.05);
}

function hslToHex(hue: number, saturation: number, lightness: number): string {
  const s = saturation / 100;
  const l = lightness / 100;
  const k = (n: number) => (n + hue / 30) % 12;
  const a = s * Math.min(l, 1 - l);
  const f = (n: number) => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  const toHex = (n: number) =>
    Math.round(255 * f(n))
      .toString(16)
      .padStart(2, '0');
  return `#${toHex(0)}${toHex(8)}${toHex(4)}`;
}

// Matches --bg / --bg-light in styles/global.css.
const PAGE_BACKGROUND = '#f9fafb';
const CARD_BACKGROUND = '#ffffff';
const WHITE = '#ffffff';

const MIN_CONTRAST_FOR_WHITE_TEXT = 4.5; // WCAG AA, normal-size text
const MIN_CONTRAST_FOR_SWATCH = 3; // enough to stay visible against the page

/**
 * A random, WCAG-checked color for a new tag: readable as white chip text,
 * and visible as a plain swatch against the app's light background. Picks
 * from a mid-to-dark, moderately saturated HSL range and re-rolls (rather
 * than clamping) any candidate that fails contrast — some hues (yellows,
 * limes) look "dark enough" by lightness alone but are still too bright
 * for white text, so a fixed HSL range isn't sufficient on its own.
 */
export function randomTagColor(): string {
  for (let attempt = 0; attempt < 20; attempt++) {
    const hue = Math.floor(Math.random() * 360);
    const saturation = 55 + Math.random() * 25; // 55-80%
    const lightness = 32 + Math.random() * 18; // 32-50%
    const candidate = hslToHex(hue, saturation, lightness);

    const readableAsChipText = contrastRatio(candidate, WHITE) >= MIN_CONTRAST_FOR_WHITE_TEXT;
    const visibleAsSwatch =
      contrastRatio(candidate, PAGE_BACKGROUND) >= MIN_CONTRAST_FOR_SWATCH &&
      contrastRatio(candidate, CARD_BACKGROUND) >= MIN_CONTRAST_FOR_SWATCH;

    if (readableAsChipText && visibleAsSwatch) {
      return candidate;
    }
  }

  // Should be unreachable in practice (most hues pass within a few
  // attempts), but guarantees termination with a color known to pass both
  // checks.
  const fallbacks = ['#2563eb', '#7c3aed', '#0f766e', '#b91c1c', '#a16207', '#0e7490'];
  return fallbacks[Math.floor(Math.random() * fallbacks.length)];
}
