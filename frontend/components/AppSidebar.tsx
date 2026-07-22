"use client";

import { Activity, BookOpenText, BriefcaseBusiness, CandlestickChart, ChevronLeft, ChevronRight, Layers, Zap } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

const navItems = [
  { href: "/manage-trades", label: "Manage Trades", short: "MT", icon: BriefcaseBusiness },
  { href: "/trade-journals", label: "Trade Journals", short: "TJ", icon: BookOpenText },
  { href: "/gamma-blast", label: "Gamma Blast", short: "GB", icon: Zap },
  { href: "/ema5", label: "ema5", short: "E5", icon: CandlestickChart },
  { href: "/animesh-scalping", label: "animesh-scalping", short: "AS", icon: Activity },
  { href: "/bank-nifty-credit-spread", label: "BN Credit Spread", short: "CS", icon: Layers },
];

const STORAGE_KEY = "live-options-sidebar-collapsed";

export default function AppSidebar() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    setCollapsed(window.localStorage.getItem(STORAGE_KEY) === "true");
  }, []);

  function toggleCollapsed() {
    setCollapsed((current) => {
      const next = !current;
      window.localStorage.setItem(STORAGE_KEY, String(next));
      return next;
    });
  }

  return (
    <aside className={`sidebar ${collapsed ? "collapsed" : ""}`}>
      <div className="brand">
        <span className="brand-mark">L</span>
        <span className="brand-name">Live Options</span>
        <button className="icon-button sidebar-toggle" type="button" title={collapsed ? "Expand navigation" : "Collapse navigation"} onClick={toggleCollapsed}>
          {collapsed ? <ChevronRight size={15} /> : <ChevronLeft size={15} />}
        </button>
      </div>
      <nav className="nav-tabs" aria-label="Primary navigation">
        {navItems.map((item) => {
          const Icon = item.icon;
          const active = pathname === item.href;
          return (
            <Link key={item.href} href={item.href} title={item.label} className={active ? "active" : ""}>
              <span className="nav-icon">
                <Icon size={17} />
              </span>
              <span className="nav-short">{item.short}</span>
              <span className="nav-label">{item.label}</span>
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}

