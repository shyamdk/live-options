"use client";

import { BarChart3, BookOpenText, BriefcaseBusiness, ChevronLeft, ChevronRight, Coins } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

// Gamma Blast, ema5, animesh-scalping, and BN Credit Spread are archived --
// their pages/background monitors still exist (see .env's *_MONITOR_ENABLED
// flags) but are intentionally kept off the nav to declutter around Theta
// Book as the active strategy. Re-add the entry + flip the flag to unarchive.
const navItems = [
  { href: "/manage-trades", label: "Manage Trades", short: "MT", icon: BriefcaseBusiness },
  { href: "/trade-journals", label: "Trade Journals", short: "TJ", icon: BookOpenText },
  { href: "/theta-book", label: "Theta Book", short: "TB", icon: Coins },
  { href: "/oi-analysis", label: "OI Analysis", short: "OI", icon: BarChart3 },
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

