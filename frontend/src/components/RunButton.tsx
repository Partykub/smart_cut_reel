"use client";

import { useTransition } from "react";

import { runJob } from "@/lib/api";
import type { OverallStatus } from "@/lib/types";

export function RunButton({
  jobId,
  status,
  onRan,
}: {
  jobId: string;
  status: OverallStatus;
  onRan: () => void | Promise<void>;
}) {
  const [isPending, startTransition] = useTransition();

  const handleClick = () => {
    startTransition(async () => {
      try {
        await runJob(jobId);
      } finally {
        await onRan();
      }
    });
  };

  const isRunning = status === "running";
  const disabled = isPending || isRunning;
  const label = isPending
    ? "Triggering..."
    : isRunning
      ? "Running..."
      : status === "success"
        ? "Run again"
        : "Run pipeline";

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={disabled}
      className="inline-flex items-center justify-center rounded-md bg-emerald-500 px-4 py-2 text-sm font-medium text-zinc-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:bg-zinc-700 disabled:text-zinc-400"
    >
      {label}
    </button>
  );
}
