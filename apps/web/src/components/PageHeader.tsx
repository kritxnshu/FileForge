import Link from "next/link";
import type { ReactNode } from "react";

/** Title block shared by every page: optional breadcrumb, eyebrow, icon tile and right-hand slot. */
export function PageHeader({ crumbs, eyebrow, title, description, icon, aside, children }: {
  crumbs?: [label: string, href?: string][];
  eyebrow?: string;
  title: ReactNode;
  description?: ReactNode;
  icon?: ReactNode;
  aside?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <header className="rise mb-6 flex flex-wrap items-start justify-between gap-4">
      <div className="flex min-w-0 items-start gap-4">
        {icon && (
          <span className="mt-1 hidden h-12 w-12 shrink-0 place-items-center rounded-xl border border-line bg-surface text-accent shadow-1 sm:grid" aria-hidden="true">
            {icon}
          </span>
        )}
        <div className="min-w-0">
          {crumbs && (
            <nav aria-label="Breadcrumb" className="mb-1 flex flex-wrap items-center gap-1.5 text-[0.82rem] text-muted">
              {crumbs.map(([label, href], i) => (
                <span key={label} className="flex items-center gap-1.5">
                  {i > 0 && <span aria-hidden="true" className="text-line-strong">/</span>}
                  {href ? <Link href={href} className="hover:text-ink">{label}</Link> : <span>{label}</span>}
                </span>
              ))}
            </nav>
          )}
          {eyebrow && <p className="eyebrow">{eyebrow}</p>}
          <h1 className="mt-1 font-display text-[1.75rem] font-semibold leading-tight tracking-[-0.025em] sm:text-[2rem]">{title}</h1>
          {description && <p className="mt-1.5 max-w-2xl text-[0.95rem] text-muted">{description}</p>}
          {children}
        </div>
      </div>
      {aside}
    </header>
  );
}
