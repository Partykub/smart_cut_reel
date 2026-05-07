import {
  STEP_ORDER,
  type ServiceStatus,
  type StepStatus,
} from "@/lib/types";

const STATUS_BADGE: Record<StepStatus, string> = {
  pending: "border-zinc-700 bg-zinc-900 text-zinc-400",
  running: "border-sky-700 bg-sky-950/60 text-sky-200",
  success: "border-emerald-700 bg-emerald-950/60 text-emerald-200",
  failed: "border-red-800 bg-red-950/60 text-red-200",
};

export function StatusBoard({ status }: { status: ServiceStatus }) {
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-sm font-medium uppercase tracking-widest text-zinc-400">
          Pipeline
        </h2>
        <span
          className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs ${STATUS_BADGE[status.status]}`}
        >
          {status.status}
        </span>
        {status.current_step ? (
          <span className="text-xs text-zinc-500">
            current:{" "}
            <span className="font-mono text-zinc-300">
              {status.current_step}
            </span>
          </span>
        ) : null}
        <span className="text-xs text-zinc-600">
          updated {formatTime(status.updated_at)}
        </span>
      </div>

      <ol className="space-y-2">
        {STEP_ORDER.map((step, index) => {
          const state = status.steps[step];
          const isCurrent = status.current_step === step;
          return (
            <li
              key={step}
              className={`flex flex-wrap items-center justify-between gap-3 rounded-md border px-3 py-2 ${STATUS_BADGE[state.status]} ${
                isCurrent ? "ring-1 ring-sky-500/50" : ""
              }`}
            >
              <div className="flex items-center gap-3">
                <span className="font-mono text-xs text-zinc-500">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <span className="font-mono text-sm">{step}</span>
              </div>
              <div className="flex flex-wrap items-center gap-3 text-xs">
                <span className="font-medium uppercase tracking-wider">
                  {state.status}
                </span>
                {state.started_at ? (
                  <span className="text-zinc-500">
                    start {formatTime(state.started_at)}
                  </span>
                ) : null}
                {state.finished_at ? (
                  <span className="text-zinc-500">
                    end {formatTime(state.finished_at)}
                  </span>
                ) : null}
              </div>
            </li>
          );
        })}
      </ol>

      {status.warnings.length > 0 ? (
        <details
          open
          className="rounded-md border border-amber-900/40 bg-amber-950/30 p-3"
        >
          <summary className="cursor-pointer text-sm font-medium text-amber-200">
            Warnings ({status.warnings.length})
          </summary>
          <ul className="mt-2 space-y-1 text-sm text-amber-100">
            {status.warnings.map((warning, idx) => (
              <li key={`${warning.code}-${idx}`} className="font-mono">
                <span className="text-amber-300">[{warning.step}]</span>{" "}
                {warning.code}: {warning.message}
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      {status.errors.length > 0 ? (
        <div className="rounded-md border border-red-900/40 bg-red-950/40 p-3">
          <p className="text-sm font-medium text-red-200">Errors</p>
          <ul className="mt-2 space-y-1 text-sm text-red-100">
            {status.errors.map((message, idx) => (
              <li key={idx} className="font-mono">
                {message}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString();
}
