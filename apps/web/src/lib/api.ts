// Typed client for the FastAPI service. Everything the UI offers comes from /api/capabilities.

export type SupportLevel = "full" | "partial" | "experimental";

export interface Pair {
  source: string;
  target: string;
  support: SupportLevel;
  limitations: string[];
  slug: string;
  primary: boolean;
}

export interface JsonSchema {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  enum?: unknown[];
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number;
  pattern?: string;
  items?: JsonSchema;
  anyOf?: JsonSchema[];
  properties?: Record<string, JsonSchema>;
  required?: string[];
  maxLength?: number;
  "x-advanced"?: boolean;
  "x-widget"?: string;
  "x-targets"?: string[];
  "x-step"?: number;
  "x-unit"?: string;
  "x-placeholder"?: string;
  [k: string]: unknown;
}

export interface Operation {
  id: string;
  category: string;
  label: string;
  description: string;
  cardinality: "one_to_one" | "one_to_many" | "many_to_one" | "transform";
  runtime: "server" | "client";
  resource_class: "fast" | "heavy";
  support: SupportLevel;
  limitations: string[];
  options_schema: JsonSchema;
  min_inputs: number;
  combine_only: boolean;
  max_inputs: number | null;
  keywords: string[];
  pairs: Pair[];
}

export interface FormatInfo {
  label: string;
  family: string;
  exts: string[];
  mime: string;
}

export interface HubTool {
  slug: string;
  title: string;
  description: string;
  icon: string;
  group: string;
  op: string;
  target: string;
  sources: string[];
  support: SupportLevel;
  limitations: string[];
  options: Record<string, unknown>;
  special: string | null;
  cardinality: Operation["cardinality"];
}

export interface Hub {
  title: string;
  description: string;
  groups: { id: string; label: string }[];
  tools: HubTool[];
  not_offered: { title: string; reason: string }[];
}

export interface Capabilities {
  version: number;
  categories: { id: string; label: string }[];
  formats: Record<string, FormatInfo>;
  operations: Operation[];
  hubs?: Record<string, Hub>;
  limits: {
    max_file_size_mb: number;
    max_video_size_mb: number;
    max_batch_files: number;
    max_batch_total_mb: number;
    max_image_megapixels: number;
    retention_minutes: number;
    jobs_per_10min: number;
  };
}

export interface UploadedFile {
  id: string;
  name: string;
  size: number;
  format: string | null;
  format_label?: string;
  family?: string;
  warnings: string[];
  error?: string;
  info?: Record<string, unknown>;
  expires_at?: number;
}

export type JobState = "queued" | "running" | "succeeded" | "failed" | "cancelled" | "expired";

export interface JobOutput {
  index: number;
  name: string;
  format: string;
  size: number;
  label: string | null;
}

export interface Job {
  id: string;
  batch_id: string | null;
  operation: string;
  target: string;
  file_ids: string[];
  state: JobState;
  stage: string | null;
  progress: { done: number; total: number } | null;
  error: { code: string; message: string } | null;
  outputs: JobOutput[];
  notices: string[];
  warnings: string[];
  input_size: number;
  created_at: number;
  finished_at: number | null;
  expires_at: number | null;
}

export const TERMINAL: JobState[] = ["succeeded", "failed", "cancelled", "expired"];

export class ApiError extends Error {
  constructor(public status: number, message: string, public retryAfter?: number) {
    super(message);
  }
}

async function parse<T>(r: Response): Promise<T> {
  if (r.ok) return (await r.json()) as T;
  let message = `Request failed (${r.status}).`;
  try {
    const body = await r.json();
    message = body?.error?.message ?? message;
  } catch {
    /* non-JSON error */
  }
  const ra = r.headers.get("Retry-After");
  throw new ApiError(r.status, message, ra ? Number(ra) : undefined);
}

const opts: RequestInit = { credentials: "same-origin" };

export function serverApiBase(): string {
  return process.env.INTERNAL_API_URL ?? "http://127.0.0.1:8000";
}

export async function fetchCapabilities(base = ""): Promise<Capabilities> {
  return parse(await fetch(`${base}/api/capabilities`, { ...opts, cache: "no-store" }));
}

