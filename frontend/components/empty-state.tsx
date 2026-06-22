import type { ReactNode } from "react";

interface EmptyStateProps {
  title: string;
  description: string;
  action?: ReactNode;
}

export function EmptyState({ title, description, action }: EmptyStateProps) {
  return (
    <div className="rounded-2xl border border-dashed border-[var(--line-strong)] bg-white p-8 text-center shadow-[var(--shadow-soft)]">
      <div className="mx-auto max-w-xl space-y-3">
        <h2 className="text-xl font-semibold tracking-[0.01em] text-[var(--ink)]">
          {title}
        </h2>
        <p className="text-sm leading-7 text-[var(--muted)]">{description}</p>
        {action ? <div className="pt-2">{action}</div> : null}
      </div>
    </div>
  );
}
