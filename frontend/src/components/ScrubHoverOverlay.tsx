"use client";

import { formatMediaTimestamp } from "@/lib/formatMediaTime";

function findRemovedGapAtTime(
  gaps: { start: number; end: number }[] | undefined,
  sec: number,
): { start: number; end: number } | undefined {
  if (!gaps?.length) return undefined;
  const t = sec;
  return gaps.find((g) => t >= g.start && t < g.end - 1e-9);
}

/**
 * Vertical playhead + floating time readout for scrub-style hover (parent must be `relative`).
 * When `removedGaps` is set and the cursor is inside a removed region, shows that gap's range
 * (for narrow bars where inline labels do not fit).
 */
export function ScrubHoverOverlay({
  ratio,
  totalSeconds,
  removedGaps,
}: {
  ratio: number | null;
  totalSeconds: number;
  /** Source-time gaps treated as cut / dead-air; used for second-line range on hover. */
  removedGaps?: { start: number; end: number }[];
}) {
  if (ratio == null || totalSeconds <= 0) {
    return null;
  }

  const sec = ratio * totalSeconds;
  const pct = ratio * 100;
  const activeRemoved = findRemovedGapAtTime(removedGaps, sec);

  return (
    <>
      <div
        className="pointer-events-none absolute inset-y-0 left-0 right-0 z-20"
        aria-hidden
      >
        <div
          className={`absolute top-0 bottom-0 w-px shadow-[0_0_12px_rgba(34,211,238,0.55)] ${
            activeRemoved
              ? "bg-gradient-to-b from-rose-200/95 via-rose-400 to-rose-300/55"
              : "bg-gradient-to-b from-cyan-200/90 via-cyan-400 to-cyan-300/50"
          }`}
          style={{ left: `${pct}%`, transform: "translateX(-50%)" }}
        />
      </div>
      <div
        className={`pointer-events-none absolute z-30 max-w-[min(92vw,18rem)] rounded-md border px-2 py-1 text-center font-mono text-[10px] font-medium shadow-lg backdrop-blur-sm ${
          activeRemoved
            ? "border-rose-500/45 bg-zinc-950/97 text-rose-50"
            : "whitespace-nowrap border-cyan-500/35 bg-zinc-950/95 text-cyan-100"
        }`}
        style={{
          left: `${pct}%`,
          top: "6px",
          transform: "translateX(-50%)",
        }}
      >
        <span className={activeRemoved ? "text-cyan-200/90" : ""}>
          {formatMediaTimestamp(sec)}
        </span>
        {activeRemoved ? (
          <div className="mt-0.5 border-t border-rose-500/35 pt-0.5 text-[9px] font-semibold leading-tight text-rose-100">
            ตัดช่วง {activeRemoved.start.toFixed(2)} – {activeRemoved.end.toFixed(2)} วิ.
          </div>
        ) : null}
      </div>
    </>
  );
}
