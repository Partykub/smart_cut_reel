import { horizontalSlots } from "./slots";
import { horizontalTheme } from "./theme";
import type { TemplateDescriptor } from "../shared/types";

export const horizontalTemplate: TemplateDescriptor = {
  family: "horizontal",
  variant: "default",
  safeZoneProfile: "horizontal_default",
  slots: horizontalSlots,
  theme: horizontalTheme
};
