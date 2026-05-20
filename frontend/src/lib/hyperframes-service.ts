export const HYPERFRAMES_BASE_URL =
  process.env.HYPERFRAMES_BASE_URL ?? "http://localhost:8050";

export function hyperframesServiceUrl(path: string): string {
  const base = HYPERFRAMES_BASE_URL.replace(/\/$/, "");
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return `${base}${normalized}`;
}
