"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition, type FormEvent } from "react";

import { createJob } from "@/lib/api";

export function UploadForm() {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);

    if (!file) {
      setError("Please choose a video file first.");
      return;
    }

    startTransition(async () => {
      try {
        const formData = new FormData();
        formData.append("source", file);
        formData.append("created_by", "debug_frontend");
        const result = await createJob(formData);
        router.push(`/jobs/${result.job_id}`);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to create job.");
      }
    });
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="space-y-6 rounded-xl border border-zinc-800 bg-zinc-900/50 p-6 shadow-lg"
    >
      <div className="space-y-2">
        <label
          htmlFor="source"
          className="block text-sm font-medium text-zinc-300"
        >
          Source video
        </label>
        <input
          id="source"
          name="source"
          type="file"
          accept="video/*"
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          disabled={isPending}
          className="block w-full text-sm text-zinc-300 file:mr-4 file:rounded-md file:border-0 file:bg-zinc-100 file:px-4 file:py-2 file:text-sm file:font-medium file:text-zinc-900 hover:file:bg-zinc-200 disabled:opacity-50"
        />
        {file ? (
          <p className="text-xs text-zinc-500">
            {file.name} · {formatMegabytes(file.size)} MB
          </p>
        ) : null}
      </div>

      {error ? (
        <p
          role="alert"
          className="rounded-md border border-red-900/40 bg-red-950/40 px-3 py-2 text-sm text-red-300"
        >
          {error}
        </p>
      ) : null}

      <button
        type="submit"
        disabled={!file || isPending}
        className="inline-flex items-center justify-center rounded-md bg-emerald-500 px-4 py-2 text-sm font-medium text-zinc-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:bg-zinc-700 disabled:text-zinc-400"
      >
        {isPending ? "Creating job..." : "Create job"}
      </button>
    </form>
  );
}

function formatMegabytes(bytes: number): string {
  return (bytes / (1024 * 1024)).toFixed(2);
}
