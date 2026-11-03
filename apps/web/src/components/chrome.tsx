"use client";

import Link from "next/link";
import { Monitor, Moon, Sun } from "lucide-react";
import { useSyncExternalStore } from "react";
import { applyTheme, readTheme, subscribeTheme, type Theme } from "./providers";

export function Logo() {
  return (
    <Link href="/" className="flex items-center gap-2.5 rounded-lg" aria-label="Universal Converter home">
      <svg width="28" height="28" viewBox="0 0 28 28" aria-hidden="true">
        <rect x="2" y="6" width="15" height="18" rx="4" fill="none" stroke="currentColor" strokeWidth="2" />
        <rect x="11" y="3" width="15" height="18" rx="4" fill="var(--accent)" />
        <path d="M15.5 12h7m-2.5-2.5L22.5 12 20 14.5" stroke="var(--accent-ink)" strokeWidth="1.8" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <span className="font-display text-[1.2rem] font-semibold">Universal Converter</span>
    </Link>
  );
}

const THEMES: { id: Theme; label: string; Icon: typeof Sun }[] = [
  { id: "light", label: "Light", Icon: Sun },
  { id: "dark", label: "Dark", Icon: Moon },
  { id: "system", label: "System", Icon: Monitor },
];

export function ThemeToggle() {
  const theme = useSyncExternalStore<Theme>(subscribeTheme, readTheme, () => "system");
  return (
    <div role="radiogroup" aria-label="Color theme" className="flex rounded-full border border-line bg-surface p-0.5">
      {THEMES.map(({ id, label, Icon }) => (
        <button
          key={id}
          role="radio"
          aria-checked={theme === id}
          aria-label={`${label} theme`}
          title={`${label} theme`}
          data-testid={`theme-${id}`}
          onClick={() => applyTheme(id)}
          className={`grid h-8 w-8 place-items-center rounded-full transition-colors duration-150 ${
            theme === id ? "bg-ink text-paper" : "text-muted hover:text-ink"
          }`}
        >
          <Icon size={15} aria-hidden="true" />
        </button>
      ))}
    </div>
  );
}

export function Header() {
  return (
    <header className="mx-auto flex w-full max-w-6xl items-center justify-between gap-4 px-4 py-5 sm:px-6">
      <a href="#main" className="sr-only-focusable rounded bg-ink px-3 py-1 text-paper">
        Skip to content
      </a>
      <Logo />
      <nav aria-label="Main" className="flex items-center gap-1 sm:gap-4">
        <Link href="/tools" className="hidden rounded-md px-2 py-1 text-[0.95rem] text-muted hover:text-ink sm:block">
          All tools
        </Link>
        <Link href="/formats" className="hidden rounded-md px-2 py-1 text-[0.95rem] text-muted hover:text-ink sm:block">
          Formats
        </Link>
        <Link href="/privacy" className="hidden rounded-md px-2 py-1 text-[0.95rem] text-muted hover:text-ink md:block">
          Privacy
        </Link>
        <ThemeToggle />
      </nav>
    </header>
  );
}

export function Footer() {
  return (
    <footer className="mt-24 border-t border-line">
      <div className="mx-auto grid max-w-6xl gap-8 px-4 py-10 text-[0.95rem] sm:grid-cols-[2fr_1fr_1fr] sm:px-6">
        <div className="max-w-sm">
          <Logo />
          <p className="mt-3 text-muted">
            Convert files between formats in one place. Uploads and results are deleted automatically.
          </p>
        </div>
        <nav aria-label="Product" className="flex flex-col gap-2">
          <span className="font-medium">Product</span>
          <Link className="text-muted hover:text-ink" href="/tools">All tools</Link>
          <Link className="text-muted hover:text-ink" href="/formats">Supported formats</Link>
          <Link className="text-muted hover:text-ink" href="/docs">Docs</Link>
        </nav>
        <nav aria-label="Legal" className="flex flex-col gap-2">
          <span className="font-medium">Legal</span>
          <Link className="text-muted hover:text-ink" href="/privacy">Privacy</Link>
          <Link className="text-muted hover:text-ink" href="/terms">Terms</Link>
        </nav>
      </div>
    </footer>
  );
}
