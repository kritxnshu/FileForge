// Re-mounted on every navigation: a short fade so pages don't pop in.
export default function Template({ children }: { children: React.ReactNode }) {
  return <div className="page-enter">{children}</div>;
}
