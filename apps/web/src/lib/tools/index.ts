// Client-side tool implementations, keyed by registry operation id.
// The *list* of tools comes from /api/capabilities; this only maps ids to code.

import { convertData } from "./data";
import { base64, codeFormat, csvToSql, htmlMarkdown, jsonFormat, timestamp, url } from "./text";
import type { ToolFn } from "./types";

export const TOOLS: Record<string, ToolFn> = {
  "dev.data_convert": ({ text, source, target, options }) => convertData(text, source, target, options),
  "dev.html_markdown": htmlMarkdown,
  "dev.json_format": jsonFormat,
  "dev.code_format": codeFormat,
  "dev.csv_to_sql": csvToSql,
  "dev.base64": base64,
  "dev.url": url,
  "dev.timestamp": timestamp,
};

/** Tools that can take a local file as input (read in the browser, never uploaded). */
export const FILE_INPUT = new Set(["dev.base64"]);

export { ToolError } from "./types";
export type { ToolInput, ToolResult } from "./types";
