import type { Metadata } from "next";
import Image from "next/image";
import localFont from "next/font/local";

import { AppNav } from "@/components/app-nav";
import "./globals.css";

const gotham = localFont({
  variable: "--font-gotham",
  display: "swap",
  src: [
    { path: "../fonts/GothamHTF-Light.otf", weight: "300", style: "normal" },
    {
      path: "../fonts/GothamHTF-LightItalic.otf",
      weight: "300",
      style: "italic",
    },
    { path: "../fonts/GothamHTF-Book.otf", weight: "400", style: "normal" },
    {
      path: "../fonts/GothamHTF-BookItalic.otf",
      weight: "400",
      style: "italic",
    },
    { path: "../fonts/GothamHTF-Bold.otf", weight: "700", style: "normal" },
    {
      path: "../fonts/GothamHTF-BoldItalic.otf",
      weight: "700",
      style: "italic",
    },
    { path: "../fonts/GothamHTF-Ultra.otf", weight: "800", style: "normal" },
  ],
});

export const metadata: Metadata = {
  title: "BOCAINA · Mesa de Dados de Crédito",
  description: "Painel operacional para leitura, cadastro e dossiês de debêntures.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="pt-BR" className={gotham.variable}>
      <body className="font-sans antialiased">
        <div className="mx-auto flex min-h-screen w-full max-w-7xl flex-col px-4 py-5 md:px-6 lg:px-8">
          <header className="sticky top-4 z-20 rounded-2xl border border-[var(--chrome-line)] bg-[var(--chrome-bg)] p-4 shadow-[var(--shadow-card)]">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex items-center gap-4">
                <Image
                  src="/brand/bocaina-logo-cream.png"
                  alt="BOCAINA"
                  width={246}
                  height={78}
                  className="h-8 w-auto"
                  priority
                />
                <div className="space-y-1">
                  <p className="font-mono text-xs uppercase tracking-[0.32em] text-[var(--chrome-muted)]">
                    Mesa de dados de crédito
                  </p>
                  <h1 className="text-lg font-semibold tracking-[0.01em] text-[var(--chrome-ink)]">
                    Mesa operacional de dados de debêntures
                  </h1>
                </div>
              </div>
              <AppNav />
            </div>
          </header>

          <main className="flex-1 py-6">{children}</main>
        </div>
      </body>
    </html>
  );
}
