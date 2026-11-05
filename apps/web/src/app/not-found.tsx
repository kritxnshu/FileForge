import Link from "next/link";

export default function NotFound() {
  return (
    <div className="card rise mx-auto mt-6 max-w-2xl p-8">
      <p className="eyebrow">Error 404</p>
      <h1 className="font-display text-[1.75rem] font-semibold leading-tight tracking-[-0.025em] sm:text-[2rem]">Page not found</h1>
      <p className="mt-2 text-[0.98rem] text-muted">
        There&apos;s nothing at this address. If you followed a link to a conversion, it may not be supported.
      </p>
      <ul className="mt-6 flex flex-wrap gap-3">
        <li><Link href="/convert" className="btn btn-primary">Convert a file</Link></li>
        <li><Link href="/tools" className="btn btn-ghost">Browse all tools</Link></li>
        <li><Link href="/formats" className="btn btn-ghost">Supported formats</Link></li>
      </ul>
    </div>
  );
}
