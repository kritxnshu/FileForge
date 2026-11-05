"use client";

import {
  ArrowLeftRight, FileText, LayoutDashboard, LayoutGrid, Menu, Monitor, Moon, Plus, Search, Shapes, SquareTerminal, Sun, Upload, Wrench, X,
  type LucideIcon,
} from "lucide-react";
import { motion } from "motion/react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState, useSyncExternalStore, type ReactNode } from "react";
import { toolEntries } from "@/lib/caps";
import { CATEGORY_ICON } from "./categoryIcons";
import { applyTheme, readTheme, subscribeTheme, useCaps, useWorkspace, type Theme } from "./providers";

export const openPalette = () => window.dispatchEvent(new Event("ff-palette"));


export function Logo({ onClick }: { onClick?: () => void }) {
  return (
    <Link href="/" onClick={onClick} className="flex items-center gap-2 rounded-lg" aria-label="FileForge home">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src="/logo.svg" width={30} height={30} alt="" aria-hidden="true" />
      <span className="font-display text-[1.15rem] font-semibold tracking-tight">
        File
        <span className="bg-[linear-gradient(90deg,#60a5fa,#a78bfa_60%,#e879f9)] bg-clip-text text-transparent">Forge</span>
      </span>
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
    <div role="radiogroup" aria-label="Color theme" className="relative flex rounded-lg bg-side-2 p-0.5">
      {THEMES.map(({ id, label, Icon }) => (
        <button
          key={id}
          role="radio"
          aria-checked={theme === id}
          aria-label={`${label} theme`}
          title={`${label} theme`}
          data-testid={`theme-${id}`}
          onClick={() => applyTheme(id)}
          className={`relative grid h-7 w-8 place-items-center rounded-md transition-colors duration-150 ${
            theme === id ? "text-side-ink" : "text-side-muted hover:text-side-ink"
          }`}
        >
          {theme === id && <motion.span layoutId="theme-thumb" className="absolute inset-0 rounded-md bg-side-line" />}
          <Icon size={14} aria-hidden="true" className="relative" />
        </button>
      ))}
    </div>
  );
}

function NavItem({ href, icon: Icon, label, active, badge, onNavigate, testId }: {
  href: string; icon: LucideIcon; label: string; active: boolean; badge?: number; onNavigate: () => void; testId?: string;
}) {
  return (
    <Link
      href={href}
      onClick={onNavigate}
      data-testid={testId}
      aria-current={active ? "page" : undefined}
      className={`relative flex items-center gap-2.5 rounded-lg px-2.5 py-[7px] text-[0.9rem] transition-colors duration-150 ${
        active ? "text-white" : "text-side-muted hover:bg-side-2 hover:text-side-ink"
      }`}
    >
      {active && (
        <motion.span layoutId="nav-active" transition={{ type: "spring", stiffness: 500, damping: 40 }}
          className="absolute inset-0 rounded-lg bg-[#4f46e5] shadow-[inset_0_1px_0_rgb(255_255_255/0.15)]" />
      )}
      <Icon size={17} aria-hidden="true" className="relative shrink-0" />
      <span className="relative flex-1 truncate">{label}</span>
      {badge !== undefined && badge > 0 && (
        <span className={`relative rounded-md px-1.5 font-mono text-[11px] tabular-nums ${active ? "bg-white/20" : "bg-side-2 text-side-muted"}`}>{badge}</span>
      )}
    </Link>
  );
}

function CategoryNav({ onNavigate }: { onNavigate: () => void }) {
  const { caps } = useCaps();
  const pathname = usePathname();
  const params = useSearchParams();
  const counts = useMemo(() => {
    const m = new Map<string, number>();
    if (caps) for (const e of toolEntries(caps)) m.set(e.category, (m.get(e.category) ?? 0) + 1);
    return m;
  }, [caps]);
  if (!caps) return null;
  return (
    <>
      {caps.categories.filter((c) => counts.get(c.id)).map((c) => (
        <NavItem key={c.id} href={`/tools?category=${c.id}`} icon={CATEGORY_ICON[c.id] ?? Wrench} label={c.label}
          active={pathname === "/tools" && params.get("category") === c.id} badge={counts.get(c.id)} onNavigate={onNavigate} />
      ))}
    </>
  );
}

/** Active on /tools only when no category is picked (a category has its own item, and one highlight moves between them). */
function AllToolsItem({ onNavigate }: { onNavigate: () => void }) {
  const pathname = usePathname();
  const params = useSearchParams();
  return <NavItem href="/tools" icon={LayoutGrid} label="All tools" active={pathname === "/tools" && !params.get("category")} onNavigate={onNavigate} />;
}

