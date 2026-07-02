import type { Metadata } from "next";

import AuthShell from "@/components/AuthShell";
import "./globals.css";

export const metadata: Metadata = {
  title: "Live Options",
  description: "Dhan live trade management workspace",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <AuthShell>{children}</AuthShell>
      </body>
    </html>
  );
}
