"use client";

import { Upload } from "lucide-react";
import { useRouter } from "next/navigation";
import { useRef, useState, type DragEvent } from "react";
import { useCaps, useWorkspace } from "./providers";

interface Props {
  /** Navigate to this route after files are added (home page → workspace). */
  navigateTo?: string;
  compact?: boolean;
  families?: string;
}

export function DropZone({ navigateTo, compact = false, families }: Props) {
  const { addFiles } = useWorkspace();
  const { caps } = useCaps();
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const depth = useRef(0);

  const take = (list: FileList | null) => {
    const files = list ? Array.from(list) : [];
    if (!files.length) return;
    addFiles(files);
    if (navigateTo) router.push(navigateTo);
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    depth.current = 0;
    setOver(false);
    take(e.dataTransfer.files);
  };

  const limits = caps?.limits;
  return (
    <div
      data-testid="dropzone"
      onDragEnter={(e) => {
        e.preventDefault();
        depth.current++;
        setOver(true);
      }}
      onDragLeave={() => {
        depth.current = Math.max(0, depth.current - 1);
        if (!depth.current) setOver(false);
      }}
      onDragOver={(e) => e.preventDefault()}
      onDrop={onDrop}
      className={`dropzone-surface relative rounded-[var(--radius-zone)] border-2 border-dashed transition-[border-color,transform] duration-200 ${
        over ? "scale-[1.01] border-accent" : "border-line-strong"
      } ${compact ? "px-5 py-6" : "px-6 py-12 sm:px-12 sm:py-16"}`}
    >
      <input
        ref={input}
        type="file"
        multiple
        className="sr-only"
        tabIndex={-1}
        aria-hidden="true"
        data-testid="file-input"
        onChange={(e) => {
          take(e.target.files);
          e.target.value = "";
        }}
      />
      <div className={`flex ${compact ? "flex-row items-center gap-4" : "flex-col items-start gap-5 sm:flex-row sm:items-center sm:gap-8"}`}>
        <span
          className={`grid shrink-0 place-items-center rounded-2xl bg-accent text-accent-ink transition-transform duration-200 ${
            over ? "-translate-y-1" : ""
          } ${compact ? "h-11 w-11" : "h-16 w-16"}`}
          aria-hidden="true"
        >
          <Upload size={compact ? 20 : 28} strokeWidth={2.2} />
        </span>
        <div className="min-w-0 flex-1">
          <p className={`font-display font-semibold ${compact ? "text-xl" : "text-[1.75rem] leading-tight sm:text-[2rem]"}`}>
            {over ? "Drop to add your files" : compact ? "Add more files" : "Drop files here to convert"}
          </p>
          {!compact && (
            <p className="mt-1.5 text-muted">
              {limits
                ? `Up to ${limits.max_batch_files} files, ${limits.max_file_size_mb} MB each (${limits.max_video_size_mb} MB for video).`
                : "Drop one file or many."}
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={() => input.current?.click()}
          className="rounded-[var(--radius-control)] bg-ink px-5 py-3 font-medium text-paper transition-opacity duration-150 hover:opacity-90"
        >
          Browse files
        </button>
      </div>
      {families && !compact && <p className="mt-8 text-[0.95rem] text-muted">{families}</p>}
    </div>
  );
}
