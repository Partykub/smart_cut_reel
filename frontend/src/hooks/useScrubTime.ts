"use client";

import { useCallback, useState } from "react";

/** 0–1 position along a horizontal timeline, or null when pointer left. */
export function useScrubTime(totalSeconds: number) {
  const [ratio, setRatio] = useState<number | null>(null);

  const onMouseMove = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      const rect = event.currentTarget.getBoundingClientRect();
      const width = rect.width;
      if (width <= 0 || totalSeconds <= 0) return;
      const x = Math.min(Math.max(event.clientX - rect.left, 0), width);
      setRatio(x / width);
    },
    [totalSeconds],
  );

  const onMouseLeave = useCallback(() => {
    setRatio(null);
  }, []);

  const seconds = ratio != null && totalSeconds > 0 ? ratio * totalSeconds : null;

  return { ratio, seconds, onMouseMove, onMouseLeave };
}
