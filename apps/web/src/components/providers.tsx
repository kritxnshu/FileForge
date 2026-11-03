"use client";

import { MotionConfig } from "motion/react";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ApiError, fetchCapabilities, uploadFiles, type Capabilities, type UploadedFile } from "@/lib/api";

// ---------------------------------------------------------------------------
// capabilities

interface CapsState {
  caps: Capabilities | null;
  error: string | null;
  reload: () => void;
}

const CapsCtx = createContext<CapsState>({ caps: null, error: null, reload: () => {} });

export function CapabilitiesProvider({ initial, children }: { initial: Capabilities | null; children: ReactNode }) {
  const [caps, setCaps] = useState<Capabilities | null>(initial);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    fetchCapabilities()
      .then((c) => {
        setCaps(c);
        setError(null);
      })
      .catch(() => setError("We couldn't reach the conversion service. Check your connection and reload the page."));
  }, []);
  useEffect(() => {
    if (!initial) load();
  }, [initial, load]);
  return <CapsCtx.Provider value={{ caps, error, reload: load }}>{children}</CapsCtx.Provider>;
}

export const useCaps = () => useContext(CapsCtx);

// ---------------------------------------------------------------------------
// workspace files (shared between the home drop zone and the workspace)

export interface Item {
  key: string;
  name: string;
  size: number;
  status: "uploading" | "ready" | "rejected";
  progress: number; // 0..1, bytes sent by the browser
  server?: UploadedFile;
  error?: string;
}

interface WorkspaceState {
  items: Item[];
  addFiles: (files: File[]) => void;
  remove: (key: string) => void;
  clear: () => void;
}

const WsCtx = createContext<WorkspaceState>({ items: [], addFiles: () => {}, remove: () => {}, clear: () => {} });

let seq = 0;

/** Restrained motion app-wide (≤200 ms); honours the OS "reduce motion" setting. */
export function MotionProvider({ children }: { children: ReactNode }) {
  return <MotionConfig reducedMotion="user" transition={{ duration: 0.2, ease: "easeOut" }}>{children}</MotionConfig>;
}

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Item[]>([]);
  const removed = useRef(new Set<string>());

  const addFiles = useCallback((files: File[]) => {
    if (!files.length) return;
    const batch: Item[] = files.map((f) => ({ key: `f${++seq}`, name: f.name, size: f.size, status: "uploading", progress: 0 }));
    setItems((prev) => [...prev, ...batch]);
    const keys = batch.map((b) => b.key);
    const patch = (fn: (it: Item, idx: number) => Item) =>
      setItems((prev) => prev.map((it) => (keys.includes(it.key) ? fn(it, keys.indexOf(it.key)) : it)));
    uploadFiles(files, (loaded, total) => patch((it) => ({ ...it, progress: total ? loaded / total : 0 })))
      .then((res) => {
        patch((it, idx) => {
          const r = res[idx];
          if (!r) return { ...it, status: "rejected", error: "The server didn't accept this file." };
          if (removed.current.has(it.key)) {
            void fetch(`/api/uploads/${r.id}`, { method: "DELETE" });
          }
          return r.error || !r.format
            ? { ...it, status: "rejected", error: r.error ?? "We couldn't identify this file's format.", progress: 1 }
            : { ...it, status: "ready", server: r, progress: 1 };
        });
      })
      .catch((e: unknown) => {
        const msg = e instanceof ApiError ? e.message : "The upload failed. Try again.";
        patch((it) => ({ ...it, status: "rejected", error: msg }));
      });
  }, []);

  const remove = useCallback((key: string) => {
    setItems((prev) => {
      const it = prev.find((p) => p.key === key);
      if (it?.server) void fetch(`/api/uploads/${it.server.id}`, { method: "DELETE" });
      removed.current.add(key);
      return prev.filter((p) => p.key !== key);
    });
  }, []);

  const clear = useCallback(() => {
    setItems((prev) => {
      for (const it of prev) {
        if (it.server) void fetch(`/api/uploads/${it.server.id}`, { method: "DELETE" });
        removed.current.add(it.key);
      }
      return [];
    });
  }, []);

  const value = useMemo(() => ({ items, addFiles, remove, clear }), [items, addFiles, remove, clear]);
  return <WsCtx.Provider value={value}>{children}</WsCtx.Provider>;
}

export const useWorkspace = () => useContext(WsCtx);

// ---------------------------------------------------------------------------
// theme

export type Theme = "system" | "light" | "dark";

let chosen: Theme | null = null; // fallback when storage is unavailable (private windows)

function setRootTheme(t: Theme) {
  const root = document.documentElement;
  if (t === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", t);
}

export function applyTheme(t: Theme) {
  chosen = t;
  setRootTheme(t);
  try {
    localStorage.setItem("uc-theme", t);
  } catch {
    /* storage unavailable */
  }
  window.dispatchEvent(new Event("uc-theme"));
}

export function readTheme(): Theme {
  try {
    const t = localStorage.getItem("uc-theme");
    if (t === "light" || t === "dark" || t === "system") return t;
  } catch {
    /* storage unavailable */
  }
  return chosen ?? "system";
}

/** For useSyncExternalStore: changes from this tab, and from other tabs (which are applied here too). */
export function subscribeTheme(onChange: () => void): () => void {
  const onStorage = (e: StorageEvent) => {
    if (e.key !== "uc-theme") return;
    setRootTheme(readTheme());
    onChange();
  };
  window.addEventListener("uc-theme", onChange);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener("uc-theme", onChange);
    window.removeEventListener("storage", onStorage);
  };
}

/** Inline, render-blocking: sets data-theme before first paint so there's no flash. */
export const themeBootScript = `try{var t=localStorage.getItem("uc-theme");if(t==="light"||t==="dark")document.documentElement.setAttribute("data-theme",t)}catch(e){}`;
