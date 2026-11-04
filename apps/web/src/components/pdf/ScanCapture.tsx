"use client";

import { Camera, ImagePlus, Video, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useWorkspace } from "../providers";

/**
 * Capture document pages with the device camera. Each photo joins the file list below, and the Scan to PDF
 * settings (photo clean-up) turn them into one PDF. Photos are uploaded only when you take them, like any file.
 */
export function ScanCapture() {
  const { addFiles } = useWorkspace();
  const video = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const [live, setLive] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [count, setCount] = useState(0);
  const [flash, setFlash] = useState(false);

  const stop = () => {
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
    setLive(false);
  };
  useEffect(() => stop, []);

  const start = async () => {
    setError(null);
    if (!navigator.mediaDevices?.getUserMedia) {
      setError("This browser can't open the camera here. Use “Take or choose photos” instead.");
      return;
    }
    try {
      const s = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" }, width: { ideal: 2560 } }, audio: false });
      stream.current = s;
      setLive(true);
      requestAnimationFrame(() => {
        if (video.current) {
          video.current.srcObject = s;
          void video.current.play();
        }
      });
    } catch {
      setError("We couldn't open the camera. Allow camera access in your browser, or use “Take or choose photos”.");
    }
  };

  const capture = () => {
    const v = video.current;
    if (!v || !v.videoWidth) return;
    const c = document.createElement("canvas");
    c.width = v.videoWidth;
    c.height = v.videoHeight;
    c.getContext("2d")!.drawImage(v, 0, 0);
    c.toBlob((blob) => {
      if (!blob) return;
      const n = count + 1;
      setCount(n);
      addFiles([new File([blob], `scan-page-${String(n).padStart(2, "0")}.jpg`, { type: "image/jpeg" })]);
      setFlash(true);
      setTimeout(() => setFlash(false), 150);
    }, "image/jpeg", 0.92);
  };

  return (
    <section aria-labelledby="scan-h" className="rounded-[var(--radius-panel)] border border-line bg-surface p-4 sm:p-6" data-testid="scan">
      <h2 id="scan-h" className="font-display text-2xl font-semibold">Capture pages</h2>
      <p className="mt-1 text-[0.95rem] text-muted">
        Lay the page flat in good light, fill the frame, and take one photo per page. They&apos;re added below in order.
      </p>
      {live ? (
        <div className="mt-4 flex flex-col gap-3">
          <div className="relative overflow-hidden rounded-[var(--radius-control)] bg-black">
            <video ref={video} playsInline muted className="max-h-[60vh] w-full object-contain" aria-label="Camera preview" />
            {flash && <div className="absolute inset-0 bg-white/70" aria-hidden="true" />}
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={capture} data-testid="scan-capture"
              className="flex items-center gap-2 rounded-[var(--radius-control)] bg-accent px-5 py-3 font-semibold text-accent-ink hover:opacity-90">
              <Camera size={18} aria-hidden="true" /> Capture page {count + 1}
            </button>
            <button type="button" onClick={stop} className="flex items-center gap-2 rounded-[var(--radius-control)] border border-line px-4 py-3 font-medium hover:border-line-strong">
              <X size={18} aria-hidden="true" /> Close camera
            </button>
          </div>
          <p aria-live="polite" className="text-[0.9rem] text-muted">{count ? `${count} page${count === 1 ? "" : "s"} captured.` : ""}</p>
        </div>
      ) : (
        <div className="mt-4 flex flex-wrap gap-2">
          <button type="button" onClick={start} data-testid="scan-open-camera"
            className="flex items-center gap-2 rounded-[var(--radius-control)] bg-accent px-5 py-3 font-semibold text-accent-ink hover:opacity-90">
            <Video size={18} aria-hidden="true" /> Open camera
          </button>
          <button type="button" onClick={() => fileInput.current?.click()}
            className="flex items-center gap-2 rounded-[var(--radius-control)] border border-line px-4 py-3 font-medium hover:border-line-strong">
            <ImagePlus size={18} aria-hidden="true" /> Take or choose photos
          </button>
          <input ref={fileInput} type="file" accept="image/*" capture="environment" multiple className="sr-only" tabIndex={-1} aria-hidden="true"
            data-testid="scan-file-input"
            onChange={(e) => {
              const files = Array.from(e.target.files ?? []);
              if (files.length) addFiles(files);
              e.target.value = "";
            }} />
        </div>
      )}
      {error && <p role="alert" className="mt-3 rounded-[var(--radius-control)] bg-danger-soft p-3 text-[0.95rem]">{error}</p>}
    </section>
  );
}
