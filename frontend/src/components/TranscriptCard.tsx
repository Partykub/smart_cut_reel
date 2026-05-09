"use client";

import { useEffect, useState } from "react";

import type { Transcript } from "@/lib/types";

interface TranscriptCardProps {
  jobId: string;
}

export function TranscriptCard({ jobId }: TranscriptCardProps) {
  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const url = `/api/jobs/${encodeURIComponent(jobId)}/artifacts/transcript`;

    async function load() {
      setIsLoading(true);
      try {
        const response = await fetch(url, { cache: "no-store" });
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        const body = (await response.json()) as Transcript;
        if (!cancelled) {
          setTranscript(body);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  if (isLoading) {
    return (
      <section className="rounded-lg border border-zinc-800 bg-zinc-950/40 p-4 text-sm text-zinc-500">
        กำลังโหลด transcript…
      </section>
    );
  }

  if (error || !transcript) {
    return (
      <section className="rounded-lg border border-amber-900/40 bg-amber-950/30 p-4 text-sm text-amber-200">
        โหลด transcript ไม่ได้: {error ?? "no data"}
      </section>
    );
  }

  if (
    transcript.language === "skipped" ||
    transcript.metrics?.skipped_reason
  ) {
    return null;
  }

  if (transcript.segments.length === 0) {
    return null;
  }

  const isThai = transcript.language?.toLowerCase() === "th";

  return (
    <section className="space-y-4 rounded-lg border border-zinc-800 bg-zinc-950/40 p-4">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <p className="text-xs uppercase tracking-widest text-zinc-500">
            ข้อความที่ถอด (Transcript)
          </p>
          <h2 className="text-lg font-medium text-zinc-100">
            {transcript.language.toUpperCase()} · {transcript.model}
          </h2>
        </div>
        <div className="text-right text-xs text-zinc-400">
          <p>
            <span className="font-mono text-zinc-200">
              {transcript.metrics.total_words}
            </span>{" "}
            คำ ·{" "}
            <span className="font-mono text-amber-300">
              {transcript.metrics.filler_word_count}
            </span>{" "}
            คำลังเล
          </p>
          {typeof transcript.metrics.average_confidence === "number" ? (
            <p>
              ความมั่นใจเฉลี่ย{" "}
              <span className="font-mono text-zinc-200">
                {(transcript.metrics.average_confidence * 100).toFixed(1)}%
              </span>
            </p>
          ) : null}
        </div>
      </header>

      <ol className="space-y-3 text-sm leading-relaxed">
        {transcript.segments.map((segment, idx) => (
          <li
            key={`segment-${idx}-${segment.start}`}
            className="rounded-md border border-zinc-800 bg-zinc-900/40 p-3"
          >
            <p className="mb-2 font-mono text-[11px] text-zinc-500">
              {segment.start.toFixed(2)}s → {segment.end.toFixed(2)}s
            </p>
            {/* Render words inline without flex/gap so non-space languages
                like Thai concatenate correctly. Whisper already includes a
                leading space on each English word, so spaces still appear
                naturally for Latin scripts. */}
            <p
              className={
                isThai
                  ? "whitespace-pre-wrap break-words text-base text-zinc-100"
                  : "whitespace-pre-wrap break-words text-zinc-100"
              }
              lang={transcript.language}
            >
              {segment.words.map((word, wIdx) => (
                <span
                  key={`word-${idx}-${wIdx}-${word.start}`}
                  className={
                    word.is_filler
                      ? "rounded bg-amber-900/50 px-0.5 font-medium text-amber-200 line-through"
                      : undefined
                  }
                  title={`${word.start.toFixed(2)}–${word.end.toFixed(2)}s · ความมั่นใจ ${
                    word.confidence !== null
                      ? (word.confidence * 100).toFixed(0) + "%"
                      : "n/a"
                  }`}
                >
                  {word.word}
                </span>
              ))}
            </p>
          </li>
        ))}
      </ol>
    </section>
  );
}
