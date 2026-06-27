"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

const navItems = [
  { href: "/", label: "Visão Geral" },
  { href: "/detalhe-ativo", label: "Detalhe do Ativo" },
  { href: "/detalhe-emissor", label: "Detalhe do Emissor" },
  { href: "/cadastro-dados", label: "Cadastro de Dados" },
];

export function AppNav() {
  const pathname = usePathname();

  return (
    <nav className="flex max-w-full flex-nowrap gap-1.5 overflow-x-auto whitespace-nowrap rounded-full bg-transparent p-1 scrollbar-none xl:justify-end">
      {navItems.map((item) => {
        const isActive =
          item.href === "/"
            ? pathname === item.href
            : pathname === item.href || pathname.startsWith(`${item.href}/`);

        return (
          <Link
            key={item.href}
            href={item.href}
            className={cn(
              "shrink-0 rounded-full px-4 py-2 text-sm font-semibold tracking-normal transition-all duration-200",
              isActive
                ? "bg-chrome-ink text-accent shadow-sm"
                : "bg-[var(--chrome-tab-idle-bg)] text-[var(--chrome-tab-idle-ink)] hover:bg-[var(--chrome-tab-idle-bg-hover)]",
            )}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
