import Link from "next/link";
import { Suspense } from "react";
import { Archive, AudioLines, Braces, FileSpreadsheet, FileText, Image as ImageIcon, Presentation, Video, Wrench } from "lucide-react";
import { DropZone } from "@/components/DropZone";
import { ToolCard } from "@/components/pdf/PdfHub";
import { ToolDirectory } from "@/components/ToolDirectory";
import { fmtShort, toolEntries } from "@/lib/caps";
import { serverCaps } from "@/lib/server";

const POPULAR: [string, string][] = [
  ["png", "jpg"], ["jpg", "png"], ["pdf", "docx"], ["docx", "pdf"],
  ["pdf", "jpg"], ["mp4", "mp3"], ["xlsx", "pdf"], ["heic", "jpg"],
];

// Featured on the home page when the API offers them (the full list lives at /pdf).
const FEATURED_PDF = ["edit-pdf", "sign-pdf", "merge-pdf", "compress-pdf", "organize-pdf", "redact-pdf", "pdf-to-word", "fill-pdf-form"];

const CATEGORY_ICON: Record<string, typeof ImageIcon> = {
  images: ImageIcon, documents: FileText, spreadsheets: FileSpreadsheet, presentations: Presentation,
  audio: AudioLines, video: Video, archives: Archive, developer: Braces, utilities: Wrench,
};

