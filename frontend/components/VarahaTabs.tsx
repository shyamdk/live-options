"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { href: "/varaha", label: "Daily decision" },
  { href: "/varaha/full-butterfly", label: "Full Butterfly builder" },
  { href: "/varaha/paper", label: "Paper trades" },
];

export default function VarahaTabs() {
  const pathname = usePathname();
  return (
    <nav style={{ display: "flex", gap: 4, borderBottom: "1px solid var(--line)", marginBottom: 14 }}>
      {TABS.map((tab) => {
        const active = pathname === tab.href;
        return (
          <Link
            key={tab.href}
            href={tab.href}
            style={{
              padding: "8px 14px",
              fontSize: 14,
              fontWeight: active ? 600 : 500,
              color: active ? "var(--blue)" : "var(--muted)",
              borderBottom: `2px solid ${active ? "var(--blue)" : "transparent"}`,
              marginBottom: -1,
              textDecoration: "none",
            }}
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
