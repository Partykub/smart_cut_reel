import { horizontalTemplate } from "../templates/horizontal/composition";
import { verticalTemplate } from "../templates/vertical/composition";
import { validateAssets, type RenderAssetMap } from "./validate_assets";

export interface RenderJobInput {
  template_family: "vertical" | "horizontal";
  template_variant: string;
  assets: RenderAssetMap;
  output_path: string;
}

export function resolveTemplate(input: RenderJobInput) {
  return input.template_family === "vertical" ? verticalTemplate : horizontalTemplate;
}

export async function renderJob(input: RenderJobInput): Promise<{
  template_family: "vertical" | "horizontal";
  template_variant: string;
  output_path: string;
}> {
  validateAssets(input.assets);
  const template = resolveTemplate(input);
  return {
    template_family: template.family,
    template_variant: input.template_variant,
    output_path: input.output_path
  };
}
