export const ORCHESTRATOR_BASE_URL =
  process.env.ORCHESTRATOR_BASE_URL ?? "http://localhost:8000";

export function orchestratorUrl(path: string): string {
  const base = ORCHESTRATOR_BASE_URL.replace(/\/$/, "");
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return `${base}${normalized}`;
}
