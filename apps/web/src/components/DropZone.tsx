"use client";

import { ClipboardPaste, CloudUpload, FolderOpen, Lock, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type DragEvent } from "react";
import { useCaps, useWorkspace } from "./providers";

interface Props {
  /** Navigate to this route after files are added (home page → workspace). */
  navigateTo?: string;
  compact?: boolean;
  /** Format badges under the title (home page), plus how many more formats exist. */
  formats?: string[];
  moreFormats?: number;
  /** Also accept files dropped anywhere on the page. */
  global?: boolean;
}

const typing = (t: EventTarget | null) =>
  t instanceof HTMLElement && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName));

export function DropZone({ navigateTo, compact = false, formats, moreFormats = 0, global = false }: Props) {
  const { addFiles } = useWorkspace();
  const { caps } = useCaps();
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const zone = useRef<HTMLDivElement>(null);
  const [over, setOver] = useState(false);
  const [pasteHint, setPasteHint] = useState(false);
  const depth = useRef(0);

  const take = (files: File[]) => {
    if (!files.length) return;
    addFiles(files);
    if (navigateTo) router.push(navigateTo);
  };
  const takeRef = useRef(take);
  useEffect(() => {
    takeRef.current = take;
  });

  // Ctrl/⌘+V with files or a screenshot on the clipboard adds them (not while typing in a field)
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      if (typing(e.target)) return;
      const files = Array.from(e.clipboardData?.files ?? []);
      if (files.length) {
        e.preventDefault();
        takeRef.current(files);
      }
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, []);

  // files dropped anywhere on the page land here too
  useEffect(() => {
    if (!global) return;
    let timer: ReturnType<typeof setTimeout>;
    const hasFiles = (e: globalThis.DragEvent) => e.dataTransfer?.types.includes("Files");
    const onOver = (e: globalThis.DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      setOver(true);
      clearTimeout(timer);
      timer = setTimeout(() => setOver(false), 150);
    };
    const onDrop = (e: globalThis.DragEvent) => {
      if (!hasFiles(e) || zone.current?.contains(e.target as Node)) return;
      e.preventDefault();
      setOver(false);
      takeRef.current(Array.from(e.dataTransfer?.files ?? []));
    };
    window.addEventListener("dragover", onOver);
    window.addEventListener("drop", onDrop);
    return () => {
      clearTimeout(timer);
      window.removeEventListener("dragover", onOver);
      window.removeEventListener("drop", onDrop);
    };
  }, [global]);

  const pasteFromClipboard = async () => {
    try {
      const items = await navigator.clipboard.read();
      const files: File[] = [];
      for (const it of items) {
        const type = it.types.find((t) => !t.startsWith("text/"));
        if (!type) continue;
        const blob = await it.getType(type);
        files.push(new File([blob], `pasted.${type.split("/")[1]?.replace("jpeg", "jpg") ?? "bin"}`, { type }));
      }
      if (files.length) return take(files);
    } catch {
      /* permission denied or unsupported: fall through to the keyboard hint */
    }
    setPasteHint(true);
  };

  const dragProps = {
    onDragEnter: (e: DragEvent) => {
      e.preventDefault();
      depth.current++;
      setOver(true);
    },
    onDragLeave: () => {
      depth.current = Math.max(0, depth.current - 1);
      if (!depth.current && !global) setOver(false);
    },
    onDragOver: (e: DragEvent) => e.preventDefault(),
    onDrop: (e: DragEvent) => {
      e.preventDefault();
      depth.current = 0;
      setOver(false);
      take(Array.from(e.dataTransfer.files));
    },
  };

  const fileInput = (
    <input
      ref={input}
      type="file"
      multiple
      className="sr-only"
      tabIndex={-1}
      aria-hidden="true"
      data-testid="file-input"
      onChange={(e) => {
        take(Array.from(e.target.files ?? []));
        e.target.value = "";
      }}
    />
  );
  const limits = caps?.limits;

  if (compact) {
    return (
      <div ref={zone} data-testid="dropzone" {...dragProps}>
        {fileInput}
        <button
          type="button"
          onClick={() => input.current?.click()}
          className={`flex w-full flex-col items-center gap-2 rounded-[var(--radius-panel)] border-[1.5px] border-dashed px-4 py-6 text-center transition-[border-color,background-color] duration-200 ${
            over ? "border-accent bg-accent-soft" : "border-line-strong bg-surface-2 hover:border-accent/50"
          }`}
        >
          <span className="grid h-9 w-9 place-items-center rounded-full bg-surface text-accent shadow-1" aria-hidden="true">
            <Plus size={18} />
          </span>
          <span className="text-[0.92rem] font-medium">{over ? "Drop to add them" : "Add more files"}</span>
          <span className="font-mono text-[11px] text-muted">
            Drag and drop or click to browse{limits ? ` (up to ${limits.max_file_size_mb} MB per file)` : ""}
          </span>
        </button>
      </div>
    );
  }

  return (
    <div
      ref={zone}
      data-testid="dropzone"
      {...dragProps}
      className={`dropzone-surface relative rounded-[var(--radius-zone)] border-[1.5px] border-dashed px-5 py-10 text-center transition-[border-color,box-shadow] duration-200 sm:px-10 sm:py-12 ${
        over ? "border-accent shadow-[0_0_0_4px_color-mix(in_oklab,var(--accent)_15%,transparent)]" : "border-line-strong"
      }`}
    >
      {fileInput}
      <span
        className={`mx-auto grid h-14 w-14 place-items-center rounded-2xl border border-line bg-surface text-accent shadow-2 transition-transform duration-300 ease-[cubic-bezier(0.2,0.7,0.2,1)] ${
          over ? "-translate-y-1.5 scale-105" : ""
        }`}
        aria-hidden="true"
      >
        <CloudUpload size={26} strokeWidth={2} />
      </span>
      <p className="mt-5 font-display text-[1.3rem] font-semibold">{over ? "Release to add your files" : "Drop your files here to transform"}</p>
      <p className="mt-1 text-[0.92rem] text-muted">
        {limits
          ? `Up to ${limits.max_batch_files} files, ${limits.max_file_size_mb} MB each (${limits.max_video_size_mb} MB for video).`
          : "Drop one file or many."}
      </p>
      {formats && formats.length > 0 && (
        <ul className="mt-4 flex flex-wrap justify-center gap-1.5" aria-label="Some supported formats">
          {formats.map((f) => <li key={f} className="chip">{f}</li>)}
          {moreFormats > 0 && (
            <li><Link href="/formats" className="chip !border-transparent !bg-accent-soft !text-accent hover:underline">+{moreFormats} formats</Link></li>
          )}
        </ul>
      )}
      <div className="mt-6 flex flex-wrap justify-center gap-2.5">
        <button type="button" onClick={() => input.current?.click()} className="btn btn-primary">
          <FolderOpen size={16} aria-hidden="true" /> Choose files
        </button>
        <button type="button" onClick={() => void pasteFromClipboard()} className="btn btn-ghost">
          <ClipboardPaste size={16} aria-hidden="true" /> Paste from clipboard
          <kbd className="rounded border border-line bg-surface-2 px-1 font-mono text-[10px] text-muted">⌘V</kbd>
        </button>
      </div>
      <p aria-live="polite" className="mt-2 min-h-5 text-[0.82rem] text-muted">
        {pasteHint && "Your browser blocked clipboard access. Press ⌘V (Ctrl+V on Windows) instead."}
      </p>
      {limits && (
        <p className="mx-auto mt-2 inline-flex items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1 text-[0.8rem] text-muted">
          <Lock size={13} aria-hidden="true" /> Processed in a sandbox and deleted automatically after {limits.retention_minutes} minutes.
        </p>
      )}
    </div>
  );
}
