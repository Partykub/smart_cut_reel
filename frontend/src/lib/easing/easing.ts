export type EasingName =
  | "linear"
  | "easeOutCubic"
  | "easeInOutCubic"
  | "easeInOutSine";

function clamp01(t: number): number {
  if (Number.isNaN(t)) return 0;
  if (t < 0) return 0;
  if (t > 1) return 1;
  return t;
}

export function linear(t: number): number {
  return clamp01(t);
}

export function easeOutCubic(t: number): number {
  const x = clamp01(t);
  const inv = 1 - x;
  return 1 - inv * inv * inv;
}

export function easeInOutCubic(t: number): number {
  const x = clamp01(t);
  if (x < 0.5) {
    return 4 * x * x * x;
  }
  const inv = -2 * x + 2;
  return 1 - (inv * inv * inv) / 2;
}

export function easeInOutSine(t: number): number {
  const x = clamp01(t);
  return -(Math.cos(Math.PI * x) - 1) / 2;
}

export const EASING_FUNCTIONS: Record<EasingName, (t: number) => number> = {
  linear,
  easeOutCubic,
  easeInOutCubic,
  easeInOutSine,
};

export function interpolate(
  start: number,
  end: number,
  t: number,
  easing: EasingName = "easeInOutCubic",
): number {
  const fn = EASING_FUNCTIONS[easing];
  if (!fn) {
    throw new Error(
      `Unknown easing '${String(easing)}'. Expected one of ${Object.keys(EASING_FUNCTIONS).join(", ")}.`,
    );
  }
  return start + (end - start) * fn(t);
}
