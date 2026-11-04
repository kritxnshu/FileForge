import type { Metadata } from "next";
import { PdfHub } from "@/components/pdf/PdfHub";
import { serverCaps } from "@/lib/server";

export const metadata: Metadata = {
  title: "PDF tools",
  description: "Merge, split, compress, convert, edit, sign, redact, fill forms and compare PDFs. Files are deleted automatically.",
};

export default async function PdfToolsPage() {
  const caps = await serverCaps();
  const hub = caps?.hubs?.pdf;
  return (
    <div className="pb-10 pt-4">
      <h1 className="font-display text-[clamp(2.6rem,7vw,4.5rem)] font-bold leading-[0.95]">
        Every PDF tool,<br /><span className="text-accent">in one place.</span>
      </h1>
      <p className="mt-5 max-w-2xl text-lg text-muted">
        {hub?.description ?? "Organize, convert, edit, sign and secure PDFs."}
      </p>
      <div className="mt-10">
        {hub ? <PdfHub hub={hub} /> : <p className="text-muted">The PDF tools are unavailable right now. Reload the page in a moment.</p>}
      </div>
    </div>
  );
}
