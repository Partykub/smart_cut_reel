import type { CutPlanSegment } from "@/lib/types";

/** Gaps between keep segments on the source timeline (treated as removed / dead-air regions). */
export function removedGapsFromKeepSegments(
  segments: CutPlanSegment[],
  totalSeconds: number,
): { start: number; end: number }[] {
  const t = Math.max(totalSeconds, 1e-6);
  if (!segments.length) {
    return [];
  }
  const sorted = [...segments].sort((a, b) => a.source_start - b.source_start);
  const out: { start: number; end: number }[] = [];
  let cursor = 0;
  for (const s of sorted) {
    if (s.source_start > cursor) {
      out.push({ start: cursor, end: Math.min(s.source_start, t) });
    }
    cursor = Math.max(cursor, s.source_end);
  }
  if (cursor < t) {
    out.push({ start: cursor, end: t });
  }
  return out.filter((x) => x.end - x.start > 1e-4);
}
