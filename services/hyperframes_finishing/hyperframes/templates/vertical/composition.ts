import { verticalSlots } from "./slots";
import { verticalTheme } from "./theme";
import type { TemplateDescriptor } from "../shared/types";

export const verticalTemplate: TemplateDescriptor = {
  family: "vertical",
  variant: "default",
  safeZoneProfile: "vertical_default",
  slots: verticalSlots,
  theme: verticalTheme
};
