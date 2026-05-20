export interface RenderAssetMap {
  source_video: string;
  intro_video?: string | null;
  outro_video?: string | null;
  logo_image?: string | null;
  subtitle_file?: string | null;
}

export function validateAssets(assets: RenderAssetMap): void {
  if (!assets.source_video) {
    throw new Error("source_video is required");
  }
}
