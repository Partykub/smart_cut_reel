/** dBFS → linear amplitude relative to an anchor peak (normalized waveform max ≈ anchor). */
export function dbfsRelativeLinear(dbfs: number, anchorDbfs: number): number {
  return 10 ** ((dbfs - anchorDbfs) / 20);
}

/**
 * Map astats dBFS into 0…1 display space: window low ≈ 0.12, window high = 1 (top).
 * Quieter material below the window still gets partial height (extra headroom below lo).
 */
export function dbfsToWindowDisplayLin(
  dbfs: number,
  lowDbfs: number,
  highDbfs: number,
): number {
  const lo = Math.min(lowDbfs, highDbfs);
  const hi = Math.max(lowDbfs, highDbfs);
  const windowSpan = Math.max(hi - lo, 0.5);
  const floor = 0.12;
  if (dbfs >= lo) {
    const t = Math.min(1, (dbfs - lo) / windowSpan);
    return Math.min(1.12, floor + (1 - floor) * t);
  }
  const headroomDb = 22;
  const below = Math.max(0, (dbfs - (lo - headroomDb)) / headroomDb);
  return floor * below;
}

/** Per-bar linear peak (0…1, file-normalized) → estimated dBFS using astats anchor peak. */
export function sampleLinearToDbfs(peakLinear: number, anchorDbfs: number): number {
  return anchorDbfs + 20 * Math.log10(Math.max(peakLinear, 1e-6));
}

/** Inclusive window check using rounded dBFS (matches on-screen digits). */
export function peakDbfsWithinWindowRounded(
  peak: number,
  low: number,
  high: number,
  decimals: number,
): boolean {
  const p = Number(peak.toFixed(decimals));
  const lo = Number(low.toFixed(decimals));
  const hi = Number(high.toFixed(decimals));
  return lo <= p && p <= hi;
}

export type ReferenceDbfsGuide = {
  lowDbfs: number;
  highDbfs: number;
  /** astats post peak — waveform envelope is normalized to file max ≈ this level */
  anchorDbfs: number;
  prePeakDbfs?: number | null;
  postPeakDbfs?: number | null;
};
