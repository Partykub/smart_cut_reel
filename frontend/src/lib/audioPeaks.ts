/** Downsample PCM to normalized peak envelope for waveform rendering. */

export function peaksFromChannelData(
  channel: Float32Array,
  barCount: number,
): number[] {
  const n = channel.length;
  if (n === 0 || barCount <= 0) {
    return Array.from({ length: Math.max(barCount, 0) }, () => 0);
  }

  const peaks = new Array<number>(barCount);
  const block = Math.max(1, Math.floor(n / barCount));

  for (let i = 0; i < barCount; i++) {
    const start = i * block;
    const end = Math.min(start + block, n);
    let max = 0;
    for (let j = start; j < end; j++) {
      const v = Math.abs(channel[j]!);
      if (v > max) max = v;
    }
    peaks[i] = max;
  }

  const ceiling = Math.max(...peaks, 1e-8);
  return peaks.map((p) => p / ceiling);
}
