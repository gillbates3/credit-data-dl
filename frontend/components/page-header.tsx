import type { ReactNode } from "react";

interface PageHeaderProps {
  eyebrow: string;
  title: string;
  description: string;
  action?: ReactNode;
}

export function PageHeader({
  eyebrow,
  title,
  description,
  action,
}: PageHeaderProps) {
  return (
    <header className="flex flex-col gap-5 rounded-2xl border border-[var(--line)] bg-[var(--panel)] p-6 shadow-[var(--shadow-card)] lg:flex-row lg:items-end lg:justify-between">
      <div className="space-y-3">
        <p className="font-mono text-xs uppercase tracking-[0.32em] text-[var(--muted)]">
          {eyebrow}
        </p>
        <div className="space-y-2">
          <h1 className="max-w-3xl text-3xl font-semibold tracking-[0.01em] text-[var(--ink)] md:text-4xl">
            {title}
          </h1>
          <p className="max-w-2xl text-sm leading-7 text-[var(--muted)] md:text-base">
            {description}
          </p>
        </div>
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </header>
  );
}
