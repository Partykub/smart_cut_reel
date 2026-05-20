"use client";

import { startTransition, useState } from "react";
import { useRouter } from "next/navigation";

import { renderHyperframesProjectDraft } from "@/lib/hyperframes-api";

export function HyperframesRenderDraftButton({
  projectId,
  revisionId,
}: {
  projectId: string;
  revisionId: string;
}) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  return (
    <div className="space-y-2">
      <button
        type="button"
        disabled={isSubmitting}
        onClick={() => {
          setIsSubmitting(true);
          setError(null);
          void renderHyperframesProjectDraft(projectId, revisionId)
            .then((job) => {
              startTransition(() => {
                router.push(`/hyperframes/jobs/${job.job_id}`);
              });
            })
            .catch((nextError: unknown) => {
              setError(nextError instanceof Error ? nextError.message : String(nextError));
              setIsSubmitting(false);
            });
        }}
        className="inline-flex rounded-lg bg-emerald-400 px-4 py-2 text-sm font-medium text-zinc-950 hover:bg-emerald-300 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {isSubmitting ? "Starting draft render..." : "Render draft"}
      </button>
      {error ? <p className="text-xs text-red-300">{error}</p> : null}
    </div>
  );
}