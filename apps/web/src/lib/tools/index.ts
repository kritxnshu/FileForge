// Client-side tool implementations, keyed by registry operation id.
// The *list* of tools comes from /api/capabilities; this only maps ids to code.

import { convertData } from "./data";
import { base64, codeFormat, csvToSql, htmlMarkdown, jsonFormat, timestamp, url } from "./text";
import type { ToolFn } from "./types";
import { byteSizes, color, imageBase64, qr, units } from "./utils";

export const TOOLS: Record<string, ToolFn> = {
  "dev.data_convert": ({ text, source, target, options }) => convertData(text, source, target, options),
  "dev.html_markdown": htmlMarkdown,
  "dev.json_format": jsonFormat,
  "dev.code_format": codeFormat,
  "dev.csv_to_sql": csvToSql,
  "dev.base64": base64,
  "dev.url": url,
  "dev.timestamp": timestamp,
  "util.image_base64": imageBase64,
  "util.color": color,
  "util.units": units,
  "util.bytes": byteSizes,
  "util.qr": qr,
};

/** Tools that can take a local file as input (read in the browser, never uploaded). */
export const FILE_INPUT = new Set(["dev.base64", "util.image_base64"]);
/** Tools whose input must be a local file (no text box). */
export const FILE_ONLY = new Set(["util.image_base64"]);

export { ToolError } from "./types";
export type { ToolInput, ToolResult } from "./types";
