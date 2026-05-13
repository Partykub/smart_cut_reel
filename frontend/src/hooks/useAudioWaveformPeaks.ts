"use client";

import { useEffect, useMemo, useState } from "react";

import { peaksFromChannelData } from "@/lib/audioPeaks";

export type WaveformLoadState = "idle" | "loading" | "ready" | "error";

const DEFAULT_BARS = 480;
const MAX_CHANNEL_SAMPLES = 1_200_000;

type DecodedWaveform = { peaks: number[]; durationSeconds: number; bars: number };

const decodeCache = new Map<string, Promise<DecodedWaveform>>();

function cacheKey(url: string, bars: number): string {
  return `${url}::${bars}`;
}

async function decodeUrlToPeaks(url: string, bars: number): Promise<DecodedWaveform> {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  const raw = await response.arrayBuffer();

  const AudioContextCtor =
    window.AudioContext ||
    (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!AudioContextCtor) {
    throw new Error("Web Audio API is not available in this browser.");
  }

  const ctx = new AudioContextCtor();
  const copy = raw.slice(0);
  const audioBuffer = await ctx.decodeAudioData(copy);

  const ch0 = audioBuffer.getChannelData(0);
  let work = ch0;
  if (ch0.length > MAX_CHANNEL_SAMPLES) {
    const step = Math.ceil(ch0.length / MAX_CHANNEL_SAMPLES);
    const reduced = new Float32Array(Math.ceil(ch0.length / step));
    for (let i = 0, j = 0; i < ch0.length; i += step, j++) {
      reduced[j] = ch0[i]!;
    }
    work = reduced;
  }

  const peaks = peaksFromChannelData(work, bars);
  const durationSeconds = audioBuffer.duration;
  await ctx.close().catch(() => undefined);
  return { peaks, durationSeconds, bars };
}

export interface UseAudioWaveformPeaksResult {
  state: WaveformLoadState;
  peaks: number[] | null;
  durationSeconds: number | null;
  error: string | null;
}

/**
 * Fetch an audio URL (WAV, or container formats the browser can decode e.g. MP4/AAC),
 * decode with Web Audio, return normalized peaks.
 * Caps work per channel to keep main thread responsive on long clips.
 */
export function useAudioWaveformPeaks(
  url: string | null,
  barCount: number = DEFAULT_BARS,
): UseAudioWaveformPeaksResult {
  const [state, setState] = useState<WaveformLoadState>("idle");
  const [peaks, setPeaks] = useState<number[] | null>(null);
  const [durationSeconds, setDurationSeconds] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const bars = useMemo(() => Math.max(32, Math.min(960, Math.floor(barCount))), [barCount]);

  useEffect(() => {
    if (!url) {
      setState("idle");
      setPeaks(null);
      setDurationSeconds(null);
      setError(null);
      return;
    }

    const ac = new AbortController();
    setState("loading");
    setPeaks(null);
    setDurationSeconds(null);
    setError(null);

    void (async () => {
      try {
        const key = cacheKey(url, bars);
        let pending = decodeCache.get(key);
        if (!pending) {
          pending = decodeUrlToPeaks(url, bars);
          decodeCache.set(key, pending);
        }
        const decoded = await pending;
        if (ac.signal.aborted) return;
        setPeaks(decoded.peaks);
        setDurationSeconds(decoded.durationSeconds);
        setState("ready");
      } catch (err) {
        if (ac.signal.aborted) return;
        decodeCache.delete(cacheKey(url, bars));
        setState("error");
        setError(err instanceof Error ? err.message : String(err));
      }
    })();

    return () => ac.abort();
  }, [url, bars]);

  return { state, peaks, durationSeconds, error };
}
