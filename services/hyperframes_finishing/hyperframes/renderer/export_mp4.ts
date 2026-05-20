export interface ExportMp4Input {
  outputPath: string;
}

export async function exportMp4(_input: ExportMp4Input): Promise<void> {
  throw new Error(
    "Real Hyperframes export is not wired yet. Replace the mock executor with a runtime bridge to this module."
  );
}
