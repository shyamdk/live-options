import type { Metadata } from "next";

import AppSidebar from "@/components/AppSidebar";
import MarketStrip from "@/components/MarketStrip";
import "./globals.css";

export const metadata: Metadata = {
  title: "Live Options",
  description: "Dhan live trade management workspace",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <div className="app-shell">
          <AppSidebar />
          <main className="main">
            <MarketStrip />
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}