function Sidebar({ open, onNavigate }: { open: boolean; onNavigate: () => void }) {
  const { caps, error } = useCaps();
  const { items } = useWorkspace();
  const pathname = usePathname();
  const devSlug = useMemo(
    () => (caps ? toolEntries(caps).find((e) => e.category === "developer" && e.op.runtime === "client")?.slug : undefined),
    [caps],
  );
  const is = (p: string) => (p === "/" ? pathname === "/" : pathname === p || pathname.startsWith(`${p}/`));
  const onDevTool = pathname.startsWith("/tools/");
  const limits = caps?.limits;

  return (
    <aside
      aria-label="Sidebar"
      className={`fixed inset-y-0 left-0 z-50 flex w-64 flex-col border-r border-side-line bg-side text-side-ink transition-[transform,visibility] duration-300 ease-[cubic-bezier(0.2,0.7,0.2,1)] lg:visible lg:w-60 lg:translate-x-0 ${
        open ? "visible translate-x-0" : "invisible -translate-x-full"
      }`}
    >
      <div className="flex h-14 items-center justify-between px-4">
        <Logo onClick={onNavigate} />
        <button onClick={onNavigate} aria-label="Close menu" className="grid h-8 w-8 place-items-center rounded-md text-side-muted hover:text-side-ink lg:hidden">
          <X size={18} />
        </button>
      </div>
      <div className="px-3">
        <button onClick={() => { onNavigate(); openPalette(); }}
          className="flex w-full items-center gap-2 rounded-lg border border-side-line bg-side-2 px-2.5 py-2 text-left text-[0.88rem] text-side-muted transition-colors duration-150 hover:text-side-ink">
          <Search size={15} aria-hidden="true" />
          <span className="flex-1">Search tools…</span>
          <kbd className="rounded bg-side px-1.5 font-mono text-[10px]">⌘K</kbd>
        </button>
      </div>
      <nav aria-label="Main" className="no-scrollbar mt-4 flex-1 overflow-y-auto px-3 pb-4">
        <p className="eyebrow mb-1.5 px-2.5 !text-[10px] !text-side-muted">Platform</p>
        <div className="flex flex-col gap-0.5">
          <NavItem href="/" icon={LayoutDashboard} label="Dashboard" active={is("/")} onNavigate={onNavigate} />
          <NavItem href="/convert" icon={ArrowLeftRight} label="Convert" active={is("/convert")} badge={items.length} onNavigate={onNavigate} testId="nav-convert" />
          <NavItem href="/pdf" icon={FileText} label="PDF tools" active={is("/pdf")} onNavigate={onNavigate} testId="nav-pdf" />
          {devSlug && <NavItem href={`/tools/${devSlug}`} icon={SquareTerminal} label="Developer tools" active={onDevTool} onNavigate={onNavigate} />}
          <Suspense fallback={<NavItem href="/tools" icon={LayoutGrid} label="All tools" active={false} onNavigate={onNavigate} />}>
            <AllToolsItem onNavigate={onNavigate} />
          </Suspense>
          <NavItem href="/formats" icon={Shapes} label="Formats" active={is("/formats")} onNavigate={onNavigate} />
        </div>
        <p className="eyebrow mb-1.5 mt-5 px-2.5 !text-[10px] !text-side-muted">Categories</p>
        <div className="flex flex-col gap-0.5">
          <Suspense>
            <CategoryNav onNavigate={onNavigate} />
          </Suspense>
        </div>
      </nav>
      <div className="flex flex-col gap-3 border-t border-side-line p-3">
        <div className="rounded-lg bg-side-2 px-3 py-2.5">
          <p className="flex items-center gap-2 font-mono text-[11px] text-side-muted">
            <span className={`h-1.5 w-1.5 rounded-full ${error ? "bg-rose-500" : caps ? "bg-emerald-400" : "pulse-dot bg-amber-400"}`} aria-hidden="true" />
            {error ? "Engine unreachable" : caps ? "Engine online · sandboxed" : "Connecting…"}
          </p>
          {limits && (
            <p className="mt-1 font-mono text-[11px] text-side-muted">
              {limits.max_file_size_mb} MB/file · wiped after {limits.retention_minutes} min
            </p>
          )}
        </div>
        <div className="flex items-center justify-between">
          <Link href="/docs" onClick={onNavigate} className="rounded-md px-1.5 py-1 text-[0.82rem] text-side-muted hover:text-side-ink">Docs &amp; API</Link>
          <ThemeToggle />
        </div>
      </div>
    </aside>
  );
}

