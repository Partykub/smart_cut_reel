/** Labels for waveform / timeline rulers (source seconds). */

export function formatMediaTimestamp(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) {
    return "0.00s";
  }
  if (seconds < 60) {
    return `${seconds.toFixed(2)}s`;
  }
  const m = Math.floor(seconds / 60);
  const s = seconds - m * 60;
  const frac = s.toFixed(2).padStart(5, "0");
  return `${m}:${frac}`;
}
