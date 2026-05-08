import type { ArtifactEntry, JobPaths, ServiceStatus, StepState } from "@/lib/types";

export function ArtifactList({
  artifacts,
  paths,
  serviceStatus,
}: {
  artifacts: Record<string, ArtifactEntry>;
  paths: JobPaths;
  serviceStatus: ServiceStatus;
}) {
  const entries = Object.entries(artifacts);
  const totalDuration = getTotalDuration(serviceStatus);

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-medium uppercase tracking-widest text-zinc-400">
          Artifacts
        </h2>
        <p className="text-xs text-zinc-500">
          Total time{" "}
          <span className="font-mono text-zinc-300">
            {formatDuration(totalDuration)}
          </span>
        </p>
      </div>

      {entries.length === 0 ? (
        <p className="text-sm text-zinc-500">
          No artifacts yet — run the pipeline to populate this list.
        </p>
      ) : (
        <ul className="divide-y divide-zinc-800 rounded-md border border-zinc-800">
          {entries.map(([key, value]) => (
            <li
              key={key}
              className="flex flex-wrap items-baseline justify-between gap-2 px-4 py-3"
            >
              <div>
                <p className="font-mono text-sm text-zinc-200">{key}</p>
                <p className="font-mono text-xs text-zinc-500">
                  {value.object_key}
                </p>
              </div>
              <div className="text-right text-xs text-zinc-500">
                <p>
                  by{" "}
                  <span className="font-mono text-zinc-300">
                    {value.produced_by}
                  </span>
                </p>
                <p>
                  service time{" "}
                  <span className="font-mono text-zinc-300">
                    {formatDuration(getStepDuration(serviceStatus.steps[value.produced_by]))}
                  </span>
                </p>
                {typeof value.size_bytes === "number" ? (
                  <p>{formatBytes(value.size_bytes)}</p>
                ) : null}
                <p>{formatTime(value.created_at)}</p>
              </div>
            </li>
          ))}
        </ul>
      )}

      <details className="rounded-md border border-zinc-800 bg-zinc-900/40 p-3 text-xs text-zinc-400">
        <summary className="cursor-pointer text-zinc-300">
          Object paths
        </summary>
        <pre className="mt-2 overflow-x-auto whitespace-pre-wrap font-mono text-zinc-400">
          {JSON.stringify(paths, null, 2)}
        </pre>
      </details>
    </section>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString();
}

function getStepDuration(step: StepState | undefined): number | null {
  if (!step?.started_at || !step.finished_at) return null;

  const startedAt = new Date(step.started_at).getTime();
  const finishedAt = new Date(step.finished_at).getTime();

  if (Number.isNaN(startedAt) || Number.isNaN(finishedAt) || finishedAt < startedAt) {
    return null;
  }

  return finishedAt - startedAt;
}

function getTotalDuration(serviceStatus: ServiceStatus): number | null {
  const durations = Object.values(serviceStatus.steps)
    .map((step) => getStepDuration(step))
    .filter((duration): duration is number => duration !== null);

  if (durations.length === 0) {
    return null;
  }

  return durations.reduce((sum, duration) => sum + duration, 0);
}

function formatDuration(durationMs: number | null): string {
  if (durationMs === null) {
    return "--";
  }

  const totalSeconds = durationMs / 1000;

  if (totalSeconds < 1) {
    return `${Math.round(durationMs)} ms`;
  }

  if (totalSeconds < 60) {
    return `${totalSeconds.toFixed(1)} s`;
  }

  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}m ${seconds.toFixed(1)}s`;
}
