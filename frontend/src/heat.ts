/**
 * Heat-score color scale. Sequential = one hue, light -> dark (dataviz rule);
 * red because the spec's demo line is "three blocks glow red". Seven steps of
 * a single-hue red ramp, lightness strictly decreasing.
 */
export const HEAT_STEPS = [
  { min: 0, hex: "#fee5d9" },
  { min: 20, hex: "#fcbba1" },
  { min: 40, hex: "#fc9272" },
  { min: 60, hex: "#fb6a4a" },
  { min: 70, hex: "#ef3b2c" },
  { min: 85, hex: "#cb181d" },
  { min: 95, hex: "#99000d" },
] as const;

export const NO_SCORE_HEX = "#e1e0d9"; // gridline gray: "no data", recedes

export function heatColor(score: number | null | undefined): string {
  if (score == null || Number.isNaN(score)) return NO_SCORE_HEX;
  let hex: string = HEAT_STEPS[0].hex;
  for (const step of HEAT_STEPS) if (score >= step.min) hex = step.hex;
  return hex;
}

/** Ink color for a label sitting inside a fill (white on dark steps). */
export function inkOn(hex: string): string {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  const lum = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  return lum < 140 ? "#ffffff" : "#0b0b0b";
}
