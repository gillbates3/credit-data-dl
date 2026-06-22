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
    <nav className="flex flex-wrap gap-1 rounded-full border border-chrome-line bg-black/10 p-1">
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
              "rounded-full px-4 py-2 text-sm font-semibold tracking-wide transition-all duration-200",
              isActive
                ? "bg-chrome-ink text-accent shadow-sm"
                : "text-chrome-muted hover:bg-white/5 hover:text-chrome-ink",
            )}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
