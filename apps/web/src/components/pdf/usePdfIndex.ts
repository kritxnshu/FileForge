"use client";

import { useEffect, useState } from "react";
import { ApiError, uploadPages, type PageIndex } from "@/lib/api";

/** Page count, thumbnails and displayed page sizes of an uploaded PDF (rendered in the sandbox). */
export function usePdfIndex(fileId: string) {
  const [state, setState] = useState<{ key: string; data?: PageIndex; error?: string } | null>(null);
  useEffect(() => {
    let live = true;
    uploadPages(fileId)
      .then((data) => live && setState({ key: fileId, data }))
      .catch((e) => live && setState({ key: fileId, error: e instanceof ApiError ? e.message : "This PDF's pages couldn't be shown." }));
    return () => {
      live = false;
    };
  }, [fileId]);
  const cur = state?.key === fileId ? state : null;
  return { data: cur?.data ?? null, error: cur?.error ?? null };
}

/** Displayed [width, height] of a page in points, or A4 when unknown. */
export function pageSize(data: PageIndex | null, page: number): [number, number] {
  return data?.sizes?.[page - 1] ?? [595.28, 841.89];
}
