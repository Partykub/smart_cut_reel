export type TemplateFamily = "vertical" | "horizontal";

export interface SlotDefinition {
  key: string;
  required: boolean;
  description: string;
}

export interface ThemeTokens {
  background: string;
  accent: string;
  subtitleBox: string;
  subtitleText: string;
  logoOpacity: number;
}

export interface TemplateDescriptor {
  family: TemplateFamily;
  variant: string;
  safeZoneProfile: string;
  slots: SlotDefinition[];
  theme: ThemeTokens;
}
