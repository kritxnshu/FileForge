import type { Metadata } from "next";
import { serverCaps } from "@/lib/server";

export const metadata: Metadata = { title: "Privacy notice", description: "What happens to your files." };

export default async function PrivacyPage() {
  const caps = await serverCaps();
  const minutes = caps?.limits.retention_minutes;
  return (
    <article className="max-w-2xl pb-10 pt-4">
      <p className="rounded-[var(--radius-control)] bg-warn-soft p-3 text-[0.95rem]" role="note">
        <span className="font-medium">Template.</span> This notice describes how the software behaves. The operator of this site must review
        it, add their identity and contact details, and confirm it matches their deployment before relying on it.
      </p>
      <h1 className="mt-6 font-display text-[1.75rem] font-semibold leading-tight tracking-[-0.025em] sm:text-[2rem]">Privacy notice</h1>
      <div className="mt-6 flex flex-col gap-5 leading-relaxed">
        <section>
          <h2 className="font-display text-xl font-semibold">Files you upload</h2>
          <p className="mt-2 text-muted">
            Uploaded files and the converted results are stored on this server only to perform the conversion. They are deleted
            automatically {minutes ? `${minutes} minutes after upload` : "after a short retention period"}, when you choose “Delete now”, or when the
            service restarts and finds files it no longer tracks. Files are stored under random identifiers; your original file name is kept
            only as metadata so downloads have the right name.
          </p>
        </section>
        <section>
          <h2 className="font-display text-xl font-semibold">Tools that run in your browser</h2>
          <p className="mt-2 text-muted">Tools marked “Runs in your browser” process what you paste or open on your device. That data is not uploaded.</p>
        </section>
        <section>
          <h2 className="font-display text-xl font-semibold">Cookies and history</h2>
          <p className="mt-2 text-muted">
            There are no accounts. A single cookie holds a random token so the server can tell your files apart from other visitors&apos;. Your
            recent conversions are listed using your browser&apos;s local storage (names and formats only); you can clear them at any time.
          </p>
        </section>
        <section>
          <h2 className="font-display text-xl font-semibold">Logs</h2>
          <p className="mt-2 text-muted">
            The service logs technical events: job identifiers, file formats, sizes, durations and error types. It does not log file contents
            or file names. [Operator: state how long logs are kept and who can access them.]
          </p>
        </section>
        <section>
          <h2 className="font-display text-xl font-semibold">Contact</h2>
          <p className="mt-2 text-muted">[Operator: add the name and contact address of the organisation running this site.]</p>
        </section>
      </div>
    </article>
  );
}
