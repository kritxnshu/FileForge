import Link from "next/link";

export default function NotFound() {
  return (
    <div className="max-w-2xl pb-10 pt-4">
      <h1 className="font-display text-4xl font-bold sm:text-5xl">Page not found</h1>
      <p className="mt-4 text-lg text-muted">
        There&apos;s nothing at this address. If you followed a link to a conversion, it may not be supported.
      </p>
      <ul className="mt-6 flex flex-wrap gap-3">
        <li><Link href="/convert" className="block rounded-[var(--radius-control)] bg-accent px-4 py-2 font-medium text-accent-ink hover:opacity-90">Convert a file</Link></li>
        <li><Link href="/tools" className="block rounded-[var(--radius-control)] border border-line px-4 py-2 font-medium hover:border-line-strong">Browse all tools</Link></li>
        <li><Link href="/formats" className="block rounded-[var(--radius-control)] border border-line px-4 py-2 font-medium hover:border-line-strong">Supported formats</Link></li>
      </ul>
    </div>
  );
}
