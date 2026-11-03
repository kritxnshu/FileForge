import type { Metadata } from "next";

export const metadata: Metadata = { title: "Terms of use" };

export default function TermsPage() {
  return (
    <article className="max-w-2xl pb-10 pt-4">
      <p className="rounded-[var(--radius-control)] bg-warn-soft p-3 text-[0.95rem]" role="note">
        <span className="font-medium">Template.</span> These terms are a starting point for the operator of this site. Have them reviewed for
        your jurisdiction and add your organisation&apos;s details before relying on them.
      </p>
      <h1 className="mt-6 font-display text-4xl font-bold sm:text-5xl">Terms of use</h1>
      <ol className="mt-6 flex list-decimal flex-col gap-4 pl-5 leading-relaxed text-muted">
        <li>You may use this service to convert files you have the right to use and process.</li>
        <li>Don&apos;t upload content that is illegal, or try to disrupt, overload or attack the service. Usage limits apply.</li>
        <li>Conversions are provided as they are. Some conversions are marked Partial or Experimental; check results before relying on them.</li>
        <li>Files are deleted automatically after a short period. Keep your own copies; nothing here is a backup.</li>
        <li>[Operator: add liability, governing law and contact details appropriate for your organisation.]</li>
      </ol>
    </article>
  );
}