const SECTIONS: [string, string][] = [
  ["/convert", "Convert"], ["/pdf", "PDF tools"], ["/tools/", "Developer tools"], ["/tools", "All tools"],
  ["/formats", "Formats"], ["/docs", "Docs"], ["/privacy", "Privacy"], ["/terms", "Terms"],
];

function TopBar({ onMenu }: { onMenu: () => void }) {
  const pathname = usePathname();
  const section = pathname === "/" ? "Dashboard" : SECTIONS.find(([p]) => pathname.startsWith(p))?.[1];
  return (
    <header className="glass sticky top-0 z-30 border-b">
      <div className="mx-auto flex h-14 max-w-[1240px] items-center gap-3 px-4 sm:px-6 lg:px-8">
        <button onClick={onMenu} aria-label="Open menu" className="-ml-1.5 grid h-9 w-9 place-items-center rounded-md text-muted hover:text-ink lg:hidden">
          <Menu size={20} />
        </button>
        <span className="lg:hidden"><Logo /></span>
        <div className="hidden items-center gap-2 text-[0.88rem] lg:flex">
          <Link href="/" className="text-muted hover:text-ink">FileForge</Link>
          {section && (
            <>
              <span className="text-line-strong" aria-hidden="true">/</span>
              <span className="font-medium text-accent">{section}</span>
            </>
          )}
        </div>
        <div className="ml-auto flex items-center gap-2">
          <button onClick={openPalette} aria-label="Search tools"
            className="btn btn-ghost !px-2.5 sm:!pr-2 text-muted">
            <Search size={15} aria-hidden="true" />
            <span className="hidden sm:inline">Search</span>
            <kbd className="hidden rounded border border-line bg-surface-2 px-1.5 font-mono text-[10px] sm:inline">⌘K</kbd>
          </button>
          <Link href="/convert" className="btn btn-primary hidden sm:inline-flex">
            <Plus size={15} aria-hidden="true" /> New batch
          </Link>
        </div>
      </div>
    </header>
  );
}

/** Sidebar + top bar around every page. On small screens the sidebar is a drawer. */
export function Shell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);
  return (
    <>
      <a href="#main" className="sr-only-focusable fixed left-3 top-3 z-[60] rounded-md bg-ink px-3 py-1.5 text-paper">
        Skip to content
      </a>
      <Sidebar open={open} onNavigate={() => setOpen(false)} />
      <div
        aria-hidden="true"
        onClick={() => setOpen(false)}
        className={`fixed inset-0 z-40 bg-black/40 transition-opacity duration-300 lg:hidden ${open ? "opacity-100" : "pointer-events-none opacity-0"}`}
      />
      <div className="flex min-h-screen flex-col lg:pl-60">
        <TopBar onMenu={() => setOpen(true)} />
        <div className="flex-1">{children}</div>
      </div>
    </>
  );
}

/** Floating hint bar on the dashboard (wide screens): opens search; reminds that files can be dropped anywhere. */
export function Dock() {
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-5 z-20 hidden justify-center lg:flex lg:pl-60">
      <div className="glass rise pointer-events-auto flex items-center gap-3 rounded-full border py-1.5 pl-1.5 pr-4 text-[0.82rem] text-muted shadow-3" style={{ "--i": 8 } as React.CSSProperties}>
        <button onClick={openPalette} className="flex items-center gap-2 rounded-full px-2.5 py-1 transition-colors duration-150 hover:bg-surface-2 hover:text-ink">
          <kbd className="rounded border border-line bg-surface-2 px-1.5 font-mono text-[10px]">⌘K</kbd> Search tools
        </button>
        <span className="h-1 w-1 rounded-full bg-line-strong" aria-hidden="true" />
        <span className="flex items-center gap-1.5"><Upload size={14} aria-hidden="true" /> Drop files anywhere to start</span>
      </div>
    </div>
  );
}

export function Footer() {
  return (
    <footer className="border-t border-line">
      <div className="mx-auto flex max-w-[1240px] flex-col gap-3 px-4 py-6 text-[0.85rem] text-muted sm:flex-row sm:items-center sm:justify-between sm:px-6 lg:px-8">
        <p>FileForge. Files are processed in a sandbox and deleted automatically.</p>
        <nav aria-label="Footer" className="flex flex-wrap gap-x-5 gap-y-1">
          <Link className="hover:text-ink" href="/formats">Supported formats</Link>
          <Link className="hover:text-ink" href="/docs">Docs</Link>
          <Link className="hover:text-ink" href="/privacy">Privacy</Link>
          <Link className="hover:text-ink" href="/terms">Terms</Link>
        </nav>
      </div>
    </footer>
  );
}