/** XHR so the UI can show real upload progress (bytes sent by the browser). */
export function uploadFiles(
  files: File[],
  onProgress: (loaded: number, total: number) => void,
  signal?: AbortSignal,
): Promise<UploadedFile[]> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    for (const f of files) form.append("files", f, f.name);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/uploads");
    xhr.withCredentials = true;
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded, e.total);
    xhr.onload = () => {
      let body: { files?: UploadedFile[]; error?: { message: string } } = {};
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* ignore */
      }
      if (xhr.status >= 200 && xhr.status < 300 && body.files) resolve(body.files);
      else {
        const ra = xhr.getResponseHeader("Retry-After");
        reject(new ApiError(xhr.status, body.error?.message ?? `Upload failed (${xhr.status}).`, ra ? Number(ra) : undefined));
      }
    };
    xhr.onerror = () => reject(new ApiError(0, "The upload was interrupted. Check your connection and try again."));
    xhr.onabort = () => reject(new ApiError(0, "Upload cancelled."));
    signal?.addEventListener("abort", () => xhr.abort());
    xhr.send(form);
  });
}

export async function createJobs(body: {
  file_ids: string[];
  operation: string;
  target: string | null;
  options: Record<string, unknown>;
  batch_id?: string;
}): Promise<{ batch_id: string; jobs: { id: string; file_ids: string[]; state: JobState }[] }> {
  return parse(
    await fetch("/api/jobs", {
      ...opts,
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
}

export async function getJob(id: string): Promise<Job> {
  return parse(await fetch(`/api/jobs/${id}`, opts));
}

export function watchJob(id: string, onJob: (j: Job) => void, onLost: () => void): () => void {
  const es = new EventSource(`/api/jobs/${id}/events`, { withCredentials: true });
  let done = false;
  es.addEventListener("job", (e) => {
    const j = JSON.parse((e as MessageEvent).data) as Job;
    onJob(j);
    if (TERMINAL.includes(j.state)) {
      done = true;
      es.close();
    }
  });
  es.onerror = () => {
    if (done) return;
    es.close();
    onLost();
  };
  return () => {
    done = true;
    es.close();
  };
}

export async function cancelJob(id: string): Promise<Job> {
  return parse(await fetch(`/api/jobs/${id}/cancel`, { ...opts, method: "POST" }));
}

export async function deleteJob(id: string): Promise<void> {
  await fetch(`/api/jobs/${id}`, { ...opts, method: "DELETE" });
}

export async function deleteUpload(id: string): Promise<void> {
  await fetch(`/api/uploads/${id}`, { ...opts, method: "DELETE" });
}

export const outputUrl = (jobId: string, n: number, inline = false) =>
  `/api/jobs/${jobId}/files/${n}${inline ? "?inline=1" : ""}`;
export const uploadRawUrl = (fileId: string) => `/api/uploads/${fileId}/raw?inline=1`;
export const batchZipUrl = (batchId: string) => `/api/batches/${batchId}/zip`;

export interface PageIndex {
  pages: number;
  thumbnails: string[];
  /** Displayed page sizes in points ([width, height]), rotation and crop applied. */
  sizes?: [number, number][];
}

/** A page rendered large for the page editors (0-based page index). */
export const pageViewUrl = (fileId: string, n: number) => `/api/uploads/${fileId}/view/${n}`;

export interface FormField {
  name: string;
  type: "text" | "checkbox" | "choice" | "radio" | "signature" | "button";
  value?: string | boolean;
  options?: string[];
  multiline?: boolean;
  multiselect?: boolean;
  required: boolean;
  read_only: boolean;
  widgets: { page: number; x: number; y: number; w: number; h: number }[];
}

export async function uploadFormFields(fileId: string): Promise<{ fields: FormField[] }> {
  return parse(await fetch(`/api/uploads/${fileId}/form`, opts));
}

export async function uploadPages(fileId: string): Promise<PageIndex> {
  return parse(await fetch(`/api/uploads/${fileId}/pages`, opts));
}

export async function outputPages(jobId: string, n: number): Promise<PageIndex> {
  return parse(await fetch(`/api/jobs/${jobId}/files/${n}/pages`, opts));
}

export interface TablePreview {
  sheet: string | null;
  rows: string[][];
  truncated: boolean;
}

/** First rows of a spreadsheet result (XLSX/XLS/ODS), read on the server in a sandboxed job process. */
export async function outputTable(jobId: string, n: number): Promise<TablePreview> {
  return parse(await fetch(`/api/jobs/${jobId}/files/${n}/table`, opts));
}
