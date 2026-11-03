// Conversion history and recent tools in localStorage. Metadata only — never file contents.

export interface HistoryEntry {
  jobId: string;
  at: number;
  fileName: string;
  operation: string;
  label: string;
  source: string;
  target: string;
  outputs: number;
  expiresAt: number | null;
  /** A tool (compress, reorder pages…): shown as its label rather than "to <format>". */
  tool?: boolean;
}

const KEY = "uc-history";
const RECENT = "uc-recent-tools";
const MAX = 50;

function read<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function write(key: string, v: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(v));
    window.dispatchEvent(new Event("uc-history"));
  } catch {
    /* storage unavailable or full */
  }
}

export function getHistory(): HistoryEntry[] {
  return read<HistoryEntry[]>(KEY, []);
}

export function addHistory(e: HistoryEntry) {
  const list = getHistory().filter((x) => x.jobId !== e.jobId);
  write(KEY, [e, ...list].slice(0, MAX));
}

export function clearHistory() {
  write(KEY, []);
  write(RECENT, []);
}

export function isExpired(e: HistoryEntry, now = Date.now() / 1000): boolean {
  return e.expiresAt != null && now > e.expiresAt;
}

export function getRecentTools(): { slug: string; title: string; href?: string }[] {
  return read(RECENT, []);
}

export function addRecentTool(t: { slug: string; title: string; href?: string }) {
  const list = getRecentTools().filter((x) => x.slug !== t.slug);
  write(RECENT, [t, ...list].slice(0, 8));
}