export default async function Home() {
  const caps = await serverCaps();
  const entries = caps ? toolEntries(caps) : [];
  const popular = POPULAR.map(([s, t]) => entries.find((e) => e.kind === "convert" && e.pair.source === s && e.pair.target === t)).filter(
    (e): e is NonNullable<typeof e> => Boolean(e),
  );
  const pdfTools = FEATURED_PDF.map((slug) => caps?.hubs?.pdf?.tools.find((t) => t.slug === slug)).filter(
    (t): t is NonNullable<typeof t> => Boolean(t),
  );
  const familyOrder = ["image", "pdf", "document", "spreadsheet", "presentation", "audio", "video", "archive", "font", "data"];
  const familyNames: Record<string, string> = {
    image: "images", pdf: "PDF", document: "Word and OpenDocument", spreadsheet: "Excel", presentation: "PowerPoint",
    audio: "audio", video: "video", archive: "archives", font: "fonts", data: "CSV, JSON and other data",
  };
  const families = caps ? familyOrder.filter((f) => Object.values(caps.formats).some((x) => x.family === f)).map((f) => familyNames[f]) : [];
  const familyLine = families.length
    ? `Works with ${families.slice(0, -1).join(", ")}${families.length > 1 ? " and " : ""}${families.at(-1)}.`
    : undefined;
  const retention = caps?.limits.retention_minutes ?? null;
  const clientTools = entries.filter((e) => e.op.runtime === "client").length;

  return (
    <>
      <section className="pb-14 pt-8 sm:pt-14">
        <h1 className="font-display text-[clamp(2.75rem,8vw,5.75rem)] font-bold leading-[0.95]" style={{ fontVariationSettings: '"wdth" 75' }}>
          One Platform.
          <br />
          Every Conversion.
        </h1>
        <p className="mt-5 max-w-xl text-lg text-muted sm:text-xl">
          Drop a file, pick a format, download the result. No accounts, and your files are deleted automatically.
        </p>
        <div className="mt-10">
          <DropZone navigateTo="/convert" families={familyLine} />
        </div>
      </section>

      {popular.length > 0 && (
        <section aria-labelledby="popular-h" className="py-10">
          <h2 id="popular-h" className="font-display text-3xl font-semibold">Popular conversions</h2>
          <ul className="mt-5 flex flex-wrap gap-2.5">
            {popular.map((e) => (
              <li key={e.slug}>
                <Link href={`/convert/${e.slug}`} className="flex items-center gap-2 rounded-full border border-line bg-surface px-4 py-2 font-medium hover:border-line-strong">
                  {fmtShort(caps!, e.pair.source)} <span aria-hidden="true" className="text-muted">→</span><span className="sr-only">to</span> {fmtShort(caps!, e.pair.target)}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      {pdfTools.length > 0 && (
        <section aria-labelledby="pdf-h" className="py-10" data-testid="home-pdf">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h2 id="pdf-h" className="font-display text-3xl font-semibold">Everything for PDFs</h2>
              <p className="mt-1 text-muted">Edit, sign, redact, fill forms, organize and convert, in one place.</p>
            </div>
            <Link href="/pdf" className="font-medium text-accent underline underline-offset-4 hover:decoration-2">
              See all {caps?.hubs?.pdf?.tools.length} PDF tools
            </Link>
          </div>
          <ul className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {pdfTools.map((t) => <li key={t.slug}><ToolCard tool={t} /></li>)}
          </ul>
        </section>
      )}

      {caps && (
        <section aria-labelledby="cat-h" className="py-10">
          <h2 id="cat-h" className="font-display text-3xl font-semibold">Categories</h2>
          <ul className="mt-5 grid grid-cols-2 gap-px overflow-hidden rounded-[var(--radius-panel)] border border-line bg-line sm:grid-cols-3">
            {caps.categories.map((c) => {
              const n = entries.filter((e) => e.category === c.id).length;
              const Icon = CATEGORY_ICON[c.id] ?? Wrench;
              return (
                <li key={c.id} className="bg-surface">
                  {n > 0 ? (
                    <Link href={`/tools?category=${c.id}`} className="flex h-full items-center gap-3 p-4 hover:bg-surface-2 sm:p-5">
                      <Icon size={22} className="shrink-0 text-accent" aria-hidden="true" />
                      <span>
                        <span className="block font-medium">{c.label}</span>
                        <span className="text-[0.88rem] text-muted">{n} {n === 1 ? "tool" : "tools"}</span>
                      </span>
                    </Link>
                  ) : (
                    <div className="flex h-full items-center gap-3 p-4 text-muted sm:p-5">
                      <Icon size={22} className="shrink-0" aria-hidden="true" />
                      <span>
                        <span className="block font-medium">{c.label}</span>
                        <span className="text-[0.88rem]">Coming soon</span>
                      </span>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      )}

      <section aria-labelledby="all-h" className="py-10">
        <h2 id="all-h" className="mb-5 font-display text-3xl font-semibold">All tools</h2>
        <Suspense>
          <ToolDirectory limit={18} />
        </Suspense>
      </section>

      <section aria-labelledby="how-h" className="py-10">
        <h2 id="how-h" className="font-display text-3xl font-semibold">How it works</h2>
        <ol className="mt-6 grid gap-6 sm:grid-cols-3">
          {[
            ["Add your files", "Drop them anywhere on the page, or browse. We detect each file's real format from its content."],
            ["Pick a format", "You only see options that work for your file, with any limitations stated up front."],
            ["Download", "Get each result, or all of them as one ZIP. Delete them yourself, or let them expire."],
          ].map(([t, d], i) => (
            <li key={t} className="flex gap-4">
              <span className="font-display text-4xl font-bold leading-none text-accent">{i + 1}</span>
              <span>
                <span className="block font-medium">{t}</span>
                <span className="text-muted">{d}</span>
              </span>
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="privacy-h" className="py-10">
        <h2 id="privacy-h" className="font-display text-3xl font-semibold">Privacy and security</h2>
        <ul className="mt-5 grid gap-x-10 gap-y-4 text-muted sm:grid-cols-2">
          {retention !== null && <li><span className="font-medium text-ink">Automatic deletion.</span> Uploads and results are deleted {retention} minutes after upload.</li>}
          <li><span className="font-medium text-ink">Delete any time.</span> “Delete now” removes your files and results from the server immediately.</li>
          <li><span className="font-medium text-ink">Isolated conversions.</span> Each conversion runs in its own sandboxed process with no network access and strict time and size limits.</li>
          <li><span className="font-medium text-ink">No accounts.</span> Your files are tied to a random token in your browser, and other visitors can&apos;t see them.</li>
          {clientTools > 0 && <li><span className="font-medium text-ink">Some tools run on your device.</span> Tools marked “In browser” never upload your data.</li>}
        </ul>
        <Link href="/privacy" className="mt-5 inline-block font-medium text-accent underline-offset-4 hover:underline">Read the privacy notice</Link>
      </section>
    </>
  );
}
