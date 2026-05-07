import type { ArtifactEntry, JobPaths } from "@/lib/types";

export function ArtifactList({
  artifacts,
  paths,
}: {
  artifacts: Record<string, ArtifactEntry>;
  paths: JobPaths;
}) {
  const entries = Object.entries(artifacts);

  return (
    <section className="space-y-3">
      <h2 className="text-sm font-medium uppercase tracking-widest text-zinc-400">
        Artifacts
      </h2>

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
