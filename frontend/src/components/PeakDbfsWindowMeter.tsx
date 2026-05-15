"use client";

import { peakDbfsWithinWindowRounded } from "@/lib/audioDbfsGuide";

function clamp(n: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, n));
}

function pctOnScale(db: number, minDb: number, maxDb: number): number {
  if (!(Number.isFinite(db) && Number.isFinite(minDb) && Number.isFinite(maxDb)) || maxDb <= minDb) {
    return 50;
  }
  return clamp(((db - minDb) / (maxDb - minDb)) * 100, 0, 100);
}

/**
 * Horizontal dBFS scale with a shaded “in window” band and markers for
 * astats overall peak before / after peak-force (same semantics as backend).
 */
export function PeakDbfsWindowMeter({
  lowDbfs,
  highDbfs,
  preDbfs,
  postDbfs,
}: {
  lowDbfs: number;
  highDbfs: number;
  preDbfs: number | null | undefined;
  postDbfs: number | null | undefined;
}) {
  const pre = typeof preDbfs === "number" && Number.isFinite(preDbfs) ? preDbfs : null;
  const post = typeof postDbfs === "number" && Number.isFinite(postDbfs) ? postDbfs : null;
  const showPreMarker = pre != null && post != null && Math.abs(pre - post) > 0.05;

  const pad = 4;
  const minDb = Math.min(lowDbfs - pad, ...(pre != null ? [pre] : []), ...(post != null ? [post] : []), lowDbfs, -48);
  const maxDb = Math.max(highDbfs + pad, ...(pre != null ? [pre] : []), ...(post != null ? [post] : []), highDbfs, -4);

  const wx0 = pctOnScale(lowDbfs, minDb, maxDb);
  const wx1 = pctOnScale(highDbfs, minDb, maxDb);
  const bandLeft = Math.min(wx0, wx1);
  const bandWidth = Math.max(Math.abs(wx1 - wx0), 3);

  const postInWindowRounded =
    post != null && peakDbfsWithinWindowRounded(post, lowDbfs, highDbfs, 3);
  const postDisplayDb =
    post != null && postInWindowRounded ? Number(post.toFixed(3)) : post;
  const postOnScaleDb =
    postDisplayDb != null && postInWindowRounded
      ? Math.min(postDisplayDb, highDbfs)
      : postDisplayDb;

  const prePct = pre != null ? pctOnScale(pre, minDb, maxDb) : null;
  let postPct = postOnScaleDb != null ? pctOnScale(postOnScaleDb, minDb, maxDb) : null;
  if (postPct != null && postInWindowRounded) {
    const hiPct = pctOnScale(highDbfs, minDb, maxDb);
    if (Math.abs(postPct - hiPct) < 1.2) postPct = hiPct;
  }

  return (
    <div className="rounded-lg border border-zinc-800/90 bg-zinc-950/80 px-3 py-2.5">
      <p className="text-[11px] font-medium text-zinc-400">
        Peak (dBFS) เทียบช่วงที่ตั้ง — สเกลเดียวกับค่า astats overall
      </p>
      <p className="mt-0.5 text-[10px] leading-snug text-zinc-600">
        แถบเขียว = ช่วงที่ตั้งไว้ [{lowDbfs.toFixed(1)}, {highDbfs.toFixed(1)}] dBFS ·
        {showPreMarker ? (
          <>จุดม่วง = ก่อนปรับ peak-force · จุดส้ม = หลังปรับ (ไฟล์ที่ mux)</>
        ) : post != null ? (
          <>
            จุดส้ม = หลังปรับ (ไฟล์ที่ mux) — ไม่แสดงจุดม่วงเมื่อไม่มีค่าก่อนปรับหรือก่อน/หลังใกล้กันมาก
          </>
        ) : null}
      </p>
      <div className="relative mt-2 h-8 w-full select-none">
        <div
          className="absolute inset-x-0 top-1/2 h-2.5 -translate-y-1/2 rounded-full bg-zinc-800/90"
          aria-hidden
        />
        <div
          className="absolute top-1/2 h-2.5 -translate-y-1/2 rounded-full bg-emerald-900/55 ring-1 ring-emerald-700/35"
          style={{ left: `${bandLeft}%`, width: `${bandWidth}%` }}
          title={`ช่วงเป้า ${lowDbfs}…${highDbfs} dBFS`}
        />
        {prePct != null && showPreMarker ? (
          <div
            className="absolute top-0 z-10 flex -translate-x-1/2 flex-col items-center"
            style={{ left: `${prePct}%` }}
            title={`ก่อนปรับ peak-force: ${pre!.toFixed(2)} dBFS`}
          >
            <span className="h-0 w-0 border-x-[5px] border-x-transparent border-b-[6px] border-b-violet-400" />
            <span className="mt-0.5 h-5 w-0.5 rounded-full bg-violet-400/90" />
          </div>
        ) : null}
        {postPct != null ? (
          <div
            className="absolute bottom-0 z-10 flex -translate-x-1/2 flex-col-reverse items-center"
            style={{ left: `${postPct}%` }}
            title={`หลังปรับ (สุดท้าย): ${postDisplayDb != null ? postDisplayDb.toFixed(3) : post!.toFixed(2)} dBFS`}
          >
            <span className="h-0 w-0 border-x-[5px] border-x-transparent border-t-[6px] border-t-amber-400" />
            <span className="mb-0.5 h-5 w-0.5 rounded-full bg-amber-400/90" />
          </div>
        ) : null}
      </div>
      <div className="mt-1 flex justify-between font-mono text-[10px] text-zinc-500">
        <span>{minDb.toFixed(0)} dBFS</span>
        <span>{maxDb.toFixed(0)} dBFS</span>
      </div>
    </div>
  );
}
