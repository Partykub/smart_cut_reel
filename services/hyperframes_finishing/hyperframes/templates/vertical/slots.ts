import type { SlotDefinition } from "../shared/types";

export const verticalSlots: SlotDefinition[] = [
  { key: "main_video", required: true, description: "Primary vertical clip" },
  { key: "intro_video", required: false, description: "Optional intro clip" },
  { key: "outro_video", required: false, description: "Optional outro clip" },
  { key: "logo_image", required: false, description: "Brand logo overlay" },
  { key: "subtitle_track", required: false, description: "Word-level subtitle track" }
];
