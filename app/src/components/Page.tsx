import type { ReactNode } from "react";

export function Page({ title, sub, right, children }: { title: string; sub?: ReactNode; right?: ReactNode; children: ReactNode }) {
  return (
    <main className="page">
      <header className="page-head">
        <div>
          <h1>{title}</h1>
          {sub && <p className="page-sub">{sub}</p>}
        </div>
        {right}
      </header>
      {children}
    </main>
  );
}

export function Loading() {
  return (
    <div className="stack">
      {[0, 1, 2].map((i) => (
        <div key={i} className="card skeleton" />
      ))}
    </div>
  );
}

export function Empty({ icon, title, text }: { icon: ReactNode; title: string; text?: string }) {
  return (
    <div className="empty">
      <div className="empty-icon">{icon}</div>
      <p className="empty-title">{title}</p>
      {text && <p className="empty-text">{text}</p>}
    </div>
  );
}

export function DemoChip({ show }: { show?: boolean }) {
  return show ? <span className="chip">Démo</span> : null;
}
