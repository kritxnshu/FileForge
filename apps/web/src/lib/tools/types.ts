export interface ToolResult {
  output: string;
  notices?: string[];
  /** For binary results (e.g. Base64 → file, QR PNG): bytes and suggested type. */
  bytes?: Uint8Array;
  mime?: string;
  /** Extra structured data for custom views (e.g. colour swatches). */
  data?: Record<string, unknown>;
}

export class ToolError extends Error {
  constructor(message: string, public where?: { line: number; column: number }) {
    super(message);
  }
}

export interface ToolInput {
  text: string;
  bytes?: Uint8Array; // when the user loaded a local file (never uploaded)
  fileName?: string;
  source: string;
  target: string;
  options: Record<string, unknown>;
}

export type ToolFn = (input: ToolInput) => ToolResult | Promise<ToolResult>;
