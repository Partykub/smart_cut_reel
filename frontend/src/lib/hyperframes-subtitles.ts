import type { HyperframesSubtitleDocument, HyperframesSubtitleSegment, HyperframesSubtitleWord } from "./hyperframes-types";

const SUPPORTED_SUBTITLE_EXTENSIONS = [".json", ".srt"] as const;

export async function validateHyperframesSubtitleFile(file: File): Promise<HyperframesSubtitleDocument> {
  const extension = getFileExtension(file.name);
  if (!SUPPORTED_SUBTITLE_EXTENSIONS.includes(extension as (typeof SUPPORTED_SUBTITLE_EXTENSIONS)[number])) {
    throw new Error("Subtitle file must be .json or .srt");
  }

  const content = await file.text();
  if (!content.trim()) {
    throw new Error("Subtitle file is empty");
  }

  if (extension === ".srt") {
    return {
      segments: parseSrtSubtitles(content),
      words: [],
    };
  }

  let payload: unknown;
  try {
    payload = JSON.parse(content) as unknown;
  } catch {
    throw new Error("Subtitle JSON is invalid");
  }
  return parseJsonSubtitles(payload);
}

export function summarizeHyperframesSubtitleDocument(document: HyperframesSubtitleDocument): string {
  const segmentCount = document.segments.length;
  const wordCount = countSubtitleWords(document);
  if (wordCount > 0 && segmentCount > 0) {
    return `${segmentCount} segments, ${wordCount} timed words`;
  }
  if (wordCount > 0) {
    return `${wordCount} timed words`;
  }
  return `${segmentCount} phrase-level segments`;
}

export function getHyperframesSubtitleHelpText(): string {
  return "Use JSON with `words` or `segments`, or upload SRT as phrase-level fallback.";
}

function parseJsonSubtitles(payload: unknown): HyperframesSubtitleDocument {
  if (Array.isArray(payload)) {
    if (payload.length > 0 && isRecord(payload[0]) && "word" in payload[0]) {
      return { words: payload.map(parseWord), segments: [] };
    }
    return { segments: payload.map(parseSegment), words: [] };
  }

  if (!isRecord(payload)) {
    throw new Error("Subtitle JSON must be an object or list");
  }

  const words = readArray(payload.words, "words").map(parseWord);
  const segments = readArray(payload.segments, "segments").map(parseSegment);

  if (words.length === 0 && segments.length === 0) {
    throw new Error("Subtitle payload must contain at least one word or segment");
  }

  return { words, segments };
}

function parseSegment(value: unknown): HyperframesSubtitleSegment {
  if (!isRecord(value)) {
    throw new Error("Subtitle segments must be objects");
  }

  const nestedWords = readArray(value.words, "words").map(parseWord);
  if (nestedWords.length > 0) {
    const start = value.start == null ? null : parseTimestamp(value.start, "segment.start");
    const end = value.end == null ? null : parseTimestamp(value.end, "segment.end");
    if (start != null && nestedWords[0]!.start < start) {
      throw new Error("Subtitle words must start inside their segment range");
    }
    if (end != null && nestedWords[nestedWords.length - 1]!.end > end) {
      throw new Error("Subtitle words must end inside their segment range");
    }
    return {
      text: typeof value.text === "string" ? value.text : null,
      start,
      end,
      words: nestedWords,
    };
  }

  const text = typeof value.text === "string" ? value.text.trim() : "";
  if (!text) {
    throw new Error("Subtitle segment text is required when no words are provided");
  }

  const start = parseTimestamp(value.start, "segment.start");
  const end = parseTimestamp(value.end, "segment.end");
  validateTimeRange(start, end);
  return { text, start, end, words: [] };
}

function parseWord(value: unknown): HyperframesSubtitleWord {
  if (!isRecord(value)) {
    throw new Error("Subtitle words must be objects");
  }

  const textValue = typeof value.text === "string" ? value.text : typeof value.word === "string" ? value.word : "";
  const text = textValue.trim();
  if (!text) {
    throw new Error("Subtitle word text is required");
  }

  const start = parseTimestamp(value.start, "word.start");
  const end = parseTimestamp(value.end, "word.end");
  validateTimeRange(start, end);
  return { text, start, end };
}

function parseSrtSubtitles(content: string): HyperframesSubtitleSegment[] {
  const blocks = content.replace(/\r\n/g, "\n").split("\n\n").map((block) => block.trim()).filter(Boolean);
  return blocks.map((block) => {
    const lines = block.split("\n").map((line) => line.trim()).filter(Boolean);
    if (lines.length < 2) {
      throw new Error("Invalid SRT block");
    }
    const timingLine = lines[1]?.includes("-->") ? lines[1] : lines[0];
    if (!timingLine.includes("-->")) {
      throw new Error("Invalid SRT timing line");
    }
    const [startRaw, endRaw] = timingLine.split("-->").map((part) => part.trim());
    const textLines = timingLine === lines[1] ? lines.slice(2) : lines.slice(1);
    const text = textLines.join(" ").trim();
    if (!text) {
      throw new Error("SRT cue text is required");
    }
    const start = parseSrtTimestamp(startRaw);
    const end = parseSrtTimestamp(endRaw);
    validateTimeRange(start, end);
    return { text, start, end, words: [] };
  });
}

function parseSrtTimestamp(value: string): number {
  const [timePart, millisPart] = value.split(",");
  if (!timePart || !millisPart) {
    throw new Error("Invalid SRT timestamp");
  }
  const [hours, minutes, seconds] = timePart.split(":").map((part) => Number.parseInt(part, 10));
  const millis = Number.parseInt(millisPart, 10);
  if ([hours, minutes, seconds, millis].some((part) => Number.isNaN(part))) {
    throw new Error("Invalid SRT timestamp");
  }
  return hours * 3600 + minutes * 60 + seconds + millis / 1000;
}

function countSubtitleWords(document: HyperframesSubtitleDocument): number {
  const nestedWordCount = document.segments.reduce((count, segment) => count + segment.words.length, 0);
  return document.words.length + nestedWordCount;
}

function parseTimestamp(value: unknown, label: string): number {
  if (typeof value !== "number") {
    throw new Error(`Subtitle ${label} must be numeric`);
  }
  if (value < 0) {
    throw new Error(`Subtitle ${label} must be non-negative`);
  }
  return value;
}

function validateTimeRange(start: number, end: number): void {
  if (end <= start) {
    throw new Error("Subtitle cue end time must be greater than start time");
  }
}

function readArray(value: unknown, label: string): unknown[] {
  if (value == null) {
    return [];
  }
  if (!Array.isArray(value)) {
    throw new Error(`Subtitle ${label} must be an array`);
  }
  return value;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function getFileExtension(filename: string): string {
  const index = filename.lastIndexOf(".");
  return index >= 0 ? filename.slice(index).toLowerCase() : "";
}