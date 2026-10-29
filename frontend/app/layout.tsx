import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";

import AuthShell from "@/components/AuthShell";
import "./globals.css";

// Ledger look (from the OI Early Signal Ledger): Plex Sans for text, Plex
// Mono for figures. Self-hosted by next/font, exposed as CSS variables.
const plexSans = IBM_Plex_Sans({ subsets: ["latin"], weight: ["400", "500", "600", "700"], variable: "--font-sans", display: "swap" });
const plexMono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-mono", display: "swap" });

export const metadata: Metadata = {
  title: "Live Options",
  description: "Dhan live trade management workspace",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${plexSans.variable} ${plexMono.variable}`}>
      <body>
        <AuthShell>{children}</AuthShell>
      </body>
    </html>
  );
}
