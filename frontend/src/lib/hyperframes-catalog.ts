import type { HyperframesTemplateFamily } from "@/lib/hyperframes-types";

export type HyperframesThemeId = "default" | "glassmorphism" | "bold";
export type HyperframesTemplateVariant =
  | "gravitational-lens"
  | "vfx-text-cursor"
  | "yt-lower-third"
  | "ui-3d-reveal";

export interface HyperframesTemplatePreset {
  id: string;
  title: string;
  subtitle: string;
  durationLabel: string;
  canvasLabel: string;
  previewVideoSrc: string;
  previewPosterSrc: string;
  installCommand: string;
  introPreset: string | null;
  mainPreset: string | null;
  outroPreset: string | null;
  autoGenerateIntro: boolean;
  autoGenerateOutro: boolean;
  usesLogoAsIntroSubject: boolean;
  templateFamily: HyperframesTemplateFamily;
  templateVariant: HyperframesTemplateVariant;
  brandTheme: HyperframesThemeId;
  subtitleTheme: HyperframesThemeId;
  suggestedProjectName: string;
  accent: string;
  background: string;
  overlay?: string;
  previewAlign?: "left" | "center" | "right";
}

export const HYPERFRAMES_TEMPLATE_PRESETS: HyperframesTemplatePreset[] = [
  {
    id: "gravitational-lens",
    title: "Gravitational Lens",
    subtitle: "Shader transition with gravitational lensing distortion.",
    durationLabel: "4s",
    canvasLabel: "1080x1920",
    previewVideoSrc:
      "https://static.heygen.ai/hyperframes-oss/docs/images/catalog/blocks/gravitational-lens.mp4",
    previewPosterSrc:
      "https://static.heygen.ai/hyperframes-oss/docs/images/catalog/blocks/gravitational-lens.png",
    installCommand: "npx hyperframes add gravitational-lens",
    introPreset: null,
    mainPreset: "gravitational-lens",
    outroPreset: null,
    autoGenerateIntro: false,
    autoGenerateOutro: false,
    usesLogoAsIntroSubject: false,
    templateFamily: "horizontal",
    templateVariant: "gravitational-lens",
    brandTheme: "bold",
    subtitleTheme: "default",
    suggestedProjectName: "Gravitational lens opener",
    accent: "#76f7c5",
    background:
      "radial-gradient(circle at 20% 20%, rgba(118,247,197,0.22), transparent 32%), radial-gradient(circle at 82% 18%, rgba(86,100,255,0.28), transparent 28%), linear-gradient(135deg, #09112b 0%, #070b18 48%, #0b122d 100%)",
    overlay:
      "linear-gradient(180deg, rgba(255,255,255,0.04), transparent 26%, rgba(118,247,197,0.08) 100%)",
    previewAlign: "left",
  },
  {
    id: "vfx-text-cursor",
    title: "VFX Text Cursor",
    subtitle: "Dramatic text reveal with cursor glow and chromatic shadow rays.",
    durationLabel: "8s",
    canvasLabel: "1920x1080",
    previewVideoSrc:
      "https://static.heygen.ai/hyperframes-oss/docs/images/catalog/blocks/vfx-text-cursor.mp4",
    previewPosterSrc:
      "https://static.heygen.ai/hyperframes-oss/docs/images/catalog/blocks/vfx-text-cursor.png",
    installCommand: "npx hyperframes add vfx-text-cursor",
    introPreset: "vfx-text-cursor",
    mainPreset: null,
    outroPreset: "vfx-text-cursor-outro",
    autoGenerateIntro: true,
    autoGenerateOutro: true,
    usesLogoAsIntroSubject: true,
    templateFamily: "horizontal",
    templateVariant: "vfx-text-cursor",
    brandTheme: "glassmorphism",
    subtitleTheme: "glassmorphism",
    suggestedProjectName: "VFX text cursor reveal",
    accent: "#3c2aff",
    background:
      "radial-gradient(circle at 68% 24%, rgba(60,42,255,0.12), transparent 26%), radial-gradient(circle at 22% 72%, rgba(255,184,90,0.16), transparent 28%), linear-gradient(135deg, #f4efe7 0%, #f8f4ef 54%, #efe7ff 100%)",
    overlay:
      "linear-gradient(120deg, rgba(255,255,255,0.55), rgba(255,255,255,0.06))",
    previewAlign: "center",
  },
  {
    id: "yt-lower-third",
    title: "YouTube Lower Third",
    subtitle: "Animated YouTube subscribe lower third with avatar and channel info.",
    durationLabel: "4.5s",
    canvasLabel: "1920x1080",
    previewVideoSrc:
      "https://static.heygen.ai/hyperframes-oss/docs/images/catalog/blocks/yt-lower-third.mp4",
    previewPosterSrc:
      "https://static.heygen.ai/hyperframes-oss/docs/images/catalog/blocks/yt-lower-third.png",
    installCommand: "npx hyperframes add yt-lower-third",
    introPreset: null,
    mainPreset: "yt-lower-third",
    outroPreset: null,
    autoGenerateIntro: false,
    autoGenerateOutro: false,
    usesLogoAsIntroSubject: false,
    templateFamily: "horizontal",
    templateVariant: "yt-lower-third",
    brandTheme: "bold",
    subtitleTheme: "glassmorphism",
    suggestedProjectName: "YouTube lower third promo",
    accent: "#ff3b57",
    background:
      "radial-gradient(circle at 18% 16%, rgba(255,59,87,0.22), transparent 24%), radial-gradient(circle at 80% 18%, rgba(92,48,255,0.24), transparent 28%), linear-gradient(135deg, #0a0a12 0%, #090b10 50%, #0d1020 100%)",
    overlay:
      "linear-gradient(180deg, rgba(255,255,255,0.04), rgba(255,255,255,0))",
    previewAlign: "right",
  },
  {
    id: "ui-3d-reveal",
    title: "3D UI Reveal",
    subtitle: "Perspective 3D reveal animation for UI elements.",
    durationLabel: "13s",
    canvasLabel: "1920x1080",
    previewVideoSrc:
      "https://static.heygen.ai/hyperframes-oss/docs/images/catalog/blocks/ui-3d-reveal.mp4",
    previewPosterSrc:
      "https://static.heygen.ai/hyperframes-oss/docs/images/catalog/blocks/ui-3d-reveal.png",
    installCommand: "npx hyperframes add ui-3d-reveal",
    introPreset: "ui-3d-reveal",
    mainPreset: null,
    outroPreset: "ui-3d-reveal-outro",
    autoGenerateIntro: true,
    autoGenerateOutro: true,
    usesLogoAsIntroSubject: true,
    templateFamily: "horizontal",
    templateVariant: "ui-3d-reveal",
    brandTheme: "default",
    subtitleTheme: "default",
    suggestedProjectName: "3D UI reveal showcase",
    accent: "#ff5f8f",
    background:
      "radial-gradient(circle at 18% 16%, rgba(255,95,143,0.22), transparent 24%), radial-gradient(circle at 80% 18%, rgba(92,48,255,0.24), transparent 28%), linear-gradient(135deg, #0a0a12 0%, #090b10 50%, #0d1020 100%)",
    overlay:
      "linear-gradient(180deg, rgba(255,255,255,0.04), rgba(255,255,255,0))",
    previewAlign: "right",
  },
];

export function getHyperframesTemplatePreset(
  presetId: string | undefined,
): HyperframesTemplatePreset | null {
  if (!presetId) {
    return null;
  }
  return HYPERFRAMES_TEMPLATE_PRESETS.find((preset) => preset.id === presetId) ?? null;
}